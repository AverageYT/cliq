"""Clean vector-style sprites drawn procedurally.

Shapes are drawn at 4x size and smooth-scaled down, which gives crisp
anti-aliased edges. Rounded shapes are built as a polygon "inflated" by a
circle (Minkowski sum): fill the polygon, then stroke every edge with a quad
and every corner with a circle. Drawing the same core polygon with a larger
radius in the ink colour first produces an even cartoon outline.
"""

from __future__ import annotations

import math

import pygame

from ..util import darken, lighten

SS = 4  # supersampling factor

Point = tuple[float, float]


# --------------------------------------------------------------------------- geometry
def rotate(points: list[Point], degrees: float) -> list[Point]:
    a = math.radians(degrees)
    ca, sa = math.cos(a), math.sin(a)
    return [(x * ca - y * sa, x * sa + y * ca) for x, y in points]


def arrow_points() -> list[Point]:
    """Chunky up-pointing arrow in unit space (core polygon, before rounding)."""
    return [(0.0, -0.7), (0.68, 0.0), (0.27, 0.0), (0.27, 0.64), (-0.27, 0.64), (-0.27, 0.0), (-0.68, 0.0)]


def diamond_points() -> list[Point]:
    return [(0.0, -0.62), (0.62, 0.0), (0.0, 0.62), (-0.62, 0.0)]


def star_points(n: int = 5, outer: float = 1.0, inner: float = 0.45) -> list[Point]:
    pts = []
    for i in range(n * 2):
        r = outer if i % 2 == 0 else inner
        a = math.pi * i / n - math.pi / 2
        pts.append((math.cos(a) * r, math.sin(a) * r))
    return pts


DIRECTION_ANGLE = {"up": 0, "right": 90, "down": 180, "left": 270}


# --------------------------------------------------------------------------- primitives
def rounded_polygon(surf: pygame.Surface, color, points: list[Point], radius: float) -> None:
    """Fill ``points`` inflated by ``radius`` (rounded corners). Coordinates in pixels."""
    pts = [(float(x), float(y)) for x, y in points]
    if len(pts) >= 3:
        pygame.draw.polygon(surf, color, pts)
    if radius <= 0:
        return
    n = len(pts)
    for i in range(n):
        (x1, y1), (x2, y2) = pts[i], pts[(i + 1) % n]
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / length * radius, dx / length * radius
        pygame.draw.polygon(surf, color, [(x1 + nx, y1 + ny), (x2 + nx, y2 + ny), (x2 - nx, y2 - ny), (x1 - nx, y1 - ny)])
        pygame.draw.circle(surf, color, (x1, y1), radius)


def to_pixels(points: list[Point], cx: float, cy: float, scale: float) -> list[Point]:
    return [(cx + x * scale, cy + y * scale) for x, y in points]


def supersample(size: tuple[int, int], draw) -> pygame.Surface:
    """Call ``draw(surface, k)`` on a k-times larger canvas, return it smooth-scaled to ``size``."""
    w, h = max(1, int(size[0])), max(1, int(size[1]))
    big = pygame.Surface((w * SS, h * SS), pygame.SRCALPHA)
    draw(big, SS)
    return pygame.transform.smoothscale(big, (w, h))


