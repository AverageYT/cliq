"""Window, main loop and scene stack."""

from __future__ import annotations

import gc
import os
import time
from pathlib import Path

import pygame

from . import paths
from .audio import engine
from .audio.engine import AudioEngine
from .display import Display
from .gameplay.modifiers import load_mod_files
from .library.importer import install_demo_song
from .library.scores import ScoreBook
from .library.song import Song, SongLibrary
from .render import vector as V
from .render.background import Background
from .render.text import FontBook
from .render.theme import get_theme
from .render.widgets import UI, Toasts
from .settings import Settings

FADE = 0.16  # seconds per half of a scene transition


class MenuMusic:
    """Loops the highlighted song's preview in menus and tracks its beat."""

    def __init__(self, app: "App"):
        self.app = app
        self.song: Song | None = None
        self.started = 0.0
        self.start_pos = 0.0
        self.active = False

    def play(self, song: Song | None, restart: bool = False) -> None:
        settings = self.app.settings
        if song is None or not settings.song_preview:
            self.stop()
            return
        if not restart and self.active and self.song is not None and song.id == self.song.id:
            return
        self.song = song
        audio = self.app.audio
        if audio.load_music(song.audio_path):
            audio.set_music_volume(settings.music_volume * 0.75)
            audio.play_music(start=song.preview, fade_ms=700)
        self.start_pos = song.preview
        self.started = time.perf_counter()
        self.active = True

    def stop(self, fade_ms: int = 300) -> None:
        if self.active:
            if fade_ms > 0:
                self.app.audio.fadeout_music(fade_ms)
            else:
                self.app.audio.stop_music()
        self.active = False

    def update(self) -> None:
        if not self.active or self.song is None:
            return
        elapsed = time.perf_counter() - self.started
        if elapsed > 24.0:
            self.app.audio.fadeout_music(900)
        if elapsed > 25.2:
            self.play(self.song, restart=True)

    @property
    def beat(self) -> float | None:
        if not self.active or self.song is None:
            return None
        t = self.start_pos + time.perf_counter() - self.started
        return float(self.song.grid.beat_at(t))


