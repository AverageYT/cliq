"""Song select: browse songs, pick a difficulty and modifiers, play or map."""

from __future__ import annotations

import time
import zlib

import pygame

from ..charting.autochart import generate_chart
from ..charting.profiles import get_profile, load_profiles
from ..gameplay.modifiers import REGISTRY
from ..render import vector as V
from ..render.widgets import Button, Pill, panel
from ..util import darken, format_time, hex_to_rgb, lighten
from .base import Scene

CARD_H, CARD_GAP = 82, 12


def _song_color(song_id: str, theme):
    colors = theme.shape_colors
    return colors[zlib.crc32(song_id.encode()) % len(colors)]


class SongSelectScene(Scene):
    def __init__(self, app, select: str | None = None):
        super().__init__(app)
        self.songs = []
        self.index = 0
        self.scroll = 0.0
        self.diff_index = 0
        self.charts: list[str] = []
        self.chart_stats: dict[str, dict] = {}
        self._covers: dict = {}
        self._cards: dict = {}
        self._confirm_delete = 0.0
        self._last_click = (0.0, -1)
        self._select_on_enter = select or app.settings.last_song
        w, h = self.size
        self.list_rect = pygame.Rect(self.s(36), self.s(92), self.s(560), h - self.s(92) - self.s(40))
        self.panel_rect = pygame.Rect(self.s(626), self.s(86), w - self.s(626) - self.s(36), h - self.s(86) - self.s(40))
        self.panel_img = panel(self.panel_rect.size, self.ui)
        px, pw = self.panel_rect.x, self.panel_rect.width
        bh = self.s(64)
        by = self.panel_rect.bottom - bh - self.s(22)
        theme = self.theme
        self.play_btn = Button(self.ui, (px + self.s(22), by, self.s(250), bh), "Play", self.play,
                               color=theme.c("accent"), size=34, sublabel="Enter")
        self.map_btn = Button(self.ui, (px + self.s(286), by, self.s(160), bh), "Map it", self.edit,
                              color=theme.c("accent3"), size=28, sublabel="E")
        self.add_btn = Button(self.ui, (px + pw - self.s(22) - self.s(130), by, self.s(130), bh), "Add", self.add_song,
                              color=theme.c("accent4"), size=28, sublabel="I", text_color=(255, 255, 255))
        self.buttons = [self.play_btn, self.map_btn, self.add_btn]
        self.mod_pills: list[Pill] = []
        self._build_mod_pills()
        self.diff_rects: list[tuple[pygame.Rect, int]] = []

    # ------------------------------------------------------------ data
    def enter(self) -> None:
        self.reload(self._select_on_enter)

    def resume(self, **result) -> None:
        self.reload(result.get("select") or (self.songs[self.index].id if self.songs else None))

    def on_library_changed(self) -> None:
        self.reload(self.songs[self.index].id if self.songs else None)

    def reload(self, select: str | None = None) -> None:
        self.songs = self.app.library.scan()
        self._cards.clear()
        self.index = 0
        for i, s in enumerate(self.songs):
            if s.id == select:
                self.index = i
        self.scroll = float(self.index)
        self._load_song()

    @property
    def song(self):
        return self.songs[self.index] if self.songs else None

    @property
    def difficulty(self) -> str | None:
        return self.charts[self.diff_index] if self.charts else None

    def _load_song(self) -> None:
        song = self.song
        self.charts, self.chart_stats = [], {}
        if song is None:
            self.app.menu_music.stop()
            return
        self.charts = song.chart_names()
        for name in self.charts:
            chart = song.load_chart(name)
            self.chart_stats[name] = chart.stats() if chart else {}
            if chart:
                self.chart_stats[name]["lanes"] = chart.lanes
        want = self.app.settings.last_difficulty or self.app.settings.default_difficulty
        self.diff_index = self.charts.index(want) if want in self.charts else min(1, max(0, len(self.charts) - 1))
        self.app.menu_music.play(song)

    def _build_mod_pills(self) -> None:
        enabled = set(self.app.settings.enabled_modifiers)
        x0 = self.panel_rect.x + self.s(22)
        x, y = x0, self.panel_rect.y + self.s(352)
        h = self.s(30)
        for mid, cls in REGISTRY.items():
            w = self.fonts.render(cls.name, "bold", 16).get_width() + self.s(24)
            if x + w > self.panel_rect.right - self.s(22):
                x, y = x0, y + h + self.s(8)
            pill = Pill(self.ui, (x, y, w, h), cls.name, hex_to_rgb(cls.color), mid in enabled,
                        on_toggle=lambda on, mid=mid: self.toggle_mod(mid, on), tooltip=cls.description)
            pill.mod_id = mid
            self.mod_pills.append(pill)
            x += w + self.s(10)

    def toggle_mod(self, mid: str, on: bool) -> None:
        mods = [m for m in self.app.settings.enabled_modifiers if m != mid]
        if on:
            mods.append(mid)
            for other in REGISTRY[mid].incompatible:
                if other in mods:
                    mods.remove(other)
        self.app.settings.enabled_modifiers = mods
        for p in self.mod_pills:
            p.active = p.mod_id in mods
        self.app.settings.save()

    # ------------------------------------------------------------ actions
    def select(self, i: int) -> None:
        if not self.songs:
            return
        i = max(0, min(len(self.songs) - 1, i))
        if i != self.index:
            self.index = i
            self.app.sfx("ui_move")
            self._confirm_delete = 0.0
            self._load_song()

    def change_difficulty(self, delta: int) -> None:
        if self.charts:
            self.diff_index = (self.diff_index + delta) % len(self.charts)
            self.app.settings.last_difficulty = self.difficulty
            self.app.sfx("ui_move")

    def _remember(self) -> None:
        self.app.settings.last_song = self.song.id if self.song else None
        self.app.settings.last_difficulty = self.difficulty
        self.app.settings.save()

    def play(self) -> None:
        song, diff = self.song, self.difficulty
        if song is None or diff is None:
            self.app.toasts.show("Add a song first - press I", self.theme.c("bad"))
            return
        chart = song.load_chart(diff)
        if chart is None or not chart.notes:
            self.app.toasts.show("That chart is empty - map it first (E)", self.theme.c("bad"))
            return
        self._remember()
        from .gameplay import GameplayScene

        self.app.push(GameplayScene(self.app, song, chart, diff, list(self.app.settings.enabled_modifiers)))

    def edit(self) -> None:
        song = self.song
        if song is None:
            return
        self._remember()
        from .editor import EditorScene

        self.app.push(EditorScene(self.app, song, self.difficulty or "custom"))

    def add_song(self) -> None:
        from .import_song import ImportScene

        self.app.push(ImportScene(self.app))

    def rechart(self) -> None:
        song = self.song
        if song is None:
            return
        analysis = song.load_analysis()
        if analysis is None:
            self.app.toasts.show("No analysis saved for this song - re-import it", self.theme.c("bad"))
            return
        lanes = self.app.settings.lane_count
        kept = 0
        for name in load_profiles():
            old = song.load_chart(name)
            if old is not None and old.meta.get("edited"):
                kept += 1
                continue
            song.save_chart(generate_chart(analysis, name, lanes=lanes, grid=song.grid))
        song.lanes = lanes
        song.save()
        self._load_song()
        msg = f"Re-charted for {lanes} keys" + (f" (kept {kept} hand-edited)" if kept else "")
        self.app.toasts.show(msg, self.theme.c("good"))

    def delete(self) -> None:
        song = self.song
        if song is None:
            return
        now = time.perf_counter()
        if now - self._confirm_delete > 3.0:
            self._confirm_delete = now
            self.app.toasts.show(f"Press Delete again to remove \"{song.title}\"", self.theme.c("bad"))
            return
        self.app.menu_music.stop()
        self.app.library.delete(song.id)
        self.app.toasts.show(f"Removed \"{song.title}\"")
        self._confirm_delete = 0.0
        self.reload(None)

    # ------------------------------------------------------------ events
    def handle_event(self, e) -> None:
        if e.type == pygame.KEYDOWN:
            k = e.key
            if k == pygame.K_ESCAPE:
                self.app.sfx("ui_back")
                self.app.pop()
            elif k == pygame.K_UP:
                self.select(self.index - 1)
            elif k == pygame.K_DOWN:
                self.select(self.index + 1)
            elif k == pygame.K_PAGEUP:
                self.select(self.index - 5)
            elif k == pygame.K_PAGEDOWN:
                self.select(self.index + 5)
            elif k == pygame.K_LEFT:
                self.change_difficulty(-1)
            elif k == pygame.K_RIGHT:
                self.change_difficulty(1)
            elif k in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.play()
            elif k == pygame.K_e:
                self.edit()
            elif k == pygame.K_i:
                self.add_song()
            elif k == pygame.K_r:
                self.rechart()
            elif k == pygame.K_DELETE:
                self.delete()
            return
        if e.type == pygame.DROPFILE:
            from .import_song import ImportScene

            scene = ImportScene(self.app)
            self.app.push(scene)
            scene.start(e.file)
            return
        if e.type == pygame.MOUSEWHEEL:
            self.select(self.index - e.y)
            return
        for b in self.buttons:
            if b.handle_event(e):
                return
        for p in self.mod_pills:
            if p.handle_event(e):
                return
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            for rect, i in self.diff_rects:
                if rect.collidepoint(e.pos):
                    self.diff_index = i
                    self.app.settings.last_difficulty = self.difficulty
                    self.app.sfx("ui_move")
                    return
            if self.list_rect.collidepoint(e.pos):
                i = self._card_at(e.pos[1])
                if i is not None:
                    now = time.perf_counter()
                    if self._last_click[1] == i and now - self._last_click[0] < 0.35:
                        self.play()
                    self._last_click = (now, i)
                    self.select(i)

    def _card_at(self, y: int) -> int | None:
        step = self.s(CARD_H + CARD_GAP)
        top = self.list_rect.y + self.list_rect.height // 2 - self.s(CARD_H) // 2 - self.scroll * step
        i = int((y - top) // step)
        return i if 0 <= i < len(self.songs) else None

    def update(self, dt: float) -> None:
        self.scroll += (self.index - self.scroll) * min(1.0, dt * 12)
        for b in self.buttons:
            b.update(dt)

    # ------------------------------------------------------------ drawing
    def _cover(self, song, size: int) -> pygame.Surface:
        key = (song.id, size)
        img = self._covers.get(key)
        if img is not None:
            return img
        ink = self.theme.c("ink")
        base = None
        if song.cover_path and song.cover_path.exists():
            try:
                raw = pygame.image.load(str(song.cover_path)).convert()
                rw, rh = raw.get_size()
                side = min(rw, rh)
                raw = raw.subsurface(((rw - side) // 2, (rh - side) // 2, side, side))
                base = pygame.transform.smoothscale(raw, (size, size))
            except pygame.error:
                base = None
        if base is None:
            color = _song_color(song.id, self.theme)
            base = V.vertical_gradient((size, size), lighten(color, 0.25), darken(color, 0.25))
            letter = self.fonts.render((song.title[:1] or "?").upper(), "display", int(size / self.ui.scale * 0.55),
                                       (255, 255, 255), outline=4, shadow=4)
            base.blit(letter, letter.get_rect(center=(size / 2, size / 2)))
        rounded = pygame.Surface((size, size), pygame.SRCALPHA)
        mask = V.rounded_rect((size, size), size * 0.16, (255, 255, 255))
        rounded.blit(base, (0, 0))
        rounded.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
        framed = V.rounded_rect((size + 6, size + 6), size * 0.16 + 3, ink)
        framed.blit(rounded, (3, 3))
        self._covers[key] = framed
        return framed

    def _card(self, song, selected: bool) -> pygame.Surface:
        key = (song.id, selected)
        img = self._cards.get(key)
        if img is not None:
            return img
        theme = self.theme
        w, h = self.list_rect.width - self.s(20), self.s(CARD_H)
        color = theme.c("accent") if selected else theme.c("panel")
        img = V.rounded_rect((w, h), self.s(20), (*color, 235), theme.c("ink"), outline=max(2, self.s(3.5)),
                             shadow=self.s(6), shadow_color=(*darken(theme.c("ink"), 0.3), 140))
        cover = self._cover(song, self.s(60))
        img.blit(cover, (self.s(11), (h - cover.get_height()) // 2))
        tx = self.s(86)
        title = self.fonts.render(song.title, "bold", 25, (255, 255, 255), outline=3, max_width=330)
        artist = self.fonts.render(song.artist or "Unknown artist", "ui", 18,
                                   (255, 240, 248) if selected else theme.c("text_dim"), max_width=330)
        img.blit(title, (tx, self.s(10)))
        img.blit(artist, (tx, self.s(46)))
        info = f"{song.grid.bpm:.0f} BPM\n{format_time(song.duration)}"
        for j, line in enumerate(info.split("\n")):
            t = self.fonts.render(line, "bold", 18, (255, 255, 255), outline=2)
            img.blit(t, t.get_rect(topright=(w - self.s(16), self.s(14) + j * self.s(26))))
        self._cards[key] = img
        return img

    def draw(self, surf) -> None:
        self.app.background.draw(surf)
        w, h = self.size
        theme = self.theme
        self.fonts.draw(surf, "Pick a song", (self.s(40), self.s(20)), "display", 46, (255, 255, 255),
                        outline=5, shadow=6)
        hint = "Enter play  -  E map  -  R re-chart  -  I add  -  Del remove  -  Esc back"
        self.fonts.draw(surf, hint, (w - self.s(36), self.s(40)), "ui", 17, theme.c("text_dim"), anchor="midright",
                        outline=2)
        self._draw_list(surf)
        surf.blit(self.panel_img, self.panel_rect)
        if self.song is None:
            self._draw_empty(surf)
        else:
            self._draw_details(surf)
        for b in self.buttons:
            b.enabled = self.song is not None or b is self.add_btn
            b.draw(surf)

    def _draw_list(self, surf) -> None:
        if not self.songs:
            return
        step = self.s(CARD_H + CARD_GAP)
        center_y = self.list_rect.y + self.list_rect.height // 2 - self.s(CARD_H) // 2
        prev_clip = surf.get_clip()
        surf.set_clip(self.list_rect.inflate(self.s(30), self.s(10)))
        first = max(0, int(self.scroll) - 5)
        for i in range(first, min(len(self.songs), first + 12)):
            y = center_y + (i - self.scroll) * step
            if y < self.list_rect.y - step or y > self.list_rect.bottom:
                continue
            selected = i == self.index
            card = self._card(self.songs[i], selected)
            x = self.list_rect.x + (self.s(20) if selected else 0)
            surf.blit(card, (x, y))
        surf.set_clip(prev_clip)

    def _draw_empty(self, surf) -> None:
        r = self.panel_rect
        self.fonts.draw(surf, "No songs yet!", (r.centerx, r.y + self.s(120)), "display", 44, (255, 255, 255),
                        anchor="center", outline=5, shadow=5)
        lines = ["Paste a YouTube link or pick an audio file:", "press I or click Add.",
                 "Notes are synced to the beat automatically."]
        for i, line in enumerate(lines):
            self.fonts.draw(surf, line, (r.centerx, r.y + self.s(190) + i * self.s(34)), "bold", 22,
                            self.theme.c("text_dim"), anchor="center", outline=2)

    def _draw_details(self, surf) -> None:
        song, theme = self.song, self.theme
        r = self.panel_rect
        cover = self._cover(song, self.s(150))
        surf.blit(cover, (r.x + self.s(22), r.y + self.s(22)))
        tx = r.x + self.s(194)
        self.fonts.draw(surf, song.title, (tx, r.y + self.s(22)), "display", 34, (255, 255, 255), outline=4,
                        shadow=4, max_width=r.width / self.ui.scale - 220)
        self.fonts.draw(surf, song.artist or "Unknown artist", (tx, r.y + self.s(68)), "bold", 22,
                        theme.c("text_dim"), outline=2, max_width=r.width / self.ui.scale - 220)
        tempo = f"{song.grid.bpm:.1f} BPM" + (" (variable)" if song.grid.variable else "")
        meta = f"{tempo}  -  {format_time(song.duration)}"
        self.fonts.draw(surf, meta, (tx, r.y + self.s(104)), "bold", 20, (255, 255, 255), outline=2)
        source = song.source.get("type", "file")
        label = {"url": "from the web", "file": "from a file", "demo": "built-in demo"}.get(source, source)
        self.fonts.draw(surf, label, (tx, r.y + self.s(136)), "ui", 17, theme.c("text_dim"), outline=2)

        # difficulty tabs
        y = r.y + self.s(186)
        x = r.x + self.s(22)
        self.diff_rects = []
        profiles = load_profiles()
        for i, name in enumerate(self.charts):
            prof = profiles.get(name) or get_profile(name)
            color = hex_to_rgb(prof.color) if name in profiles else theme.c("accent2")
            label = prof.label if name in profiles else name.title()
            selected = i == self.diff_index
            txt = self.fonts.render(label, "display", 24 if selected else 21, theme.c("ink") if selected else
                                    (255, 255, 255), outline=0 if selected else 3)
            bw, bh = txt.get_width() + self.s(30), self.s(44 if selected else 40)
            box = V.rounded_rect((bw, bh), bh / 2, color if selected else theme.c("panel_light"), theme.c("ink"),
                                 outline=max(2, self.s(3)))
            box.blit(txt, txt.get_rect(center=(bw / 2, bh / 2)))
            rect = box.get_rect(topleft=(x, y + (0 if selected else self.s(2))))
            surf.blit(box, rect)
            self.diff_rects.append((rect, i))
            x += bw + self.s(8)
        diff = self.difficulty
        stats = self.chart_stats.get(diff or "", {})
        if stats:
            line = (f"{stats.get('rating', 0):.1f} stars  -  {stats.get('notes', 0)} notes  -  "
                    f"{stats.get('holds', 0)} holds  -  {stats.get('lanes', 4)}K")
            self.fonts.draw(surf, line, (r.x + self.s(24), y + self.s(58)), "bold", 20, (255, 255, 255), outline=2)
        best = self.app.scores.best(song.id, diff) if diff else None
        if best:
            grade = best.get("grade", "?")
            text = f"Best: {best.get('score', 0):,}  -  {best.get('accuracy', 0) * 100:.2f}%  -  {grade}"
            if best.get("full_combo"):
                text += "  -  FC"
            self.fonts.draw(surf, text, (r.x + self.s(24), y + self.s(92)), "bold", 20, theme.c("accent2"), outline=2)
        else:
            self.fonts.draw(surf, "Not played yet", (r.x + self.s(24), y + self.s(92)), "bold", 20,
                            theme.c("text_dim"), outline=2)
        keys = self.app.settings.keys_for(stats.get("lanes", 4)) if stats else []
        if keys:
            self.fonts.draw(surf, "Keys: " + "  ".join(k.upper() for k in keys), (r.right - self.s(24), y + self.s(92)),
                            "bold", 20, (255, 255, 255), anchor="topright", outline=2)
        self.fonts.draw(surf, "Modifiers", (r.x + self.s(24), r.y + self.s(312)), "display", 24, (255, 255, 255),
                        outline=3)
        hovered = None
        for p in self.mod_pills:
            p.draw(surf)
            if p.hover:
                hovered = p
        if hovered is not None:
            self.fonts.draw(surf, hovered.tooltip, (r.right - self.s(24), r.y + self.s(318)), "ui", 17,
                            theme.c("text_dim"), anchor="topright", outline=2, max_width=360)
