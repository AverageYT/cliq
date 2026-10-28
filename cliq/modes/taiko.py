"""Taiko: a drum mode in the style of Taiko no Tatsujin.

Notes slide right-to-left into the drum. Red "don" notes are hit with the
inner keys (F / K), blue "ka" notes with the outer keys (D / L). Big notes
award a bonus when both hands hit them together; yellow drumrolls want as many
hits as you can fit. The charter favours percussive onsets: kicks become don,
snares and hats become ka.
"""

from __future__ import annotations

import math

import pygame

from ..charting.autochart import _det_noise, chart_meta, plan_chart, resolve_profile
from ..charting.chart import Chart, Note
from ..gameplay.session import PlaySession
from ..render import vector as V
from ..render.fx import Particles, ease_out_cubic
from ..util import darken, lighten
from .base import GameMode, ModeView, keycodes

DON, KA = 0, 1
DON_COLOR = (255, 84, 84)
KA_COLOR = (61, 184, 255)
ROLL_COLOR = (255, 210, 63)


class TaikoSession(PlaySession):
    DOUBLE_WINDOW = 0.05       # second hand on the same drum within this counts as "both hands"
    ROLL_SCORE = 30

    def __init__(self, chart, rules, modifiers=(), bus=None, start_time=-math.inf):
        super().__init__(chart, rules, modifiers, bus, start_time)
        self.rolls = [ns for ns in self.notes if ns.kind == "roll"]
        for q in self._queues:
            q[:] = [ns for ns in q if ns.kind != "roll"]
        self.roll_hits = 0
        self._last_hit: dict[int, tuple[float, object]] = {}
        self._auto_roll = -1.0

    def active_roll(self, t: float):
        for r in self.rolls:
            if not r.judged and r.time - 0.03 <= t <= r.end:
                return r
        return None

    def press(self, lane, t):
        if not 0 <= lane < self.lanes:
            return None
        self.pressed[lane] = True
        if self.failed or self.finished or self.rules.autoplay:
            return None
        roll = self.active_roll(t)
        if roll is not None:
            self._roll_hit(roll, lane)
            return None
        last = self._last_hit.get(lane)
        if last is not None and t - last[0] <= self.DOUBLE_WINDOW:
            note = last[1]
            if note.kind == "big" and not getattr(note, "big_bonus", False):
                note.big_bonus = True
                self.score += int(round(150 * self.rules.score_multiplier))
                self.bus.emit("big_bonus", session=self, note=note)
            return None   # the other hand on the same drum is never a stray press
        ns = super().press(lane, t)
        if ns is not None:
            self._last_hit[lane] = (t, ns)
        return ns

    def _roll_hit(self, roll, lane) -> None:
        self.roll_hits += 1
        roll.roll_hits = getattr(roll, "roll_hits", 0) + 1
        self.score += int(round(self.ROLL_SCORE * self.rules.score_multiplier))
        self.bus.emit("roll_hit", session=self, note=roll, lane=lane)

    def update(self, t):
        if not (self.failed or self.finished):
            for r in self.rolls:
                if r.judged:
                    continue
                if self.rules.autoplay and r.time <= t <= r.end and t - self._auto_roll >= 1 / 12:
                    self._auto_roll = t
                    self._roll_hit(r, DON)
                if t >= r.end:
                    r.judged, r.result = True, "roll"
                    self._judged += 1
        super().update(t)


