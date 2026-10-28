"""Gameplay: the note highway, input, HUD, pause and fail/clear flow.

Latency notes:
  * Key presses are timestamped with ``perf_counter()`` when the event is
    processed and converted to song time by the conductor, so frame rate
    affects input timing by well under a frame (the loop runs at fps_cap).
  * Hit sounds are fired immediately on key down on reserved mixer channels.
  * Python's garbage collector is paused while playing to avoid hitches.
"""

from __future__ import annotations

import gc
import math
import time

import pygame

from ..audio.conductor import Conductor
from ..events import EventBus
from ..gameplay.modifiers import Modifier, prepare_play
from ..gameplay.session import PlaySession
from ..render import vector as V
from ..render.background import Background
from ..render.fx import ease_out_back
from ..render.playfield import Playfield
from ..render.widgets import Button, ButtonGroup, panel
from ..util import darken, hex_to_rgb, lighten, mix
from .base import Scene

ARROW_KEYS = [pygame.K_LEFT, pygame.K_DOWN, pygame.K_UP, pygame.K_RIGHT]


def lane_key_map(settings, lanes: int) -> dict[int, int]:
    mapping = {}
    for lane, name in enumerate(settings.keys_for(lanes)):
        try:
            mapping[pygame.key.key_code(name)] = lane
        except (ValueError, pygame.error):
            pass
    if lanes == 4:  # arrow keys always work too (FnF style)
        for lane, key in enumerate(ARROW_KEYS):
            mapping.setdefault(key, lane)
    return mapping