class App:
    def __init__(self, settings: Settings | None = None):
        paths.ensure_dirs()
        self.settings = settings or Settings.load()
        engine.pre_init(self.settings.audio_buffer)
        pygame.init()
        self.screen = self._open_window()
        self.size = self.display.size
        self.scale = self.size[1] / 720.0
        self.theme = get_theme()
        self.fonts = FontBook(self.theme, self.scale)
        self.audio = AudioEngine(self.settings.audio_buffer)
        self.audio.init()
        self.audio.set_music_volume(self.settings.music_volume)
        self.ui = UI(self.fonts, self.theme, self.scale, sound=self.sfx)
        self.toasts = Toasts(self.ui)
        self.library = SongLibrary()
        self.library.scan()
        self.scores = ScoreBook()
        self.background = Background(self.size, self.theme, self.scale, seed=7)
        self.menu_music = MenuMusic(self)
        self.clock = pygame.time.Clock()
        self.stack: list = []
        self.running = True
        self.fps = 0.0
        self._pending = None
        self._fade = 0.0
        self._fading_in = False
        self._fade_surface = pygame.Surface(self.size)
        self._fade_surface.fill(self.theme.c("ink"))
        self.demo_job: "_DemoInstall | None" = None
        self.editor_clipboard: list = []        # copied notes, shared by every chart in the editor

        errors = load_mod_files(paths.MODS_DIR)
        if paths.ROOT / "mods" != paths.MODS_DIR:
            errors += load_mod_files(paths.ROOT / "mods")
        for err in errors:
            print(f"[cliq] mod failed to load: {err}")
        if errors:
            self.toasts.show(f"{len(errors)} mod(s) failed to load - see console", self.theme.c("bad"))
        if not self.library.songs:
            self.demo_job = _DemoInstall(self.library, self.settings.lane_count)

    # ------------------------------------------------------------ window
    def _open_window(self) -> pygame.Surface:
        self.display = Display(self.settings)
        screen = self.display.open()
        try:
            self.display.set_icon(V.glossy_shape(64, V.arrow_points(), self.theme_color("up"), (27, 18, 54)))
        except pygame.error:
            pass
        return screen

    @staticmethod
    def theme_color(direction: str):
        return get_theme().lane_colors.get(direction, (255, 255, 255))

    def toggle_fullscreen(self) -> None:
        self.settings.fullscreen = not self.settings.fullscreen
        self.display.toggle_fullscreen(self.settings.fullscreen)
        self.settings.save()

    # ------------------------------------------------------------ audio helpers
    def sfx(self, name: str, volume: float = 1.0) -> None:
        self.audio.play_sfx(name, volume * self.settings.sfx_volume)

    # ------------------------------------------------------------ scenes
    @property
    def scene(self):
        return self.stack[-1] if self.stack else None

    def push(self, scene, instant: bool = False) -> None:
        self._request(("push", scene, {}), instant)

    def replace(self, scene, instant: bool = False) -> None:
        self._request(("replace", scene, {}), instant)

    def pop(self, instant: bool = False, **result) -> None:
        self._request(("pop", None, result), instant)

    def cut_in(self, scene) -> None:
        """Push ``scene`` now and fade it in from black (the caller already animated the way out)."""
        self._apply(("push", scene, {}))
        self._pending = None
        self._fading_in = True
        self._fade = 0.0

    def _request(self, action, instant: bool) -> None:
        if instant or not self.stack:
            self._apply(action)
        else:
            self._pending = action
            self._fade = 0.0
            self._fading_in = False

    def _apply(self, action) -> None:
        kind, scene, result = action
        if kind in ("pop", "replace") and self.stack:
            self.stack.pop().leave()
        elif kind == "push" and self.stack:
            self.stack[-1].pause()
        if scene is not None:
            if not scene.menu_music:
                # Stop the preview *before* the scene starts its own music, so the
                # preview's fade-out can never touch the new track.
                self.menu_music.stop(fade_ms=0)
            self.stack.append(scene)
            scene.enter()
        elif self.stack:
            self.stack[-1].resume(**result)
        if not self.stack:
            self.running = False
            return
        top = self.stack[-1]
        if top.key_repeat:
            pygame.key.set_repeat(*top.key_repeat)
        else:
            pygame.key.set_repeat()
        if top.text_input:
            pygame.key.start_text_input()
        else:
            pygame.key.stop_text_input()

    def quit(self) -> None:
        self.running = False

    # ------------------------------------------------------------ loop
    def run(self, first_scene) -> None:
        self._apply(("push", first_scene, {}))
        try:
            while self.running:
                cap = 0 if self.settings.vsync else int(self.settings.fps_cap)
                dt = min(0.1, self.clock.tick(cap) / 1000.0)
                self.fps = self.clock.get_fps()
                self._frame(dt)
        finally:
            gc.enable()
            self.settings.save()
            pygame.quit()

    def _frame(self, dt: float) -> None:
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                self.running = False
            elif e.type == pygame.KEYDOWN and e.key == pygame.K_F11:
                self.toggle_fullscreen()
            elif e.type == pygame.KEYDOWN and e.key == pygame.K_F12:
                self.screenshot()
            elif self._pending is None and self.scene is not None:
                self.scene.handle_event(self.display.map_event(e))
        if self.demo_job is not None and self.demo_job.done:
            if self.demo_job.song:
                self.toasts.show("Demo song ready - have fun!", self.theme.c("good"))
                self.library.scan()
                for s in self.stack:
                    getattr(s, "on_library_changed", lambda: None)()
            elif self.demo_job.error:
                self.toasts.show(f"Couldn't make the demo song: {self.demo_job.error}", self.theme.c("bad"), 6)
            self.demo_job = None
        scene = self.scene
        if scene is None:
            self.running = False
            return
        if scene.menu_music:
            self.menu_music.update()
            self.background.update(dt, self.menu_music.beat)
        scene.update(dt)
        self.toasts.update(dt)
        scene.draw(self.screen)
        self.toasts.draw(self.screen)
        if self.settings.show_fps:
            self.fonts.draw(self.screen, f"{self.fps:.0f} fps", (self.ui.s(10), self.size[1] - self.ui.s(8)),
                            "bold", 16, (255, 255, 255), anchor="bottomleft", outline=2)
        self._transition(dt)
        self.display.present()

    def _transition(self, dt: float) -> None:
        if self._pending is None and not self._fading_in:
            return
        self._fade += dt / FADE
        if self._pending is not None and self._fade >= 1.0:
            self._apply(self._pending)
            self._pending = None
            self._fading_in = True
            self._fade = 0.0
            alpha = 255
        elif self._pending is not None:
            alpha = int(255 * min(1.0, self._fade))
        else:
            alpha = int(255 * max(0.0, 1.0 - self._fade))
            if self._fade >= 1.0:
                self._fading_in = False
        self._fade_surface.set_alpha(alpha)
        self.screen.blit(self._fade_surface, (0, 0))

    def screenshot(self) -> None:
        folder = paths.USER_DIR / "screenshots"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / time.strftime("cliq-%Y%m%d-%H%M%S.png")
        pygame.image.save(self.screen, str(path))
        self.toasts.show(f"Screenshot saved: {path.name}")


class _DemoInstall:
    """Builds the demo song on first launch without blocking the menu."""

    def __init__(self, library: SongLibrary, lanes: int):
        import threading

        self.song = None
        self.error = None
        self.done = False
        self._lib = library
        self._lanes = lanes
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        try:
            self.song = install_demo_song(SongLibrary(self._lib.root), lanes=self._lanes)
        except Exception as exc:  # never crash the menu over the demo
            self.error = str(exc)
        self.done = True


def open_path(path: Path) -> None:
    """Reveal a folder in the OS file browser (used by 'open songs folder')."""
    import subprocess
    import sys

    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        pass

