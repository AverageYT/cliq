"""Note skins: notes, receptors and hold trails for each lane.

Built-in styles are drawn procedurally ("arrows" like FnF, "circles", and
"bars" like rhythm-plus). To use your own art, put PNGs in
``assets/skins/<style>/`` named ``note_<direction>.png``,
``receptor_<direction>.png`` and ``receptor_<direction>_pressed.png``
(direction = left/down/up/right/center). Missing files fall back to the
procedural sprites, so you can replace just one piece.
"""

from __future__ import annotations

import math

import pygame

from .. import paths
from ..display import prepare
from ..util import darken, lighten, mix
from . import vector as V
from .theme import Theme


def _shape_points(style: str, direction: str) -> list[V.Point]:
    if style == "circles":
        return V.circle_points()
    if direction == "center":
        return V.diamond_points()
    return V.rotate(V.arrow_points(), V.DIRECTION_ANGLE.get(direction, 0))


class NoteSkin:
    def __init__(self, theme: Theme, style: str, lanes: int, lane_width: int):
        self.theme = theme
        self.style = style
        self.lanes = lanes
        self.lane_width = lane_width
        self.size = int(lane_width * (0.96 if style != "bars" else 1.0))
        ink = theme.c("ink")
        self.colors = [theme.lane_color(lanes, i) for i in range(lanes)]
        self.directions = [theme.lane_direction(lanes, i) for i in range(lanes)]
        self.note: list[pygame.Surface] = []
        self.receptor: list[pygame.Surface] = []
        self.pressed: list[pygame.Surface] = []
        self.flash: list[pygame.Surface] = []
        self.glow: list[pygame.Surface] = []
        self.hold_cap: list[pygame.Surface] = []
        self.hold_width = max(8, int(self.size * (0.34 if style != "bars" else 0.5)))
        self.hold_outline = max(2, int(self.size * 0.05))
        cache: dict = {}
        for lane in range(lanes):
            color, direction = self.colors[lane], self.directions[lane]
            key = (color, direction)
            if key not in cache:
                cache[key] = self._build(color, direction, ink)
            note, rec, pressed, flash = cache[key]
            self.note.append(note)
            self.receptor.append(rec)
            self.pressed.append(pressed)
            self.flash.append(flash)
            self.glow.append(V.soft_glow(int(self.size * 0.66), lighten(color, 0.45), 0.8))
            self.hold_cap.append(self._cap(color, ink))
        self.hold_cap_dead = self._cap((120, 112, 150), ink)
        # bar notes are short; everything else is square
        self.note_height = self.note[0].get_height()
        self._scaled: dict = {}

    # ------------------------------------------------------------ building
    def _custom(self, name: str) -> pygame.Surface | None:
        path = paths.SKINS_DIR / self.style / f"{name}.png"
        if not path.exists():
            return None
        try:
            img = prepare(pygame.image.load(str(path)), alpha=True)
        except pygame.error:
            return None
        w, h = img.get_size()
        scale = self.size / max(w, h)
        return pygame.transform.smoothscale(img, (max(1, int(w * scale)), max(1, int(h * scale))))

    def _build(self, color, direction: str, ink):
        if self.style == "bars":
            note, rec, pressed, flash = self._bars(color, ink)
        else:
            pts = _shape_points(self.style, direction)
            radius = 0.0 if self.style == "circles" else 0.13
            note = V.glossy_shape(self.size, pts, color, ink, radius=radius)
            rec = V.outline_shape(self.size, pts, self.theme.c("receptor"), self.theme.c("receptor_edge"), ink,
                                  radius=radius)
            pressed = V.outline_shape(self.size, pts, mix(color, self.theme.c("receptor"), 0.45),
                                      lighten(color, 0.5), ink, fill_alpha=235, radius=radius)
            flash = V.glossy_shape(self.size, pts, lighten(color, 0.35), ink, radius=radius, shadow=False)
        note = self._custom(f"note_{direction}") or note
        rec = self._custom(f"receptor_{direction}") or rec
        pressed = self._custom(f"receptor_{direction}_pressed") or pressed
        return note, rec, pressed, flash

    def _bars(self, color, ink):
        w = self.size - 6
        h = max(14, int(self.size * 0.3))
        note = V.rounded_rect((w, h), h * 0.45, (*color, 255), ink, outline=max(2, h * 0.14), shadow=h * 0.18,
                              shadow_color=(*darken(ink, 0.2), 110),
                              gradient=((*lighten(color, 0.3), 255), (*darken(color, 0.15), 255)))
        rec = V.rounded_rect((w, h), h * 0.45, (*self.theme.c("receptor"), 170), ink, outline=max(2, h * 0.14))
        pressed = V.rounded_rect((w, h), h * 0.45, (*mix(color, self.theme.c("receptor"), 0.4), 235), ink,
                                 outline=max(2, h * 0.14))
        flash = V.rounded_rect((w, h), h * 0.45, (*lighten(color, 0.4), 255), ink, outline=max(2, h * 0.14))
        return note, rec, pressed, flash

    def _cap(self, color, ink) -> pygame.Surface:
        w = self.hold_width
        o = self.hold_outline

        def draw(s: pygame.Surface, k: int) -> None:
            r = w * k / 2
            pygame.draw.circle(s, ink, (r, r), r)
            pygame.draw.circle(s, lighten(color, 0.15), (r, r), r - o * k)

        return V.supersample((w, w), draw)

    # ------------------------------------------------------------ helpers
    def scaled(self, kind: str, lane: int, scale: float) -> pygame.Surface:
        """Cached scaled copy (quantised to 2% steps) for squash/stretch animations."""
        base = getattr(self, kind)[lane]
        step = int(round(scale * 50))
        if step == 50:
            return base
        key = (kind, lane, step)
        img = self._scaled.get(key)
        if img is None:
            s = step / 50
            img = pygame.transform.smoothscale(base, (max(1, int(base.get_width() * s)),
                                                      max(1, int(base.get_height() * s))))
            self._scaled[key] = img
        return img

    def hold_colors(self, lane: int, state: str):
        if state == "dead":
            return (110, 104, 140), (150, 144, 178)
        color = self.colors[lane]
        if state == "held":
            return lighten(color, 0.25), lighten(color, 0.6)
        return mix(color, (255, 255, 255), 0.08), lighten(color, 0.45)


def lane_glyph(direction: str) -> str:
    return {"left": "<", "down": "v", "up": "^", "right": ">", "center": "o"}.get(direction, "?")


def angle_for(direction: str) -> float:
    return math.radians(V.DIRECTION_ANGLE.get(direction, 0))
