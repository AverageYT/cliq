"""The game window.

The game draws into one off-screen surface at a fixed *render resolution*
(16:9; the UI scales with its height). How that surface reaches the screen:

* **renderer backend** (pygame-ce): a resizable, high-DPI aware window. The
  frame is uploaded to a GPU texture and scaled smoothly to the window. On
  Retina/4K screens this renders at real pixel density instead of letting the
  OS stretch a small window (which is what made things blurry).
* **classic backend** (old pygame, or ``CLIQ_DISPLAY=classic``): pygame's
  ``SCALED`` mode.

``settings.render_quality`` picks the render height: "auto" (1080p on high-DPI
or big screens, else 720p), "720p", "900p", "1080p", "1440p" or "native".
Higher looks sharper but costs more CPU per frame.
"""

from __future__ import annotations

import os

import pygame

try:  # pygame-ce GPU renderer
    from pygame._sdl2 import video as _video
except Exception:  # pragma: no cover - classic pygame without _sdl2
    _video = None

QUALITY_HEIGHTS = {"720p": 720, "900p": 900, "1080p": 1080, "1440p": 1440, "2160p": 2160}
RENDER_QUALITIES = ("auto", "720p", "900p", "1080p", "1440p", "native")


def _even(v: float) -> int:
    return max(2, int(round(v / 2)) * 2)


class Display:
    def __init__(self, settings):
        self.settings = settings
        self.use_renderer = (os.environ.get("CLIQ_DISPLAY", "").lower() != "classic"
                             and _video is not None and hasattr(pygame, "Window"))
        self.window = None
        self.renderer = None
        self.texture = None
        self.surface: pygame.Surface | None = None
        self.size = (1280, 720)
        self.pixel_ratio = 1.0
        self._dst = pygame.Rect(0, 0, 1280, 720)

    # ------------------------------------------------------------ sizing
    @staticmethod
    def _desktop() -> tuple[int, int]:
        try:
            sizes = pygame.display.get_desktop_sizes()
            if sizes:
                return sizes[0]
        except pygame.error:
            pass
        return 1920, 1080

    def _render_height(self, physical_h: float) -> int:
        quality = getattr(self.settings, "render_quality", "auto")
        if quality in QUALITY_HEIGHTS:
            return QUALITY_HEIGHTS[quality]
        if quality == "native":
            return _even(max(720, physical_h))
        return 1080 if physical_h >= 1080 else 720

    # ------------------------------------------------------------ open
    def open(self) -> pygame.Surface:
        if self.use_renderer:
            try:
                return self._open_renderer()
            except (pygame.error, TypeError, AttributeError) as exc:
                print(f"[cliq] GPU window unavailable ({exc}); using classic window")
                self.use_renderer = False
        return self._open_classic()

    def _open_renderer(self) -> pygame.Surface:
        os.environ.setdefault("SDL_RENDER_SCALE_QUALITY", "linear")   # smooth texture scaling
        dw, dh = self._desktop()
        wh = int(min(dh * 0.82, dw * 0.82 * 9 / 16))
        ww = int(wh * 16 / 9)
        self.window = pygame.Window("Cliq", (ww, wh), resizable=True, allow_high_dpi=True)
        self.window.minimum_size = (480, 270)
        self.renderer = _video.Renderer(self.window, vsync=bool(self.settings.vsync))
        vp = self.renderer.get_viewport()
        self.pixel_ratio = max(1.0, vp.width / max(1, self.window.size[0]))
        rh = self._render_height(dh * self.pixel_ratio)
        self.size = (_even(rh * 16 / 9), rh)
        self.surface = pygame.Surface(self.size)
        self.texture = _video.Texture(self.renderer, self.size, streaming=True)
        if self.settings.fullscreen:
            self.window.set_fullscreen(desktop=True)
        return self.surface

    def _open_classic(self) -> pygame.Surface:
        quality = getattr(self.settings, "render_quality", "auto")
        h = QUALITY_HEIGHTS.get(quality, int(self.settings.resolution[1]) if quality == "auto" else 720)
        self.size = (_even(h * 16 / 9), h)
        flags = pygame.SCALED | (pygame.FULLSCREEN if self.settings.fullscreen else 0)
        pygame.display.set_caption("Cliq")
        try:
            self.surface = pygame.display.set_mode(self.size, flags, vsync=1 if self.settings.vsync else 0)
        except pygame.error:
            self.surface = pygame.display.set_mode(self.size, flags)
        return self.surface

    def set_icon(self, icon: pygame.Surface) -> None:
        try:
            if self.window is not None:
                self.window.set_icon(icon)
            else:
                pygame.display.set_icon(icon)
        except pygame.error:
            pass

    # ------------------------------------------------------------ runtime
    def toggle_fullscreen(self, on: bool) -> None:
        if self.window is not None:
            if on:
                self.window.set_fullscreen(desktop=True)
            else:
                self.window.set_windowed()
        else:
            try:
                pygame.display.toggle_fullscreen()
            except pygame.error:
                self._open_classic()

    def present(self) -> None:
        if self.renderer is None:
            pygame.display.flip()
            return
        self.texture.update(self.surface)
        vp = self.renderer.get_viewport()
        scale = min(vp.width / self.size[0], vp.height / self.size[1])
        w, h = int(self.size[0] * scale), int(self.size[1] * scale)
        self._dst = pygame.Rect((vp.width - w) // 2, (vp.height - h) // 2, w, h)
        self.renderer.draw_color = (0, 0, 0, 255)
        self.renderer.clear()
        self.texture.draw(dstrect=self._dst)
        self.renderer.present()

    def to_render(self, pos) -> tuple[int, int]:
        """Window (point) coordinates -> render-surface coordinates."""
        if self.renderer is None:
            return pos
        ratio = self.renderer.get_viewport().width / max(1, self.window.size[0])
        x = (pos[0] * ratio - self._dst.x) * self.size[0] / max(1, self._dst.width)
        y = (pos[1] * ratio - self._dst.y) * self.size[1] / max(1, self._dst.height)
        return int(x), int(y)

    def map_event(self, e: pygame.event.Event) -> pygame.event.Event:
        if self.renderer is None or e.type not in (pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
            return e
        data = dict(e.dict)
        data["pos"] = self.to_render(e.pos)
        if "rel" in data:
            k = self.size[0] / max(1, self._dst.width) * self.renderer.get_viewport().width / max(1, self.window.size[0])
            data["rel"] = (int(e.rel[0] * k), int(e.rel[1] * k))
        return pygame.event.Event(e.type, data)

    def mouse_pos(self) -> tuple[int, int]:
        return self.to_render(pygame.mouse.get_pos())


def prepare(surf: pygame.Surface, alpha: bool = False) -> pygame.Surface:
    """``convert()`` when a classic display exists (faster blits), otherwise unchanged."""
    if pygame.display.get_init() and pygame.display.get_surface() is not None:
        try:
            return surf.convert_alpha() if alpha else surf.convert()
        except pygame.error:
            return surf
    return surf
