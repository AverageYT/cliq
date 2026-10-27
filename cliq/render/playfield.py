"""The note highway: lanes, beat lines, receptors, notes, holds and hit effects.

Shared by gameplay and the mapping editor so what you map is exactly what you
play. Notes are drawn from pre-rendered sprites and only the visible slice of
the chart is touched each frame (binary search on note times).
"""

from __future__ import annotations

import bisect
import math

import pygame

from ..util import darken, lighten
from . import vector as V
from .fx import Particles, ease_out_cubic
from .skins import NoteSkin

BASE_SPEED = 600.0   # px/s at 720p for scroll speed 1.0


class Playfield:
    def __init__(self, theme, settings, lanes: int, scale: float, screen_size, center_x: float | None = None,
                 speed_scale: float = 1.0):
        self.theme = theme
        self.scale = scale
        self.lanes = lanes
        self.screen_w, self.screen_h = screen_size
        self.lane_w = int(settings.lane_width * scale)
        self.width = self.lane_w * lanes
        cx = center_x if center_x is not None else self.screen_w / 2
        self.x0 = int(cx - self.width / 2)
        self.down = settings.scroll_direction != "up"
        margin = int(112 * scale)
        self.receptor_y = self.screen_h - margin if self.down else margin
        self.speed = BASE_SPEED * settings.scroll_speed * speed_scale * scale
        self.skin = NoteSkin(theme, settings.note_skin, lanes, self.lane_w)
        self.particles = Particles(scale)
        self.press = [0.0] * lanes        # receptor squash animation 0..1
        self.flash = [9.0] * lanes        # seconds since last hit
        self.rings: list[list] = []
        self.show_beat_lines = settings.show_beat_lines
        self._build_static()

    # ------------------------------------------------------------ geometry
    def lane_x(self, lane: int) -> float:
        return self.x0 + self.lane_w * (lane + 0.5)

    def y_at(self, dt: float) -> float:
        """Screen y of something ``dt`` seconds in the future."""
        return self.receptor_y - dt * self.speed if self.down else self.receptor_y + dt * self.speed

    def time_at_y(self, y: float, now: float) -> float:
        return now + ((self.receptor_y - y) if self.down else (y - self.receptor_y)) / self.speed

    def lane_at_x(self, x: float) -> int | None:
        lane = int((x - self.x0) // self.lane_w)
        return lane if 0 <= lane < self.lanes else None

    @property
    def ahead(self) -> float:
        """Seconds of chart visible ahead of the receptors."""
        dist = self.receptor_y if self.down else self.screen_h - self.receptor_y
        return (dist + self.lane_w) / self.speed

    @property
    def behind(self) -> float:
        dist = self.screen_h - self.receptor_y if self.down else self.receptor_y
        return (dist + self.lane_w) / self.speed

    # ------------------------------------------------------------ static art
    def _build_static(self) -> None:
        ink = self.theme.c("ink")
        h = self.screen_h + int(40 * self.scale)
        pad = int(10 * self.scale)
        self.panel = V.rounded_rect((self.width + 2 * pad, h), 26 * self.scale, (*self.theme.c("panel"), 222),
                                    ink, outline=max(2, 3.5 * self.scale))
        self.panel_pos = (self.x0 - pad, -int(20 * self.scale))
        self.beams = []
        for lane in range(self.lanes):
            color = self.skin.colors[lane]
            top = (*color, 0)
            bottom = (*lighten(color, 0.2), 95)
            length = int(self.screen_h * 0.55)
            beam = V.vertical_gradient((self.lane_w - int(6 * self.scale), length),
                                       top if self.down else bottom, bottom if self.down else top)
            self.beams.append(beam)
        self.ring_base = V.ring(int(self.lane_w * 0.5), 5 * self.scale, (255, 255, 255))

    # ------------------------------------------------------------ effects
    def on_hit(self, lane: int, judgement_id: str, color) -> None:
        self.flash[lane] = 0.0
        x, y = self.lane_x(lane), self.receptor_y
        lane_color = self.skin.colors[lane]
        if judgement_id in ("perfect", "great"):
            count = 8 if judgement_id == "perfect" else 5
            angle = -math.pi / 2 if self.down else math.pi / 2
            self.particles.burst(x, y, lighten(lane_color, 0.2), count=count, speed=520, spread=2.2, angle=angle,
                                 gravity=1500 if self.down else -1500, jitter=self.lane_w * 0.28)
            self.rings.append([x, y, 0.0, lane_color])
        elif judgement_id == "good":
            self.rings.append([x, y, 0.0, lane_color])

    def on_hold_tick(self, lane: int) -> None:
        x, y = self.lane_x(lane), self.receptor_y
        angle = -math.pi / 2 if self.down else math.pi / 2
        self.particles.burst(x, y, lighten(self.skin.colors[lane], 0.3), count=1, speed=380, spread=1.2, angle=angle,
                             gravity=1200 if self.down else -1200, shapes=("dot",), life=0.35)

    def update(self, dt: float, pressed) -> None:
        for lane in range(self.lanes):
            target = 1.0 if pressed[lane] else 0.0
            self.press[lane] += (target - self.press[lane]) * min(1.0, dt * 30)
            self.flash[lane] += dt
        self.particles.update(dt)
        for r in self.rings:
            r[2] += dt
        self.rings = [r for r in self.rings if r[2] < 0.32]

    # ------------------------------------------------------------ drawing
    def draw_panel(self, surf: pygame.Surface) -> None:
        surf.blit(self.panel, self.panel_pos)
        sep = darken(self.theme.c("panel_light"), 0.1)
        for lane in range(1, self.lanes):
            x = self.x0 + lane * self.lane_w
            pygame.draw.line(surf, sep, (x, 0), (x, self.screen_h), max(1, int(2 * self.scale)))

    def draw_beams(self, surf: pygame.Surface, pressed) -> None:
        for lane in range(self.lanes):
            if pressed[lane] or self.press[lane] > 0.05:
                beam = self.beams[lane]
                beam.set_alpha(int(255 * min(1.0, self.press[lane])))
                x = self.lane_x(lane) - beam.get_width() / 2
                y = self.receptor_y - beam.get_height() if self.down else self.receptor_y
                surf.blit(beam, (x, y))

    def draw_grid(self, surf: pygame.Surface, now: float, grid, division: int = 1, strong: bool = False) -> None:
        if grid is None:
            return
        t0, t1 = (now - self.behind, now + self.ahead)
        left, right = self.x0, self.x0 + self.width
        base = self.theme.c("panel_light")
        for t, kind in grid.lines(t0, t1, division):
            y = self.y_at(t - now)
            if kind == "measure":
                color, w = lighten(base, 0.35 if strong else 0.15), max(1, int((3 if strong else 2) * self.scale))
            elif kind == "beat":
                color, w = lighten(base, 0.12 if strong else 0.0), max(1, int(2 * self.scale))
                if not strong:
                    color = darken(base, 0.05)
            else:
                color, w = darken(base, 0.1), 1
            pygame.draw.line(surf, color, (left, y), (right, y), w)

    def draw_receptors(self, surf: pygame.Surface, pressed) -> None:
        skin = self.skin
        for lane in range(self.lanes):
            x, y = self.lane_x(lane), self.receptor_y
            p = self.press[lane]
            if self.flash[lane] < 0.14:
                t = ease_out_cubic(self.flash[lane] / 0.14)
                img = skin.scaled("flash", lane, 1.12 - 0.12 * t)
            elif p > 0.02:
                img = skin.scaled("pressed", lane, 1.0 - 0.1 * p)
            else:
                img = skin.receptor[lane]
            surf.blit(img, (x - img.get_width() / 2, y - img.get_height() / 2))

    def draw_effects(self, surf: pygame.Surface) -> None:
        for lane in range(self.lanes):
            f = self.flash[lane]
            if f < 0.16:
                glow = self.skin.glow[lane]
                glow.set_alpha(int(150 * (1 - f / 0.16)))
                surf.blit(glow, (self.lane_x(lane) - glow.get_width() / 2, self.receptor_y - glow.get_height() / 2))
        for x, y, age, color in self.rings:
            t = age / 0.32
            size = int(self.ring_base.get_width() * (0.8 + 0.5 * ease_out_cubic(t)))
            img = pygame.transform.smoothscale(self.ring_base, (size, size))
            img.fill((*lighten(color, 0.3), int(255 * (1 - t))), special_flags=pygame.BLEND_RGBA_MULT)
            surf.blit(img, (x - size / 2, y - size / 2))
        self.particles.draw(surf)

    def _visible(self, now: float, notes, times: list[float], max_hold: float, alpha_fn):
        """Yield (note, x, alpha, hit, dead) for notes on screen that still need drawing."""
        lo = bisect.bisect_left(times, now - self.behind - max_hold)
        hi = bisect.bisect_right(times, now + self.ahead)
        for i in range(lo, hi):
            n = notes[i]
            result = getattr(n, "result", None)
            if result == "skip":
                continue
            hit = result is not None and result != "miss"
            if hit and (not n.is_hold or getattr(n, "hold_done", False)):
                continue
            alpha = 1.0
            if alpha_fn is not None:
                alpha = alpha_fn(max(0.0, (n.time - now) / self.ahead))
                if alpha <= 0.01:
                    continue
            dead = result == "miss" or getattr(n, "hold_dropped", False)
            yield n, self.lane_x(n.lane), alpha, hit, dead

    def draw_holds(self, surf: pygame.Surface, now: float, notes, times: list[float], max_hold: float = 0.0,
                   alpha_fn=None) -> None:
        """Hold trails - drawn before the receptors so held trails tuck under them."""
        if max_hold <= 0:
            return
        skin = self.skin
        hold_w, outline = skin.hold_width, skin.hold_outline
        ink = self.theme.c("ink")
        for n, x, alpha, hit, dead in self._visible(now, notes, times, max_hold, alpha_fn):
            if not n.is_hold:
                continue
            holding = getattr(n, "holding", False)
            start_t = max(n.time, now) if (holding or (hit and not dead)) else n.time
            y_start, y_end = self.y_at(start_t - now), self.y_at(n.end - now)
            top, bottom = min(y_start, y_end), max(y_start, y_end)
            if bottom - top > 1:
                edge, fill = skin.hold_colors(n.lane, "dead" if dead else "held" if holding else "idle")
                body = pygame.Rect(0, 0, hold_w, bottom - top)
                body.midtop = (x, top)
                pygame.draw.rect(surf, ink, body)
                pygame.draw.rect(surf, edge, body.inflate(-2 * outline, 0))
                shine = body.inflate(-hold_w * 0.62, 0)
                shine.x -= int(hold_w * 0.12)
                pygame.draw.rect(surf, fill, shine)
            cap = skin.hold_cap_dead if dead else skin.hold_cap[n.lane]
            surf.blit(cap, (x - cap.get_width() / 2, y_end - cap.get_height() / 2))

    def draw_heads(self, surf: pygame.Surface, now: float, notes, times: list[float], max_hold: float = 0.0,
                   alpha_fn=None, highlight=None) -> None:
        """Note heads - drawn after the receptors so incoming notes pass over them."""
        skin = self.skin
        for n, x, alpha, hit, dead in self._visible(now, notes, times, max_hold, alpha_fn):
            if hit and not dead:
                continue  # a held note's head sits "inside" the receptor
            img = skin.note[n.lane]
            y = self.y_at(n.time - now)
            rect = img.get_rect(center=(x, y))
            if dead or alpha < 1.0:
                img.set_alpha(int(255 * (0.35 if dead else alpha)))
                surf.blit(img, rect)
                img.set_alpha(255)
            else:
                surf.blit(img, rect)
            if highlight is not None and highlight(n):
                box = pygame.Rect(0, 0, self.lane_w - 4, rect.height)
                box.center = rect.center
                pygame.draw.rect(surf, (255, 255, 255), box, max(2, int(3 * self.scale)),
                                 border_radius=int(12 * self.scale))

    def draw_chart(self, surf: pygame.Surface, now: float, notes, times: list[float], pressed, max_hold: float = 0.0,
                   alpha_fn=None, highlight=None) -> None:
        """Holds, receptors, then heads - the standard layering."""
        self.draw_holds(surf, now, notes, times, max_hold, alpha_fn)
        self.draw_receptors(surf, pressed)
        self.draw_heads(surf, now, notes, times, max_hold, alpha_fn, highlight)