def clip_to(shape_mask: pygame.Surface, layer: pygame.Surface) -> pygame.Surface:
    """Keep ``layer`` only where ``shape_mask`` is opaque."""
    out = layer.copy()
    out.blit(shape_mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
    return out


def glossy_shape(size: int, points: list[Point], color, ink, outline: float = 0.085, radius: float = 0.13,
                 shine: bool = True, shadow: bool = True, fill_alpha: int = 255) -> pygame.Surface:
    """A cartoon sprite: drop shadow, ink outline, shaded fill and a shine spot.

    ``points`` are in unit space (-1..1); ``size`` is the sprite edge in pixels.
    """
    def draw(s: pygame.Surface, k: int) -> None:
        full = size * k
        c = full / 2
        unit = full / 2 * 0.86
        pts = to_pixels(points, c, c - unit * 0.02, unit)
        r = radius * unit
        o = outline * unit
        if shadow:
            sh = pygame.Surface(s.get_size(), pygame.SRCALPHA)
            rounded_polygon(sh, (*darken(ink, 0.2), 110), [(x, y + unit * 0.09) for x, y in pts], r + o)
            s.blit(sh, (0, 0))
        rounded_polygon(s, ink, pts, r + o)
        body = pygame.Surface(s.get_size(), pygame.SRCALPHA)
        rounded_polygon(body, (*color, 255), pts, r)
        layer = pygame.Surface(s.get_size(), pygame.SRCALPHA)
        rounded_polygon(layer, (*darken(color, 0.28), 255), pts, r)                           # bottom shade
        rounded_polygon(layer, (*color, 255), [(x, y - unit * 0.1) for x, y in pts], r)       # main fill
        rounded_polygon(layer, (*lighten(color, 0.38), 255), [(x, y - unit * 0.42) for x, y in pts], r * 0.9)
        rounded_polygon(layer, (*color, 255), [(x, y - unit * 0.3) for x, y in pts], r * 0.9)  # soft top highlight
        layer = clip_to(body, layer)
        if fill_alpha < 255:
            layer.fill((255, 255, 255, fill_alpha), special_flags=pygame.BLEND_RGBA_MULT)
        s.blit(layer, (0, 0))
        if shine:
            bx, by = min(p[0] for p in pts), min(p[1] for p in pts)
            ex, ey = max(p[0] for p in pts), max(p[1] for p in pts)
            w, h = (ex - bx), (ey - by)
            spot = pygame.Rect(0, 0, w * 0.22, h * 0.13)
            spot.center = (bx + w * 0.34, by + h * 0.3)
            shine_layer = pygame.Surface(s.get_size(), pygame.SRCALPHA)
            pygame.draw.ellipse(shine_layer, (255, 255, 255, 170), spot)
            s.blit(clip_to(body, shine_layer), (0, 0))

    return supersample((size, size), draw)


def outline_shape(size: int, points: list[Point], fill, edge, ink, fill_alpha: int = 170,
                  outline: float = 0.085, radius: float = 0.13, edge_width: float = 0.06) -> pygame.Surface:
    """Receptor-style sprite: translucent fill, light inner edge, ink outline."""
    def draw(s: pygame.Surface, k: int) -> None:
        full = size * k
        c = full / 2
        unit = full / 2 * 0.86
        pts = to_pixels(points, c, c - unit * 0.02, unit)
        r = radius * unit
        o = outline * unit
        rounded_polygon(s, ink, pts, r + o)
        rounded_polygon(s, edge, pts, r)
        inner = pygame.Surface(s.get_size(), pygame.SRCALPHA)
        rounded_polygon(inner, (*fill, 255), pts, max(0.0, r - edge_width * unit))
        inner.fill((255, 255, 255, fill_alpha), special_flags=pygame.BLEND_RGBA_MULT)
        hole = pygame.Surface(s.get_size(), pygame.SRCALPHA)
        rounded_polygon(hole, (0, 0, 0, 255), pts, max(0.0, r - edge_width * unit))
        s.blit(hole, (0, 0), special_flags=pygame.BLEND_RGBA_SUB)
        s.blit(inner, (0, 0))

    return supersample((size, size), draw)


def circle_points(n: int = 40, r: float = 0.62) -> list[Point]:
    return [(math.cos(2 * math.pi * i / n) * r, math.sin(2 * math.pi * i / n) * r) for i in range(n)]


def rounded_rect(size: tuple[int, int], radius: float, fill, outline_color=None, outline: float = 0,
                 shadow: float = 0, shadow_color=(0, 0, 0, 90), gradient=None) -> pygame.Surface:
    """Anti-aliased rounded rectangle sprite (all sizes in pixels)."""
    w, h = size
    extra = int(math.ceil(shadow))

    def draw(s: pygame.Surface, k: int) -> None:
        rect = pygame.Rect(0, 0, w * k, h * k)
        rad = int(radius * k)
        if shadow:
            pygame.draw.rect(s, shadow_color, rect.move(0, extra * k), border_radius=rad)
        if outline and outline_color is not None:
            pygame.draw.rect(s, outline_color, rect, border_radius=rad)
            rect = rect.inflate(-2 * outline * k, -2 * outline * k)
            rad = max(0, rad - int(outline * k))
        if gradient:
            top, bottom = gradient
            body = pygame.Surface(rect.size, pygame.SRCALPHA)
            pygame.draw.rect(body, (255, 255, 255, 255), body.get_rect(), border_radius=rad)
            grad = vertical_gradient(rect.size, top, bottom)
            body.blit(grad, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
            s.blit(body, rect.topleft)
        else:
            pygame.draw.rect(s, fill, rect, border_radius=rad)

    return supersample((w, h + extra), draw)


def vertical_gradient(size: tuple[int, int], top, bottom, mid=None) -> pygame.Surface:
    """Vertical gradient (optionally 3-stop). Colours may include alpha."""
    w, h = max(1, int(size[0])), max(1, int(size[1]))
    top = tuple(top) + ((255,) if len(top) == 3 else ())
    bottom = tuple(bottom) + ((255,) if len(bottom) == 3 else ())
    if mid is not None:
        mid = tuple(mid) + ((255,) if len(mid) == 3 else ())
    strip = pygame.Surface((1, h), pygame.SRCALPHA)
    for y in range(h):
        t = y / max(1, h - 1)
        if mid is not None:
            a, b, tt = (top, mid, t * 2) if t < 0.5 else (mid, bottom, (t - 0.5) * 2)
        else:
            a, b, tt = top, bottom, t
        strip.set_at((0, y), tuple(int(a[i] + (b[i] - a[i]) * tt) for i in range(4)))
    return pygame.transform.scale(strip, (w, h))


def soft_glow(radius: int, color, strength: float = 1.0) -> pygame.Surface:
    """Radial glow sprite for additive blending."""
    size = radius * 2
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    steps = 24
    for i in range(steps, 0, -1):
        t = i / steps
        a = int(255 * strength * (1 - t) ** 2)
        pygame.draw.circle(surf, (*color, a), (radius, radius), max(1, int(radius * t)))
    return surf


def ring(radius: int, width: float, color) -> pygame.Surface:
    def draw(s: pygame.Surface, k: int) -> None:
        c = radius * k
        pygame.draw.circle(s, color, (c, c), c, max(1, int(width * k)))

    return supersample((radius * 2, radius * 2), draw)


def star(size: int, color, ink=None, outline: float = 0.12) -> pygame.Surface:
    pts = star_points(5, 0.8, 0.38)

    def draw(s: pygame.Surface, k: int) -> None:
        unit = size * k / 2
        p = to_pixels(pts, unit, unit, unit * 0.9)
        if ink is not None:
            rounded_polygon(s, ink, p, outline * unit)
        rounded_polygon(s, color, p, outline * unit * 0.3)

    return supersample((size, size), draw)
