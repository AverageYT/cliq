"""Settings: gameplay, key bindings, audio and display."""

from __future__ import annotations

import pygame

from ..render import vector as V
from ..render.widgets import panel
from ..settings import DEFAULT_KEYBINDS, SETTINGS_MENU, SettingSpec
from ..util import darken, lighten
from .base import Scene

KEY_COUNTS = (4, 5, 6, 7)


class SettingsScene(Scene):
    def __init__(self, app):
        super().__init__(app)
        self.sections: list[str] = []
        for spec in SETTINGS_MENU:
            if spec.section not in self.sections:
                self.sections.append(spec.section)
        self.tab = 0
        self.row = 0
        self.key_col = 0
        self.rebinding: tuple[int, int] | None = None
        w, h = self.size
        self.panel_rect = pygame.Rect(0, 0, self.s(940), self.s(496))
        self.panel_rect.center = (w // 2, self.s(392))
        self.panel_img = panel(self.panel_rect.size, self.ui)
        self.row_h = self.s(48)
        self.visible_rows = (self.panel_rect.height - self.s(36)) // self.row_h
        self.first_row = 0
        self.tab_rects: list[pygame.Rect] = []
        self.row_rects: list[tuple[pygame.Rect, int]] = []

    # ------------------------------------------------------------ rows
    def rows(self) -> list:
        section = self.sections[self.tab]
        if section == "Controls":
            return [("keys", n) for n in KEY_COUNTS] + [("reset_keys", None)]
        return [spec for spec in SETTINGS_MENU if spec.section == section]

    def _value_text(self, spec: SettingSpec) -> str:
        if spec.kind == "action":
            return ""
        value = self.app.settings.get(spec.key)
        if spec.kind == "toggle":
            return "On" if value else "Off"
        if spec.kind == "choice":
            return str(value).title() if isinstance(value, str) else str(value)
        if spec.kind == "number":
            try:
                return spec.fmt.format(value)
            except (ValueError, TypeError):
                return str(value)
        return ""

    def change(self, spec: SettingSpec, direction: int) -> None:
        if spec.kind == "action":
            self.action(spec.key)
            return
        s = self.app.settings
        value = s.get(spec.key)
        if spec.kind == "toggle":
            s.set(spec.key, not value)
        elif spec.kind == "choice":
            choices = list(spec.choices)
            i = choices.index(value) if value in choices else 0
            s.set(spec.key, choices[(i + direction) % len(choices)])
        elif spec.kind == "number":
            mult = 10 if pygame.key.get_mods() & pygame.KMOD_SHIFT else 1
            new = max(spec.lo, min(spec.hi, round(float(value) + direction * spec.step * mult, 4)))
            s.set(spec.key, int(new) if isinstance(value, int) and not isinstance(value, bool) else new)
        self.app.sfx("ui_move")
        self.apply_side_effects(spec.key)
        s.save()

    def apply_side_effects(self, key: str) -> None:
        app, s = self.app, self.app.settings
        if key == "fullscreen":
            s.fullscreen = not s.fullscreen  # toggle_fullscreen flips it back and applies
            app.toggle_fullscreen()
        elif key in ("vsync", "render_quality"):
            app.toasts.show("Restart the game to apply this")
        elif key == "audio_buffer":
            song = app.menu_music.song
            app.audio.reinit(s.audio_buffer)
            app.menu_music.active = False
            app.menu_music.play(song)
            app.toasts.show(f"Audio buffer {s.audio_buffer} samples ({app.audio.latency_ms:.1f} ms)")
        elif key == "music_volume":
            app.audio.set_music_volume(s.music_volume * 0.75)
        elif key == "song_preview":
            if s.song_preview:
                app.menu_music.play(app.library.songs[0] if app.library.songs else None)
            else:
                app.menu_music.stop()
        elif key == "sfx_volume":
            app.sfx("ui_select")
        elif key == "hitsound_volume":
            app.audio.play_sfx("hit", s.hitsound_volume * s.sfx_volume)

    def action(self, key: str) -> None:
        if key == "calibrate":
            from .calibration import CalibrationScene

            self.app.push(CalibrationScene(self.app))

    # ------------------------------------------------------------ events
    def handle_event(self, e) -> None:
        if self.rebinding is not None:
            if e.type == pygame.KEYDOWN:
                lanes, lane = self.rebinding
                self.rebinding = None
                if e.key == pygame.K_ESCAPE:
                    return
                self.app.settings.set_key(lanes, lane, pygame.key.name(e.key))
                self.app.settings.save()
                self.app.sfx("ui_select")
                if lane + 1 < lanes:  # flow straight into the next key
                    self.key_col = lane + 1
                    self.rebinding = (lanes, lane + 1)
            return
        rows = self.rows()
        if e.type == pygame.KEYDOWN:
            k = e.key
            if k == pygame.K_ESCAPE:
                self.app.sfx("ui_back")
                self.app.pop()
            elif k == pygame.K_TAB:
                self.switch_tab(-1 if e.mod & pygame.KMOD_SHIFT else 1)
            elif k == pygame.K_UP:
                self.row = (self.row - 1) % len(rows)
                self.app.sfx("ui_move")
            elif k == pygame.K_DOWN:
                self.row = (self.row + 1) % len(rows)
                self.app.sfx("ui_move")
            elif k in (pygame.K_LEFT, pygame.K_RIGHT):
                self._horizontal(rows[self.row], -1 if k == pygame.K_LEFT else 1)
            elif k in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                self._activate(rows[self.row])
        elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            for i, rect in enumerate(self.tab_rects):
                if rect.collidepoint(e.pos):
                    self.tab, self.row, self.first_row = i, 0, 0
                    self.app.sfx("ui_move")
                    return
            for rect, i in self.row_rects:
                if rect.collidepoint(e.pos):
                    self.row = i
                    row = rows[i]
                    if isinstance(row, tuple) and row[0] == "keys":
                        n = row[1]
                        rel = e.pos[0] - (self.panel_rect.right - self.s(40) - n * self.s(66))
                        if rel >= 0:
                            self.key_col = min(n - 1, rel // self.s(66))
                            self._activate(row)
                    elif isinstance(row, SettingSpec) and row.kind in ("number", "choice"):
                        self.change(row, -1 if e.pos[0] < rect.right - self.s(150) else 1)
                    else:
                        self._activate(row)
                    return
        elif e.type == pygame.MOUSEWHEEL:
            self.row = (self.row - e.y) % len(rows)

    def switch_tab(self, delta: int) -> None:
        self.tab = (self.tab + delta) % len(self.sections)
        self.row = self.first_row = 0
        self.app.sfx("ui_move")

    def _horizontal(self, row, direction: int) -> None:
        if isinstance(row, tuple):
            if row[0] == "keys":
                self.key_col = max(0, min(row[1] - 1, self.key_col + direction))
                self.app.sfx("ui_move")
            return
        self.change(row, direction)

    def _activate(self, row) -> None:
        if isinstance(row, tuple):
            if row[0] == "keys":
                self.rebinding = (row[1], min(self.key_col, row[1] - 1))
                self.app.sfx("ui_select")
            elif row[0] == "reset_keys":
                self.app.settings.keybinds = {k: list(v) for k, v in DEFAULT_KEYBINDS.items()}
                self.app.settings.save()
                self.app.toasts.show("Key bindings reset")
            return
        if row.kind in ("toggle", "action"):
            self.change(row, 1)
        elif row.kind in ("choice", "number"):
            self.change(row, 1)

    # ------------------------------------------------------------ drawing
    def draw(self, surf) -> None:
        self.app.background.draw(surf)
        theme = self.theme
        self.title(surf, "Settings", 42, 48)
        r = self.panel_rect
        # tabs
        x = r.x
        self.tab_rects = []
        for i, name in enumerate(self.sections):
            active = i == self.tab
            img = self.fonts.render(name, "display", 24, theme.c("ink") if active else (255, 255, 255),
                                    outline=0 if active else 3)
            bw, bh = img.get_width() + self.s(36), self.s(46)
            box = V.rounded_rect((bw, bh), bh / 2, theme.c("accent2") if active else theme.c("panel_light"),
                                 theme.c("ink"), outline=max(2, self.s(3)))
            box.blit(img, img.get_rect(center=(bw / 2, bh / 2)))
            rect = box.get_rect(bottomleft=(x, r.y - self.s(12)))
            surf.blit(box, rect)
            self.tab_rects.append(rect)
            x += bw + self.s(10)
        self.fonts.draw(surf, "Tab: next page", (r.right, r.y - self.s(26)), "ui", 17, theme.c("text_dim"),
                        anchor="midright", outline=2)
        surf.blit(self.panel_img, r)
        rows = self.rows()
        self.row = min(self.row, len(rows) - 1)
        # keep the focused row inside the scrolling window
        if self.row < self.first_row:
            self.first_row = self.row
        elif self.row >= self.first_row + self.visible_rows:
            self.first_row = self.row - self.visible_rows + 1
        self.first_row = max(0, min(self.first_row, max(0, len(rows) - self.visible_rows)))
        y = r.y + self.s(18)
        rh = self.row_h
        self.row_rects = []
        help_text = ""
        shown = range(self.first_row, min(len(rows), self.first_row + self.visible_rows))
        for i in shown:
            row = rows[i]
            rect = pygame.Rect(r.x + self.s(16), y, r.width - self.s(32), rh - self.s(6))
            self.row_rects.append((rect, i))
            focused = i == self.row
            if focused:
                pygame.draw.rect(surf, darken(theme.c("accent"), 0.1), rect, border_radius=self.s(14))
                pygame.draw.rect(surf, theme.c("ink"), rect, max(2, self.s(3)), border_radius=self.s(14))
            if isinstance(row, tuple):
                self._draw_key_row(surf, row, rect, focused)
                if focused:
                    help_text = ("Enter: rebind the highlighted key (Esc cancels). Arrow keys also work for 4K."
                                 if row[0] == "keys" else "Restore D F K L and the other defaults.")
            else:
                self.fonts.draw(surf, row.label, (rect.x + self.s(24), rect.centery), "bold", 23, (255, 255, 255),
                                anchor="midleft", outline=2)
                value = self._value_text(row)
                if row.kind in ("choice", "number"):
                    value = f"<  {value}  >"
                elif row.kind == "action":
                    value = "Enter"
                color = theme.c("accent2") if row.kind != "toggle" else (
                    theme.c("good") if self.app.settings.get(row.key) else theme.c("text_dim"))
                self.fonts.draw(surf, value, (rect.right - self.s(24), rect.centery), "display", 24, color,
                                anchor="midright", outline=3)
                if focused:
                    help_text = row.help
            y += rh
        for more, tip_y, sign in ((self.first_row > 0, r.y + self.s(8), -1),
                                  (self.first_row + self.visible_rows < len(rows), r.bottom - self.s(8), 1)):
            if more:
                cx = r.centerx
                d = self.s(9)
                pygame.draw.polygon(surf, theme.c("accent2"), [(cx - d, tip_y - sign * d), (cx + d, tip_y - sign * d),
                                                               (cx, tip_y)])
        if help_text:
            self.fonts.draw(surf, help_text, (self.size[0] // 2, r.bottom + self.s(30)), "ui", 19, (255, 255, 255),
                            anchor="center", outline=2, max_width=1100)
        latency = f"Audio buffer latency: {self.app.audio.latency_ms:.1f} ms  -  Esc back"
        self.fonts.draw(surf, latency, (self.size[0] // 2, self.size[1] - self.s(20)), "ui", 17, theme.c("text_dim"),
                        anchor="center", outline=2)
        if self.rebinding is not None:
            lanes, lane = self.rebinding
            self.fonts.draw(surf, f"Press a key for lane {lane + 1} of {lanes}...",
                            (self.size[0] // 2, r.y + self.s(330)), "display", 34, theme.c("accent2"),
                            anchor="center", outline=4, shadow=5)

    def _draw_key_row(self, surf, row, rect, focused) -> None:
        theme = self.theme
        if row[0] == "reset_keys":
            self.fonts.draw(surf, "Reset key bindings", (rect.x + self.s(24), rect.centery), "bold", 23,
                            (255, 255, 255), anchor="midleft", outline=2)
            return
        n = row[1]
        self.fonts.draw(surf, f"{n} keys", (rect.x + self.s(24), rect.centery), "bold", 23, (255, 255, 255),
                        anchor="midleft", outline=2)
        keys = self.app.settings.keys_for(n)
        x = rect.right - self.s(24) - n * self.s(66) + self.s(6)
        for lane, name in enumerate(keys):
            color = theme.lane_color(n, lane)
            selected = focused and lane == self.key_col
            waiting = self.rebinding == (n, lane)
            box = pygame.Rect(x + lane * self.s(66), rect.y + self.s(4), self.s(58), rect.height - self.s(8))
            fill = lighten(color, 0.25) if (selected or waiting) else darken(color, 0.25)
            pygame.draw.rect(surf, theme.c("ink"), box.inflate(self.s(4), self.s(4)), border_radius=self.s(10))
            pygame.draw.rect(surf, fill, box, border_radius=self.s(9))
            label = "..." if waiting else (name.upper() if len(name) <= 3 else name[:5].title())
            self.fonts.draw(surf, label, box.center, "display", 20 if len(label) <= 3 else 15, (255, 255, 255),
                            anchor="center", outline=3)