class TaikoMode(GameMode):
    id = "taiko"
    name = "Taiko"
    tagline = "Drum along: F/K for red don, D/L for blue ka"
    color = "#FF5454"

    def generate(self, analysis, difficulty, grid, settings, seed=0):
        profile = resolve_profile(difficulty)

        def drums(ons):
            perc = (ons.low + ons.high) / (ons.low + ons.mid + ons.high + 1e-6)
            return 0.45 + perc

        plan = plan_chart(analysis, profile, grid, salience=drums, density=0.85)
        chart = Chart(lanes=2, difficulty=self.chart_stem(profile.id), mode=self.id,
                      meta=chart_meta(profile, grid, seed, mode=self.id))
        if plan is None:
            return chart
        ons = plan.onsets
        notes = []
        last_big = -10.0
        for i, t in enumerate(plan.times):
            k = plan.onset[i]
            beat = grid.beat_length_at(t)
            if k >= 0:
                low, mid, high = float(ons.low[k]), float(ons.mid[k]), float(ons.high[k])
                lane = DON if low >= 0.85 * max(mid, high) else KA
            else:
                lane = DON if plan.level[i] <= 1 else KA
            if plan.duration[i] >= beat * 0.9:
                notes.append(Note(t, DON, plan.duration[i], "roll"))
                continue
            big = (plan.level[i] <= 1 and plan.intensity(i) >= profile.chord_threshold and t - last_big >= 2 * beat
                   and _det_noise(seed, t) < 0.6)
            if big:
                last_big = t
            notes.append(Note(t, lane, 0.0, "big" if big else "tap"))
        chart.notes = notes
        return chart.sort()

    def lanes(self, chart):
        return 2

    def key_map(self, settings, chart):
        keys = keycodes(settings.keys_for(4))
        mapping = {}
        for i, code in enumerate(keys):
            if code is not None:
                mapping[code] = KA if i in (0, 3) else DON
        mapping.setdefault(pygame.K_LEFT, KA)
        mapping.setdefault(pygame.K_RIGHT, KA)
        mapping.setdefault(pygame.K_DOWN, DON)
        mapping.setdefault(pygame.K_UP, DON)
        return mapping

    def key_hint(self, settings, chart):
        k = [x.upper() for x in settings.keys_for(4)]
        return f"{k[1]} {k[2]} = red don   {k[0]} {k[3]} = blue ka"

    def session(self, chart, rules, modifiers, bus, start_time):
        return TaikoSession(chart, rules, modifiers, bus, start_time=start_time)

    def view(self, scene):
        return TaikoView(scene)


def _drum_note(size: int, color, big: bool = False) -> pygame.Surface:
    ink = (27, 18, 54)

    def draw(s, k):
        r = size * k / 2
        c = (r, r)
        pygame.draw.circle(s, ink, c, r)
        pygame.draw.circle(s, (255, 255, 255), c, r * 0.86)
        pygame.draw.circle(s, ink, c, r * 0.74)
        pygame.draw.circle(s, darken(color, 0.15), c, r * 0.66)
        pygame.draw.circle(s, color, (r, r * 0.95), r * 0.6)
        pygame.draw.circle(s, lighten(color, 0.55), (r * 0.72, r * 0.68), r * 0.16)

    return V.supersample((size, size), draw)


