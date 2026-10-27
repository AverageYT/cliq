"""Easing curves and lightweight particle effects."""

from __future__ import annotations

import math
import random

import pygame

from . import vector as V


def clamp01(t: float) -> float:
    return 0.0 if t < 0 else 1.0 if t > 1 else t


def ease_out_cubic(t: float) -> float:
    t = clamp01(t)
    return 1 - (1 - t) ** 3


def ease_in_cubic(t: float) -> float:
    t = clamp01(t)
    return t * t * t


def ease_out_back(t: float, s: float = 1.9) -> float:
    t = clamp01(t) - 1
    return t * t * ((s + 1) * t + s) + 1


def ease_out_elastic(t: float) -> float:
    t = clamp01(t)
    if t in (0.0, 1.0):
        return t
    return 2 ** (-10 * t) * math.sin((t * 10 - 0.75) * (2 * math.pi) / 3) + 1


def pulse(phase: float, sharpness: float = 6.0) -> float:
    """1 at phase 0 decaying toward 0 - for beat bounces."""
    return math.exp(-max(0.0, phase) * sharpness)


class Particles:
    """Stars and dots that burst from hits. Sprites are cached per colour and size step."""

    SIZE_STEPS = 6

    def __init__(self, scale: float = 1.0, limit: int = 500):
        self.scale = scale
        self.limit = limit
        self.items: list[list] = []
        self._sprites: dict = {}
        self.rng = random.Random(3)

    def _sprite(self, shape: str, color, step: int) -> pygame.Surface:
        key = (shape, color, step)
        img = self._sprites.get(key)
        if img is None:
            size = max(3, int(24 * self.scale * step / self.SIZE_STEPS))
            if shape == "star":
                img = V.star(size, color)
            else:
                img = pygame.Surface((size, size), pygame.SRCALPHA)
                pygame.draw.circle(img, color, (size / 2, size / 2), size / 2)
            self._sprites[key] = img
        return img

    def burst(self, x: float, y: float, color, count: int = 10, speed: float = 520.0, life: float = 0.5,
              gravity: float = 1300.0, spread: float = math.tau, angle: float = -math.pi / 2,
              shapes=("star", "dot"), jitter: float = 0.0) -> None:
        s = self.scale
        for _ in range(count):
            if len(self.items) >= self.limit:
                self.items.pop(0)
            px = x + (self.rng.random() - 0.5) * 2 * jitter
            py = y + (self.rng.random() - 0.5) * jitter
            a = angle + (self.rng.random() - 0.5) * spread
            v = speed * s * (0.45 + 0.55 * self.rng.random())
            lt = life * (0.6 + 0.4 * self.rng.random())
            shape = self.rng.choice(shapes)
            size = 0.5 + 0.5 * self.rng.random()
            self.items.append([px, py, math.cos(a) * v, math.sin(a) * v, lt, lt, shape, tuple(color), size,
                               gravity * s])

    def update(self, dt: float) -> None:
        alive = []
        for p in self.items:
            p[4] -= dt
            if p[4] <= 0:
                continue
            p[2] *= 0.985
            p[3] += p[9] * dt
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            alive.append(p)
        self.items = alive

    def draw(self, surf: pygame.Surface) -> None:
        for x, y, _, _, life, max_life, shape, color, size, _ in self.items:
            t = life / max_life
            step = max(1, int(round(self.SIZE_STEPS * size * (0.35 + 0.65 * t))))
            img = self._sprite(shape, color, step)
            surf.blit(img, (x - img.get_width() / 2, y - img.get_height() / 2))

    def clear(self) -> None:
        self.items.clear()