class GameplayScene(Scene):
    key_repeat = None
    menu_music = False

    def __init__(self, app, song, chart, difficulty: str, modifier_ids=(), start_time: float | None = None,
                 from_editor: bool = False):
        super().__init__(app)
        self.song = song
        self.source_chart = chart
        self.difficulty = difficulty
        self.modifier_ids = list(modifier_ids)
        self.start_time = start_time
        self.from_editor = from_editor
        settings = app.settings
        seed = sum(map(ord, song.id)) + int(time.time()) % 1000
        play_chart, self.rules, self.mods = prepare_play(chart, self.modifier_ids, settings.ghost_tapping,
                                                         settings.no_fail, seed=seed)
        self.bus = EventBus()
        self.session = PlaySession(play_chart, self.rules, self.mods, self.bus,
                                   start_time=start_time if start_time is not None else -math.inf)
        self.lanes = play_chart.lanes
        self.grid = song.grid
        self.key_lanes = lane_key_map(settings, self.lanes)
        w, h = self.size
        self.playfield = Playfield(self.theme, settings, self.lanes, self.ui.scale, self.size,
                                   speed_scale=self.rules.scroll_speed_scale)
        self.times = [n.time for n in self.session.notes]
        self.max_hold = max((n.end - n.time for n in self.session.notes), default=0.0)
        alpha_mods = [m for m in self.mods if type(m).note_alpha is not Modifier.note_alpha]
        self.alpha_fn = (lambda p: min(m.note_alpha(p) for m in alpha_mods)) if alpha_mods else None
        self.conductor = Conductor(app.audio, offset_ms=settings.audio_offset_ms)
        self.background = Background(self.size, self.theme, self.ui.scale, seed=len(song.id),
                                     dim=settings.background_dim)
        self.hitsounds = settings.hitsounds
        self.hit_volume = settings.hitsound_volume * settings.sfx_volume
        self.down = settings.scroll_direction != "up"

        # HUD state
        self.popups = {j.id: self.fonts.render(j.label, "display", 40, j.color, outline=5, shadow=4)
                       for j in self.rules.judgements}
        self.popups["miss"] = self.fonts.render(self.rules.miss.label, "display", 40, self.rules.miss.color,
                                                outline=5, shadow=4)
        self.popup = None
        self.popup_age = 9.0
        self.early_late = None
        self.combo_bump = 0.0
        self.error_ticks: list[list] = []
        self.shown_score = 0.0
        self.shown_health = self.session.health
        self.hold_tick = 0.0
        self.paused = False
        self.end_timer = None
        self.end_banner = None
        self.fail_shake = 0.0
        self.countdown_beats: list[float] = []
        self.countdown_next = 0
        self._summary = None

        self.bus.on("judgement", self._on_judgement)
        self.bus.on("hold_drop", self._on_hold_drop)
        self.bus.on("hold_complete", lambda **kw: self.playfield.on_hit(kw["note"].lane, "great", None))
        self.bus.on("fail", self._on_fail)
        self.bus.on("finish", self._on_finish)
        self.bus.on("combo_milestone", lambda **kw: self.app.sfx("combo", 0.5))
        self.bus.on("auto_press", self._on_auto_press)

        bw, bh = self.s(320), self.s(64)
        x = w // 2 - bw // 2
        resume_label = "Back to editor" if from_editor else "Quit to songs"
        self.pause_buttons = [
            Button(self.ui, (x, self.s(300), bw, bh), "Resume", self.resume_play, color=self.theme.c("accent")),
            Button(self.ui, (x, self.s(380), bw, bh), "Restart", self.restart, color=self.theme.c("accent3")),
            Button(self.ui, (x, self.s(460), bw, bh), resume_label, self.quit, color=self.theme.c("panel_light")),
        ]
        self.pause_group = ButtonGroup(self.pause_buttons)
        self.pause_panel = panel((self.s(420), self.s(420)), self.ui)
        self.dim = pygame.Surface(self.size, pygame.SRCALPHA)
        self.dim.fill((*darken(self.theme.c("ink"), 0.4), 170))
        self.heart = self._heart(self.s(40))

    # ------------------------------------------------------------ lifecycle
    def enter(self) -> None:
        self.conductor.load(self.song.audio_path, duration=self.song.duration)
        self.app.audio.set_music_volume(self.app.settings.music_volume)
        notes = [n for n in self.session.notes if not n.judged]
        first = notes[0].time if notes else 0.0
        beat = self.grid.beat_length_at(max(0.0, first))
        lead = max(2.0, 4 * beat + 0.4)
        if self.start_time is not None:
            start = self.start_time - lead
        else:
            start = min(-1.0, first - lead) if first < lead else 0.0
        if self.app.settings.countdown and first - start >= 4 * beat:
            b0 = round(self.grid.beat_at(first))
            self.countdown_beats = [self.grid.time_at(b0 - k) for k in (3, 2, 1, 0)]
        gc.collect()
        gc.disable()
        self.conductor.play(start)

    def leave(self) -> None:
        self.conductor.stop()
        gc.enable()

    # ------------------------------------------------------------ bus handlers
    def _on_judgement(self, session, note, judgement, error) -> None:
        self.popup = self.popups.get(judgement.id)
        self.popup_age = 0.0
        if judgement.is_miss:
            self.early_late = None
        else:
            self.playfield.on_hit(note.lane, judgement.id, judgement.color)
            self.combo_bump = 1.0
            self.error_ticks.append([error, 0.0, judgement.color])
            self.error_ticks = self.error_ticks[-40:]
            if judgement.id != self.rules.judgements[0].id and error is not None:
                self.early_late = ("EARLY", self.theme.c("accent3")) if error < 0 else ("LATE", self.theme.c("accent5"))
            else:
                self.early_late = None

    def _on_hold_drop(self, session, note) -> None:
        self.popup = self.popups["miss"]
        self.popup_age = 0.0

    def _on_auto_press(self, session, lane) -> None:
        if self.hitsounds:
            self.app.audio.play_sfx("hit", self.hit_volume)

    def _on_fail(self, session) -> None:
        self.end_banner = ("FAILED", self.theme.c("bad"))
        self.end_timer = 0.0
        self.fail_shake = 1.0
        self.app.audio.fadeout_music(900)
        self.app.sfx("fail", 0.8)

    def _on_finish(self, session) -> None:
        if self.end_banner is None:
            fc = session.full_combo
            self.end_banner = ("FULL COMBO!" if fc else "CLEAR!", self.theme.c("accent2") if fc else self.theme.c("good"))
            self.end_timer = 0.0

    # ------------------------------------------------------------ actions
    def pause_play(self) -> None:
        if self.paused or self.end_timer is not None:
            return
        self.paused = True
        self.conductor.pause()
        for lane in range(self.lanes):
            self.session.release(lane, self.conductor.time)
        self.pause_group.focus(0)
        self.app.sfx("ui_back")

    def resume_play(self) -> None:
        if self.paused:
            self.paused = False
            self.conductor.resume()

    def restart(self) -> None:
        self.app.replace(GameplayScene(self.app, self.song, self.source_chart, self.difficulty, self.modifier_ids,
                                       self.start_time, self.from_editor))

    def quit(self) -> None:
        self.conductor.stop()
        if self.from_editor:
            self.app.pop(playtest=self.session.summary())
        else:
            self.app.pop()

    def _finish_scene(self) -> None:
        summary = self.session.summary()
        if self.from_editor:
            self.app.pop(playtest=summary)
            return
        from .results import ResultsScene

        self.app.replace(ResultsScene(self.app, self.song, self.source_chart, self.difficulty, summary,
                                      self.modifier_ids, self.mods, errors=list(self.session.errors)))

    # ------------------------------------------------------------ events
    def handle_event(self, e) -> None:
        if e.type == pygame.KEYDOWN:
            lane = self.key_lanes.get(e.key)
            if lane is not None and not self.paused:
                t = self.conductor.time_at(time.perf_counter())
                if self.hitsounds and not self.rules.autoplay:
                    self.app.audio.play_sfx("hit", self.hit_volume)
                self.session.press(lane, t)
                return
            if self.paused:
                if e.key == pygame.K_ESCAPE:
                    self.resume_play()
                elif e.key == pygame.K_r:
                    self.restart()
                elif e.key == pygame.K_q:
                    self.quit()
                else:
                    self.pause_group.handle_event(e)
                return
            if e.key in (pygame.K_ESCAPE, pygame.K_PAUSE, pygame.K_RETURN):
                self.pause_play()
            elif e.key == pygame.K_r and e.mod & pygame.KMOD_CTRL:
                self.restart()
            return
        if e.type == pygame.KEYUP:
            lane = self.key_lanes.get(e.key)
            if lane is not None and not self.paused:
                self.session.release(lane, self.conductor.time_at(time.perf_counter()))
            return
        if e.type in (pygame.WINDOWFOCUSLOST, pygame.WINDOWMINIMIZED) and not self.paused:
            self.pause_play()
            return
        if self.paused:
            self.pause_group.handle_event(e)

    # ------------------------------------------------------------ update
    def update(self, dt: float) -> None:
        if self.paused:
            self.pause_group.update(dt)
            return
        self.conductor.update()
        t = self.conductor.time
        if self.end_timer is None or not self.session.failed:
            self.session.update(t)
        self.playfield.update(dt, self.session.pressed)
        self.background.update(dt, float(self.grid.beat_at(t)))
        self.popup_age += dt
        self.combo_bump = max(0.0, self.combo_bump - dt * 6)
        for tick in self.error_ticks:
            tick[1] += dt
        self.error_ticks = [tk for tk in self.error_ticks if tk[1] < 3.0]
        self.shown_score += (self.session.score - self.shown_score) * min(1.0, dt * 12)
        self.shown_health += (self.session.health - self.shown_health) * min(1.0, dt * 10)
        if self.session.active_holds:
            self.hold_tick += dt
            if self.hold_tick > 0.07:
                self.hold_tick = 0.0
                for lane in self.session.active_holds:
                    self.playfield.on_hold_tick(lane)
        while self.countdown_next < len(self.countdown_beats) and t >= self.countdown_beats[self.countdown_next]:
            self.app.sfx("tick_accent" if self.countdown_next == 3 else "tick", 0.6)
            self.countdown_next += 1
        if self.conductor.state == "ended" and not self.session.finished and not self.session.failed:
            self.session.update(self.session.end_time + 10.0)
        if self.end_timer is not None:
            self.end_timer += dt
            self.fail_shake = max(0.0, self.fail_shake - dt * 2)
            if self.end_timer > (2.0 if self.session.failed else 1.6):
                self.end_timer = None
                self._finish_scene()

    # ------------------------------------------------------------ drawing
    def draw(self, surf) -> None:
        t = self.conductor.time
        pf = self.playfield
        self.background.draw(surf)
        pf.draw_panel(surf)
        pf.draw_beams(surf, self.session.pressed)
        if pf.show_beat_lines:
            pf.draw_grid(surf, t, self.grid)
        pf.draw_chart(surf, t, self.session.notes, self.times, self.session.pressed, self.max_hold, self.alpha_fn)
        pf.draw_effects(surf)
        self._draw_hud(surf, t)
        self._draw_countdown(surf, t)
        if self.end_banner is not None:
            self._draw_banner(surf)
        if self.paused:
            self._draw_pause(surf)

    def _heart(self, size: int) -> pygame.Surface:
        ink, color = self.theme.c("ink"), self.theme.c("bad")

        def draw(s, k):
            u = size * k
            pts = [(0.5 * u, 0.9 * u), (0.12 * u, 0.48 * u), (0.88 * u, 0.48 * u)]
            for col, grow in ((ink, 0.09 * u), (color, 0.0)):
                pygame.draw.circle(s, col, (0.32 * u, 0.36 * u), 0.2 * u + grow)
                pygame.draw.circle(s, col, (0.68 * u, 0.36 * u), 0.2 * u + grow)
                V.rounded_polygon(s, col, pts, grow + 0.02 * u)
            pygame.draw.circle(s, lighten(color, 0.5), (0.3 * u, 0.32 * u), 0.06 * u)

        return V.supersample((size, size), draw)

    def _draw_hud(self, surf, t: float) -> None:
        w, h = self.size
        pf = self.playfield
        theme = self.theme
        session = self.session
        cx = pf.x0 + pf.width / 2
        mid_y = h * (0.42 if self.down else 0.58)
        shake = math.sin(time.perf_counter() * 60) * self.s(10) * self.fail_shake

        # judgement popup + early/late
        if self.popup is not None and self.popup_age < 0.6:
            scale = 1.25 - 0.25 * ease_out_back(min(1.0, self.popup_age / 0.12))
            img = self.popup
            if abs(scale - 1.0) > 0.01:
                img = pygame.transform.smoothscale(img, (int(img.get_width() * scale), int(img.get_height() * scale)))
            fade = 1.0 if self.popup_age <= 0.4 else 1 - (self.popup_age - 0.4) / 0.2
            if img is self.popup:
                img = img.copy()
            img.set_alpha(int(225 * fade))
            surf.blit(img, img.get_rect(center=(cx + shake, mid_y)))
            if self.early_late:
                label, color = self.early_late
                self.fonts.draw(surf, label, (cx, mid_y - self.s(42)), "bold", 18, color, anchor="center", outline=3)

        # combo
        if session.combo >= 3:
            scale = 1.0 + 0.18 * self.combo_bump
            img = self.fonts.render(str(session.combo), "display", 48, (255, 255, 255), outline=5, shadow=4)
            if scale > 1.01:
                img = pygame.transform.smoothscale(img, (int(img.get_width() * scale), int(img.get_height() * scale)))
            else:
                img = img.copy()
            img.set_alpha(200)
            surf.blit(img, img.get_rect(center=(cx, mid_y + self.s(56))))
            self.fonts.draw(surf, "combo", (cx, mid_y + self.s(92)), "bold", 17, theme.c("text_dim"),
                            anchor="center", outline=2)

        # timing bar, tucked just outside the receptors
        if self.app.settings.show_hit_error:
            gap = pf.lane_w * 0.5 + self.s(24)
            self._draw_error_bar(surf, cx, pf.receptor_y + (gap if self.down else -gap))

        # score / accuracy (top right)
        right = w - self.s(28)
        self.fonts.draw(surf, f"{int(round(self.shown_score)):,}", (right, self.s(18)), "display", 44,
                        (255, 255, 255), anchor="topright", outline=5, shadow=5)
        grade, gcolor = self.rules.grade_for(session.accuracy)
        acc_rect = self.fonts.draw(surf, f"{session.accuracy * 100:.2f}%", (right, self.s(76)), "display", 30,
                                   (255, 255, 255), anchor="topright", outline=4, shadow=4)
        self.fonts.draw(surf, grade, (acc_rect.left - self.s(12), self.s(76)), "display", 30, gcolor,
                        anchor="topright", outline=4, shadow=4)
        self.fonts.draw(surf, f"Misses {session.misses}", (right, self.s(118)), "bold", 20, theme.c("text_dim"),
                        anchor="topright", outline=2)
        y = self.s(150)
        for m in self.mods:
            text = m.hud_text()
            if text:
                self.fonts.draw(surf, text, (right, y), "bold", 20, hex_to_rgb(m.color), anchor="topright",
                                outline=2)
                y += self.s(28)

        # song info (top left), never running into the lanes
        info_w = max(120, min(340, (pf.x0 - self.s(46)) / self.ui.scale))
        self.fonts.draw(surf, self.song.title, (self.s(26), self.s(20)), "bold", 26, (255, 255, 255), outline=3,
                        max_width=info_w)
        self.fonts.draw(surf, self.song.artist, (self.s(26), self.s(56)), "ui", 19, theme.c("text_dim"), outline=2,
                        max_width=info_w)
        x = self.s(26)
        if not hasattr(self, "_pills"):
            self._pills = []
            for label, color in [(self.difficulty.title(), theme.c("accent2"))] + \
                                [(m.name, hex_to_rgb(m.color)) for m in self.mods]:
                img = self.fonts.render(label, "bold", 16, theme.c("ink"))
                box = V.rounded_rect((img.get_width() + self.s(18), self.s(28)), self.s(14), color, theme.c("ink"),
                                     outline=max(2, self.s(2.5)))
                box.blit(img, img.get_rect(center=(box.get_width() / 2, self.s(14))))
                self._pills.append(box)
        for box in self._pills:
            surf.blit(box, (x, self.s(88)))
            x += box.get_width() + self.s(6)

        # progress along the song (top edge)
        end = max(1.0, session.end_time)
        progress = max(0.0, min(1.0, t / end))
        pygame.draw.rect(surf, darken(theme.c("ink"), 0.2), (0, 0, w, self.s(7)))
        pygame.draw.rect(surf, theme.c("accent2"), (0, 0, int(w * progress), self.s(7)))

        # health (right of the playfield)
        hx = pf.x0 + pf.width + self.s(38)
        bar = pygame.Rect(0, 0, self.s(22), int(h * 0.52))
        bar.midtop = (hx, int(h * 0.24))
        pygame.draw.rect(surf, theme.c("ink"), bar.inflate(self.s(8), self.s(8)), border_radius=self.s(15))
        pygame.draw.rect(surf, theme.c("panel"), bar, border_radius=self.s(11))
        frac = max(0.0, min(1.0, self.shown_health / self.rules.health_max))
        fill = bar.copy()
        fill.height = int(bar.height * frac)
        fill.bottom = bar.bottom
        color = mix(theme.c("bad"), theme.c("good"), min(1.0, frac * 1.6))
        if fill.height > 0:
            pygame.draw.rect(surf, color, fill, border_radius=self.s(11))
            shine = fill.inflate(-self.s(12), -self.s(6))
            shine.x -= self.s(3)
            pygame.draw.rect(surf, lighten(color, 0.4), shine, border_radius=self.s(6))
        throb = 1.0 + (0.12 * abs(math.sin(time.perf_counter() * 9)) if frac < 0.25 else 0.0)
        heart = self.heart if throb == 1.0 else pygame.transform.smoothscale(
            self.heart, (int(self.heart.get_width() * throb), int(self.heart.get_height() * throb)))
        surf.blit(heart, heart.get_rect(center=(hx, bar.top - self.s(18))))

        if self.rules.autoplay:
            self.fonts.draw(surf, "AUTOPLAY", (cx, h - self.s(20) if not self.down else self.s(28)), "display", 26,
                            theme.c("accent3"), anchor="center", outline=4)

    def _draw_error_bar(self, surf, cx: float, y: float) -> None:
        width = self.s(260)
        max_w = self.rules.max_window
        theme = self.theme
        rect = pygame.Rect(0, 0, width, self.s(10))
        rect.center = (int(cx), int(y))
        pygame.draw.rect(surf, theme.c("ink"), rect.inflate(self.s(6), self.s(6)), border_radius=self.s(8))
        for j in reversed(self.rules.judgements):
            zw = int(width * (j.window * self.rules.window_scale) / max_w)
            zone = pygame.Rect(0, 0, zw, rect.height)
            zone.center = rect.center
            pygame.draw.rect(surf, darken(j.color, 0.25), zone, border_radius=self.s(5))
        pygame.draw.rect(surf, (255, 255, 255), (rect.centerx - 1, rect.y - self.s(6), 3, rect.height + self.s(12)))
        for err, age, color in self.error_ticks:
            x = rect.centerx + err / max_w * width / 2
            a = max(0.0, 1.0 - age / 3.0)
            col = mix(darken(theme.c("ink"), 0.1), lighten(color, 0.2), a)
            pygame.draw.rect(surf, col, (x - 1, rect.y - self.s(8), max(2, self.s(3)), rect.height + self.s(16)))

    def _draw_countdown(self, surf, t: float) -> None:
        if not self.countdown_beats:
            return
        labels = ["3", "2", "1", "GO!"]
        for i, bt in enumerate(self.countdown_beats):
            age = t - bt
            if 0 <= age < 0.5:
                scale = 0.6 + 0.4 * ease_out_back(min(1.0, age / 0.15))
                color = self.theme.c("accent2") if i == 3 else (255, 255, 255)
                img = self.fonts.render(labels[i], "display", 120, color, outline=8, shadow=10)
                img = pygame.transform.smoothscale(img, (int(img.get_width() * scale), int(img.get_height() * scale)))
                if age > 0.3:
                    img.set_alpha(int(255 * (1 - (age - 0.3) / 0.2)))
                pf = self.playfield
                surf.blit(img, img.get_rect(center=(pf.x0 + pf.width / 2, self.size[1] * 0.4)))

    def _draw_banner(self, surf) -> None:
        text, color = self.end_banner
        age = self.end_timer or 0.0
        scale = ease_out_back(min(1.0, age / 0.3))
        img = self.fonts.render(text, "display", 96, color, outline=8, shadow=10)
        if scale < 0.999:
            img = pygame.transform.smoothscale(img, (max(1, int(img.get_width() * scale)),
                                                     max(1, int(img.get_height() * scale))))
        shake = math.sin(time.perf_counter() * 70) * self.s(14) * self.fail_shake
        surf.blit(img, img.get_rect(center=(self.size[0] / 2 + shake, self.size[1] * 0.45)))

    def _draw_pause(self, surf) -> None:
        surf.blit(self.dim, (0, 0))
        r = self.pause_panel.get_rect(center=(self.size[0] // 2, self.s(370)))
        surf.blit(self.pause_panel, r)
        self.fonts.draw(surf, "Paused", (r.centerx, r.y + self.s(52)), "display", 52, (255, 255, 255),
                        anchor="center", outline=5, shadow=6)
        self.pause_group.draw(surf)
        self.fonts.draw(surf, "Esc resume  -  R restart  -  Q quit", (r.centerx, r.bottom - self.s(26)), "bold", 18,
                        self.theme.c("text_dim"), anchor="center", outline=2)
