"""Fonts and cartoon-style text (thick outline + drop shadow), with caching.

Roles map to the font files in ``data/theme.json``: ``display`` (chunky
headings, judgements, combo), ``ui`` (body text), ``bold``. Strings with
characters the bundled fonts lack (e.g. Japanese song titles) automatically
fall back to a system font that has them.
"""

from __future__ import annotations

from collections import OrderedDict

import pygame

from .. import paths
from .theme import Theme, get_theme

FALLBACK_SYSTEM_FONTS = ("notosanscjkjp,notosanscjk,notosans,meiryo,yugothic,msgothic,applesdgothicneo,"
                         "malgungothic,microsoftyahei,simhei,arialunicodems,segoeui,arial,dejavusans")


class FontBook:
    def __init__(self, theme: Theme | None = None, scale: float = 1.0):
        self.theme = theme or get_theme()
        self.scale = scale
        self._fonts: dict[tuple, pygame.font.Font] = {}
        self._cache: OrderedDict = OrderedDict()
        self._coverage: dict[tuple[str, str], bool] = {}
        self._ft: dict[str, object] = {}

    def set_scale(self, scale: float) -> None:
        if abs(scale - self.scale) > 1e-6:
            self.scale = scale
            self._fonts.clear()
            self._cache.clear()

    def _path(self, role: str):
        name = self.theme.fonts.get(role) or self.theme.fonts.get("ui")
        path = paths.FONTS_DIR / name if name else None
        return path if path and path.exists() else None

    def font(self, role: str, size: int, fallback: bool = False) -> pygame.font.Font:
        px = max(6, int(round(size * self.scale)))
        key = (role, px, fallback)
        font = self._fonts.get(key)
        if font is None:
            path = None if fallback else self._path(role)
            if path:
                font = pygame.font.Font(str(path), px)
            else:
                try:
                    font = pygame.font.SysFont(FALLBACK_SYSTEM_FONTS, px, bold=role != "ui")
                except Exception:
                    font = pygame.font.Font(None, px)
            self._fonts[key] = font
        return font

    def covers(self, role: str, text: str) -> bool:
        """True if the bundled font for ``role`` has glyphs for every character."""
        path = self._path(role)
        if path is None:
            return True
        missing = [ch for ch in set(text) if ch.strip() and ord(ch) > 0x24F]
        if not missing:
            return True
        try:
            import pygame.freetype as ft

            if not ft.get_init():
                ft.init()
            face = self._ft.get(role)
            if face is None:
                face = self._ft[role] = ft.Font(str(path), 16)
            for ch in missing:
                key = (role, ch)
                if key not in self._coverage:
                    self._coverage[key] = face.get_metrics(ch)[0] is not None
                if not self._coverage[key]:
                    return False
        except Exception:
            return True
        return True

    # ------------------------------------------------------------ rendering
    def render(self, text: str, role: str = "ui", size: int = 24, color=(255, 255, 255),
               outline: int = 0, outline_color=None, shadow: int = 0, shadow_color=None,
               max_width: int | None = None) -> pygame.Surface:
        key = (text, role, size, tuple(color), outline, tuple(outline_color or ()), shadow,
               tuple(shadow_color or ()), max_width, self.scale)
        surf = self._cache.get(key)
        if surf is not None:
            self._cache.move_to_end(key)
            return surf
        surf = self._render(text, role, size, color, outline, outline_color, shadow, shadow_color, max_width)
        self._cache[key] = surf
        if len(self._cache) > 600:
            self._cache.popitem(last=False)
        return surf

    def _render(self, text, role, size, color, outline, outline_color, shadow, shadow_color, max_width):
        font = self.font(role, size, fallback=not self.covers(role, text))
        if max_width:
            limit = int(max_width * self.scale) if max_width > 0 else 0
            if limit and font.size(text)[0] > limit:
                while text and font.size(text + "...")[0] > limit:
                    text = text[:-1]
                text = text.rstrip() + "..."
        o = int(round(outline * self.scale)) if outline else 0
        sh = int(round(shadow * self.scale)) if shadow else 0
        ink = outline_color or self.theme.c("ink")
        fill = font.render(text or " ", True, color)
        if not o and not sh:
            return fill
        if o and hasattr(font, "outline"):
            font.outline = o
            stroke = font.render(text or " ", True, ink)
            font.outline = 0
        elif o:
            stroke = pygame.Surface((fill.get_width() + 2 * o, fill.get_height() + 2 * o), pygame.SRCALPHA)
            ink_text = font.render(text or " ", True, ink)
            for dx in range(-o, o + 1):
                for dy in range(-o, o + 1):
                    if dx * dx + dy * dy <= o * o:
                        stroke.blit(ink_text, (dx + o, dy + o))
        else:
            stroke = None
        w = (stroke.get_width() if stroke else fill.get_width())
        h = (stroke.get_height() if stroke else fill.get_height())
        out = pygame.Surface((w, h + sh), pygame.SRCALPHA)
        base = stroke if stroke else fill
        if sh:
            shadow_surf = base.copy()
            shadow_surf.fill((*(shadow_color or ink), 255), special_flags=pygame.BLEND_RGBA_MIN)
            out.blit(shadow_surf, (0, sh))
        if stroke:
            out.blit(stroke, (0, 0))
            out.blit(fill, ((w - fill.get_width()) // 2, (h - fill.get_height()) // 2))
        else:
            out.blit(fill, (0, 0))
        return out

    def draw(self, surf: pygame.Surface, text: str, pos, role: str = "ui", size: int = 24, color=(255, 255, 255),
             anchor: str = "topleft", **kw) -> pygame.Rect:
        img = self.render(text, role, size, color, **kw)
        rect = img.get_rect(**{anchor: (int(pos[0]), int(pos[1]))})
        surf.blit(img, rect)
        return rect
