"""Title screen: bouncing logo and the main menu."""

from __future__ import annotations

import math
import random

import pygame

from ..render.fx import ease_out_back, pulse
from ..render.widgets import Button, ButtonGroup
from .base import Scene

LOGO = "CLIQ"


class TitleScene(Scene):
    def __init__(self, app):
        super().__init__(app)
        w, h = self.size
        bw, bh, gap = self.s(330), self.s(60), self.s(14)
        x = w // 2 - bw // 2
        y0 = int(h * 0.415)
        theme = self.theme
        items = [
            ("Play", self.play, theme.c("accent")),
            ("Playlists", self.playlists, theme.c("accent4")),
            ("Add a song", self.import_song, theme.c("accent3")),
            ("Settings", self.settings, theme.c("accent5")),
            ("Quit", self.app.quit, theme.c("panel_light")),
        ]
        self.buttons = [Button(self.ui, (x, y0 + i * (bh + gap), bw, bh), label, cb, color=color, size=32)
                        for i, (label, cb, color) in enumerate(items)]
        self.group = ButtonGroup(self.buttons)
        self.t = 0.0

    def enter(self) -> None:
        self._start_music()

    def resume(self, **result) -> None:
        self._start_music()

    def on_library_changed(self) -> None:
        self._start_music()

    def _start_music(self) -> None:
        songs = self.app.library.songs
        if songs and not self.app.menu_music.active:
            last = self.app.library.get(self.app.settings.last_song or "") if self.app.settings.last_song else None
            self.app.menu_music.play(last or random.choice(songs))

    # ------------------------------------------------------------ actions
    def play(self) -> None:
        from .song_select import SongSelectScene

        self.app.push(SongSelectScene(self.app))

    def playlists(self) -> None:
        from .playlists import PlaylistsScene

        self.app.push(PlaylistsScene(self.app))

    def import_song(self) -> None:
        from .import_song import ImportScene

        self.app.push(ImportScene(self.app))

    def settings(self) -> None:
        from .settings_menu import SettingsScene

        self.app.push(SettingsScene(self.app))

    # ------------------------------------------------------------ frame
    def handle_event(self, e) -> None:
        if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
            self.app.quit()
            return
        if e.type == pygame.DROPFILE:
            from .import_song import ImportScene

            scene = ImportScene(self.app)
            self.app.push(scene)
            scene.start(e.file)
            return
        self.group.handle_event(e)

    def update(self, dt: float) -> None:
        self.t += dt
        self.group.update(dt)

    def draw(self, surf) -> None:
        self.app.background.draw(surf)
        w, h = self.size
        beat = self.app.menu_music.beat
        # logo letters hop one after another on the beat
        theme = self.theme
        colors = [theme.lane_colors["left"], theme.lane_colors["down"], theme.lane_colors["up"],
                  theme.lane_colors["right"]]
        intro = ease_out_back(min(1.0, self.t * 1.6))
        letters = [self.fonts.render(ch, "display", 150, c, outline=9, shadow=12) for ch, c in zip(LOGO, colors)]
        total = sum(img.get_width() for img in letters) - self.s(12) * (len(letters) - 1)
        x = w // 2 - total // 2
        base_y = int(h * 0.21)
        for i, img in enumerate(letters):
            hop = 0.0
            if beat is not None:
                phase = (beat - i * 0.12) % 1.0
                hop = pulse(phase, 7.0) * self.s(14)
            wobble = math.sin(self.t * 2.2 + i * 0.9) * self.s(3)
            y = base_y - hop + wobble + (1 - intro) * self.s(160)
            surf.blit(img, (x, y - img.get_height() // 2))
            x += img.get_width() - self.s(12)
        self.fonts.draw(surf, "rhythm game  -  phase one", (w // 2, base_y + self.s(88)), "bold", 24,
                        (255, 255, 255), anchor="center", outline=3)
        self.group.draw(surf)
        hint = "Up/Down + Enter, or click  -  drop an audio file anywhere to import it"
        if self.app.demo_job is not None:
            dots = "." * (int(self.t * 3) % 4)
            hint = f"Preparing the demo song{dots}"
        self.fonts.draw(surf, hint, (w // 2, h - self.s(22)), "ui", 18, theme.c("text_dim"), anchor="center",
                        outline=2)
        song = self.app.menu_music.song if self.app.menu_music.active else None
        if song:
            self.fonts.draw(surf, f"Now playing: {song.title}", (w - self.s(18), self.s(16)), "bold", 18,
                            (255, 255, 255), anchor="topright", outline=2, max_width=600)