class TaikoView(ModeView):
    def __init__(self, scene):
        super().__init__(scene)
        w, h = scene.size
        s = scene.s
        settings = scene.app.settings
        self.track_y = int(h * 0.44)
        self.track_h = s(132)
        self.hit_x = int(w * 0.24)
        self.speed = 560 * settings.scroll_speed * scene.rules.scroll_speed_scale * scene.ui.scale
        self.note_size = s(84)
        self.don = _drum_note(self.note_size, DON_COLOR)
        self.ka = _drum_note(self.note_size, KA_COLOR)
        self.big_don = _drum_note(int(self.note_size * 1.38), DON_COLOR)
        self.big_ka = _drum_note(int(self.note_size * 1.38), KA_COLOR)
        self.roll_head = _drum_note(self.note_size, ROLL_COLOR)
        self.health_x = w - s(52)
        self.track = V.rounded_rect((self.health_x - s(40) - int(w * 0.03), self.track_h), s(30),
                                    (*scene.theme.c("panel"), 228), scene.theme.c("ink"), outline=max(2, s(3.5)))
        self.target = V.ring(int(self.note_size * 0.56), s(5), (255, 255, 255))
        self.target_big = V.ring(int(self.note_size * 0.76), s(3), (200, 190, 240))
        self.particles = Particles(scene.ui.scale)
        self.flash = [9.0, 9.0]
        self.flying: list[list] = []
        self.center_x = self.hit_x
        self.judge_y = self.track_y - s(178)
        self.countdown_y = self.track_y - s(170)
        self.error_y = self.track_y + self.track_h / 2 + s(34)
        self.info_limit = w * 0.45
        self.ahead = (w - self.hit_x) / self.speed
        self.autoplay_y = s(30)
        self.hint = scene.mode.key_hint(settings, scene.session.chart)

    def update(self, dt, t):
        self.particles.update(dt)
        self.flash = [f + dt for f in self.flash]
        for f in self.flying:
            f[2] += dt
        self.flying = [f for f in self.flying if f[2] < 0.45]

    def on_judgement(self, note, judgement, error):
        if judgement.is_miss:
            return
        self.flash[note.lane] = 0.0
        color = DON_COLOR if note.lane == DON else KA_COLOR
        self.particles.burst(self.hit_x, self.track_y, lighten(color, 0.3), count=9, speed=520, spread=math.tau)
        self.flying.append([note.kind == "big", note.lane, 0.0])

    def draw(self, surf, t):
        scene = self.scene
        s = scene.s
        theme = scene.theme
        w, h = scene.size
        x0 = int(w * 0.03)
        surf.blit(self.track, (x0, self.track_y - self.track_h // 2))
        # drum
        dx = x0 + s(74)
        pressed = scene.session.pressed
        rim = lighten(KA_COLOR, 0.35) if pressed[KA] else darken(KA_COLOR, 0.35)
        face = lighten(DON_COLOR, 0.35) if pressed[DON] else darken(DON_COLOR, 0.3)
        pygame.draw.circle(surf, theme.c("ink"), (dx, self.track_y), s(56))
        pygame.draw.circle(surf, rim, (dx, self.track_y), s(51))
        pygame.draw.circle(surf, theme.c("ink"), (dx, self.track_y), s(37))
        pygame.draw.circle(surf, face, (dx, self.track_y), s(33))
        # target
        surf.blit(self.target_big, self.target_big.get_rect(center=(self.hit_x, self.track_y)))
        surf.blit(self.target, self.target.get_rect(center=(self.hit_x, self.track_y)))
        for lane in (DON, KA):
            if self.flash[lane] < 0.12:
                a = 1 - self.flash[lane] / 0.12
                color = DON_COLOR if lane == DON else KA_COLOR
                pygame.draw.circle(surf, lighten(color, 0.4), (self.hit_x, self.track_y),
                                   int(self.note_size * (0.55 + 0.25 * (1 - a))), max(2, s(6 * a)))
        # notes (draw far ones first so near ones are on top)
        notes = scene.session.notes
        right = w + self.note_size
        visible = []
        for n in notes:
            x = self.hit_x + (n.time - t) * self.speed
            if x > right + 40:
                break
            end_x = self.hit_x + (n.end - t) * self.speed
            if end_x < -self.note_size:
                continue
            visible.append((n, x, end_x))
        for n, x, end_x in reversed(visible):
            if n.kind == "roll":
                if n.judged:
                    continue
                start = max(x, self.hit_x) if t >= n.time else x
                body = pygame.Rect(0, 0, max(0, end_x - start), int(self.note_size * 0.62))
                body.midleft = (start, self.track_y)
                if body.width > 0:
                    pygame.draw.rect(surf, theme.c("ink"), body.inflate(s(6), s(6)), border_radius=body.height)
                    pygame.draw.rect(surf, ROLL_COLOR, body, border_radius=body.height)
                    pygame.draw.circle(surf, lighten(ROLL_COLOR, 0.4), (end_x, self.track_y), body.height // 2)
                img = self.roll_head
                surf.blit(img, img.get_rect(center=(start, self.track_y)))
                hits = getattr(n, "roll_hits", 0)
                if hits:
                    scene.fonts.draw(surf, str(hits), (start, self.track_y - s(60)), "display", 26, ROLL_COLOR,
                                     anchor="center", outline=3)
                continue
            if n.result not in (None, "miss"):
                continue
            big = n.kind == "big"
            img = (self.big_don if big else self.don) if n.lane == DON else (self.big_ka if big else self.ka)
            if n.result == "miss":
                img.set_alpha(90)
                surf.blit(img, img.get_rect(center=(x, self.track_y)))
                img.set_alpha(255)
            else:
                surf.blit(img, img.get_rect(center=(x, self.track_y)))
        # hit notes fly up to the top-left like in taiko
        for big, lane, age in self.flying:
            p = ease_out_cubic(age / 0.45)
            img = (self.big_don if big else self.don) if lane == DON else (self.big_ka if big else self.ka)
            fx = self.hit_x + (s(160) - self.hit_x) * p * 0.4
            fy = self.track_y - s(260) * p
            img.set_alpha(int(255 * (1 - p)))
            surf.blit(img, img.get_rect(center=(fx, fy)))
            img.set_alpha(255)
        self.particles.draw(surf)
        scene.fonts.draw(surf, self.hint, (self.health_x - s(50), self.track_y + self.track_h / 2 + s(14)), "bold",
                         18, theme.c("text_dim"), anchor="topright", outline=2)
