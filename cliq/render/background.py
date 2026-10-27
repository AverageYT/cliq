"""Animated cartoon background: soft gradient plus floating outlined shapes
that hop on every beat."""

from __future__ import annotations

import math
import random

import pygame

from ..util import darken, lighten, mix
from . import vector as V
from .fx import pulse
from .theme import Theme

SHAPES = ("circle", "ring", "square", "plus", "triangle", "star")


def _shape_sprite(kind: str, size: int, color, ink) -> pygame.Surface:
    def draw(s: pygame.Surface, k: int) -> None:
        full = size * k
        c = full / 2
        unit = full / 2 * 0.8
        o = max(2.0, unit * 0.16)
        if kind == "circle":
            pygame.draw.circle(s, ink, (c, c), unit)
            pygame.draw.circle(s, color, (c, c), unit - o)
            pygame.draw.circle(s, lighten(color, 0.35), (c - unit * 0.3, c - unit * 0.3), unit * 0.22)
        elif kind == "ring":
            pygame.draw.circle(s, ink, (c, c), unit)
            pygame.draw.circle(s, color, (c, c), unit - o)
            pygame.draw.circle(s, ink, (c, c), unit * 0.5 + o)
            pygame.draw.circle(s, (0, 0, 0, 0), (c, c), unit * 0.5)
        else:
            if kind == "square":
                pts = [(-0.55, -0.55), (0.55, -0.55), (0.55, 0.55), (-0.55, 0.55)]
            elif kind == "plus":
                a, b = 0.2, 0.62
                pts = [(-a, -b), (a, -b), (a, -a), (b, -a), (b, a), (a, a), (a, b), (-a, b), (-a, a), (-b, a),
                       (-b, -a), (-a, -a)]
            elif kind == "triangle":
                pts = [(0.0, -0.62), (0.62, 0.48), (-0.62, 0.48)]
            else:
                pts = V.star_points(5, 0.72, 0.34)
            pts = V.rotate(pts, random.Random(size).uniform(-25, 25))
            px = V.to_pixels(pts, c, c, unit)
            V.rounded_polygon(s, ink, px, unit * 0.22)
            V.rounded_polygon(s, color, px, unit * 0.22 - o)

    return V.supersample((size, size), draw)


class Background:
    def __init__(self, size: tuple[int, int], theme: Theme, scale: float = 1.0, seed: int = 1, count: int = 16,
                 dim: float = 0.0):
        self.size = size
        self.theme = theme
        self.scale = scale
        self.rng = random.Random(seed)
        self.items = []
        self.time = 0.0
        self.beat = None
        self._base = None
        self._dim = -1.0
        ink = darken(theme.c("ink"), 0.1)
        w, h = size
        for i in range(count):
            kind = SHAPES[i % len(SHAPES)]
            color = mix(self.rng.choice(theme.shape_colors), theme.c("bg_mid"), 0.1)
            px = int(self.rng.uniform(28, 92) * scale)
            sprite = _shape_sprite(kind, px, color, ink)
            sprite.set_alpha(175)
            self.items.append({
                "sprite": sprite, "x": self.rng.uniform(0, w), "y": self.rng.uniform(0, h),
                "vx": self.rng.uniform(-14, 14) * scale, "vy": self.rng.uniform(-22, -6) * scale,
                "phase": self.rng.uniform(0, math.tau), "hop": self.rng.uniform(5, 12) * scale,
            })
        self.set_dim(dim)

    def set_dim(self, dim: float) -> None:
        if abs(dim - self._dim) < 1e-3 and self._base is not None:
            return
        self._dim = dim
        th = self.theme
        base = V.vertical_gradient(self.size, th.c("bg_top"), th.c("bg_bottom"), th.c("bg_mid"))
        # soft diagonal stripes
        stripes = pygame.Surface(self.size, pygame.SRCALPHA)
        step = int(70 * self.scale)
        w, h = self.size
        for x in range(-h, w + h, step * 2):
            pygame.draw.polygon(stripes, (255, 255, 255, 12), [(x, 0), (x + step, 0), (x + step - h, h), (x - h, h)])
        base.blit(stripes, (0, 0))
        if dim > 0:
            shade = pygame.Surface(self.size, pygame.SRCALPHA)
            shade.fill((*darken(th.c("ink"), 0.5), int(255 * dim)))
            base.blit(shade, (0, 0))
        self._base = base.convert() if pygame.display.get_init() and pygame.display.get_surface() else base
        alpha = int(175 * (1.0 - dim * 0.85))
        for it in self.items:
            it["sprite"].set_alpha(alpha)

    def update(self, dt: float, beat: float | None = None) -> None:
        self.time += dt
        self.beat = beat
        w, h = self.size
        for it in self.items:
            it["x"] += it["vx"] * dt
            it["y"] += it["vy"] * dt
            margin = 120 * self.scale
            if it["y"] < -margin:
                it["y"] = h + margin * 0.5
                it["x"] = self.rng.uniform(0, w)
            if it["x"] < -margin:
                it["x"] = w + margin * 0.5
            elif it["x"] > w + margin:
                it["x"] = -margin * 0.5

    def draw(self, surf: pygame.Surface) -> None:
        surf.blit(self._base, (0, 0))
        hop_phase = (self.beat % 1.0) if self.beat is not None else None
        for it in self.items:
            img = it["sprite"]
            y = it["y"] + math.sin(self.time * 0.8 + it["phase"]) * 6 * self.scale
            if hop_phase is not None:
                y -= it["hop"] * pulse(hop_phase, 7.0)
            surf.blit(img, (it["x"] - img.get_width() / 2, y - img.get_height() / 2))
