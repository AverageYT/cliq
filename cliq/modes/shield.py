"""Shield: block spears like the Undyne fight in Undertale.

Arrows fly in from the four sides toward the heart in the middle. Turn the
shield to face an arrow before it lands (D/F/K/L or the arrow keys = left,
down, up, right). Yellow arrows come in from the wrong side and swing around at
the last moment - block where they *end up*.
"""

from __future__ import annotations

import math

import pygame

from ..charting.autochart import _det_noise, chart_meta, plan_chart, resolve_profile
from ..charting.chart import Chart, Note
from ..gameplay.session import PlaySession
from ..render import vector as V
from ..render.fx import Particles, ease_out_cubic
from ..util import darken, lighten
from .base import GameMode, ModeView

LEFT, DOWN, UP, RIGHT = 0, 1, 2, 3
# unit vector pointing from the heart toward the side an arrow comes from
SIDE = {LEFT: (-1, 0), DOWN: (0, 1), UP: (0, -1), RIGHT: (1, 0)}
ANGLE = {LEFT: 180.0, DOWN: 90.0, UP: 270.0, RIGHT: 0.0}   # screen angles (y down)
OPPOSITE = {LEFT: RIGHT, RIGHT: LEFT, UP: DOWN, DOWN: UP}
REVERSE_COLOR = (255, 214, 64)


class ShieldSession(PlaySession):
    """Blocking is about *state*: whatever the shield faces when an arrow lands."""

    def __init__(self, chart, rules, modifiers=(), bus=None, start_time=-math.inf):
        super().__init__(chart, rules, modifiers, bus, start_time)
        self.facing = UP
        self.order = sorted(self.notes, key=lambda n: n.time)
        self._i = 0

    def press(self, lane, t):
        if not 0 <= lane < self.lanes or self.failed or self.finished or self.rules.autoplay:
            return None
        self.facing = lane
        self.pressed = [i == lane for i in range(self.lanes)]
        self.bus.emit("shield_turn", session=self, lane=lane)
        return None

    def release(self, lane, t):
        pass

    def update(self, t):
        self.time = t
        if self.failed or self.finished:
            return
        while self._i < len(self.order) and self.order[self._i].judged:
            self._i += 1
        if self.rules.autoplay and self._i < len(self.order):
            nxt = self.order[self._i]
            if t >= nxt.time - 0.08 and self.facing != nxt.lane:
                self.facing = nxt.lane
                self.pressed = [i == nxt.lane for i in range(self.lanes)]
                self.bus.emit("shield_turn", session=self, lane=nxt.lane)
        while self._i < len(self.order) and self.order[self._i].time <= t:
            ns = self.order[self._i]
            self._i += 1
            if ns.judged:
                continue
            if self.facing == ns.lane:
                self._hit(ns, self.rules.judgements[0], 0.0, record_error=False)   # blocks have no timing error
            else:
                self._miss(ns)
        for m in self.modifiers:
            m.on_update(self, t)
        if self._i >= len(self.order) and t > self.end_time + 0.4 and not self.failed:
            self.finished = True
            self.bus.emit("finish", session=self)


class ShieldMode(GameMode):
    id = "shield"
    name = "Shield"
    tagline = "Turn the shield to block every spear"
    color = "#3DDCFF"

    def generate(self, analysis, difficulty, grid, settings, seed=0):
        profile = resolve_profile(difficulty)
        # fewer, well-spaced arrows: you need time to turn
        plan = plan_chart(analysis, profile, grid, density=0.55, min_gap_s=0.17)
        chart = Chart(lanes=4, difficulty=self.chart_stem(profile.id), mode=self.id,
                      meta=chart_meta(profile, grid, seed, mode=self.id))
        if plan is None:
            return chart
        ons = plan.onsets
        reverse_rate = {"easy": 0.0, "normal": 0.0, "hard": 0.12, "expert": 0.22, "master": 0.3}.get(profile.id, 0.15)
        notes, last_dir, last_tone, streak = [], UP, None, 0
        for i, t in enumerate(plan.times):
            k = plan.onset[i]
            tone = float(ons.tone[k]) if k >= 0 else last_tone
            low = float(ons.low[k]) if k >= 0 else 0.0
            high = float(ons.high[k]) if k >= 0 else 0.0
            mid = float(ons.mid[k]) if k >= 0 else 0.0
            if tone is not None and last_tone is not None and abs(tone - last_tone) >= 0.75:
                d = RIGHT if tone > last_tone else LEFT
            elif low > 1.2 * max(mid, high):
                d = DOWN
            elif high > 1.2 * max(low, mid):
                d = UP
            else:
                d = last_dir
            streak = streak + 1 if d == last_dir else 0
            if streak >= 3:     # keep the player turning
                d = [LEFT, DOWN, UP, RIGHT][int(_det_noise(seed, t, i) * 4) % 4]
                streak = 0
            kind = "reverse" if (plan.intensity(i) >= profile.chord_threshold * 0.9
                                 and _det_noise(seed + 7, t) < reverse_rate) else "tap"
            notes.append(Note(t, d, 0.0, kind))
            last_dir = d
            if tone is not None:
                last_tone = tone
        chart.notes = notes
        return chart.sort()

    def key_hint(self, settings, chart):
        k = [x.upper() for x in settings.keys_for(4)]
        return f"{k[0]} left  {k[1]} down  {k[2]} up  {k[3]} right  (arrow keys work too)"

    def session(self, chart, rules, modifiers, bus, start_time):
        return ShieldSession(chart, rules, modifiers, bus, start_time=start_time)

    def view(self, scene):
        return ShieldView(scene)


class ShieldView(ModeView):
    def __init__(self, scene):
        super().__init__(scene)
        w, h = scene.size
        s = scene.s
        settings = scene.app.settings
        theme = scene.theme
        self.cx, self.cy = w // 2, int(h * 0.56)
        self.hit_r = s(82)
        self.speed = 430 * settings.scroll_speed * scene.rules.scroll_speed_scale * scene.ui.scale
        self.flip_d = s(150)
        self.arrow_size = s(70)
        ink = theme.c("ink")
        self.sprites = {}
        for lane in range(4):
            color = theme.lane_color(4, lane)
            for kind, col in (("tap", color), ("reverse", REVERSE_COLOR)):
                # arrows point toward the heart, i.e. away from the side they come from
                pts = V.rotate(V.arrow_points(), ANGLE[lane] + 90 + 180)
                self.sprites[(lane, kind)] = V.glossy_shape(self.arrow_size, pts, col, ink)
        self.base_up = V.glossy_shape(self.arrow_size, V.arrow_points(), REVERSE_COLOR, ink)
        self.heart = self._heart(s(54))
        self.ring = V.ring(self.hit_r, s(4), lighten(theme.c("panel_light"), 0.2))
        self.disc = V.rounded_rect((self.hit_r * 2, self.hit_r * 2), self.hit_r, (*theme.c("panel"), 210),
                                   ink, outline=max(2, s(3.5)))
        self.particles = Particles(scene.ui.scale)
        self.shield_angle = ANGLE[UP]
        self.block_flash = 0.0
        self.hurt = 0.0
        self.center_x = self.cx
        self.judge_y = self.cy - self.hit_r - s(150)
        self.countdown_y = self.cy - self.hit_r - s(120)
        self.error_y = None
        self.health_x = w - s(52)
        self.info_limit = w * 0.4
        self.ahead = (max(w, h) * 0.6) / self.speed
        self.autoplay_y = s(30)
        self.hint = scene.mode.key_hint(settings, scene.session.chart)

    def _heart(self, size):
        ink, color = self.scene.theme.c("ink"), (255, 64, 96)

        def draw(s, k):
            u = size * k
            pts = [(0.5 * u, 0.9 * u), (0.12 * u, 0.48 * u), (0.88 * u, 0.48 * u)]
            for col, grow in ((ink, 0.09 * u), (color, 0.0)):
                pygame.draw.circle(s, col, (0.32 * u, 0.36 * u), 0.2 * u + grow)
                pygame.draw.circle(s, col, (0.68 * u, 0.36 * u), 0.2 * u + grow)
                V.rounded_polygon(s, col, pts, grow + 0.02 * u)
            pygame.draw.circle(s, lighten(color, 0.5), (0.3 * u, 0.32 * u), 0.06 * u)

        return V.supersample((size, size), draw)

    def on_judgement(self, note, judgement, error):
        a = math.radians(ANGLE[note.lane])
        x = self.cx + math.cos(a) * self.hit_r
        y = self.cy + math.sin(a) * self.hit_r
        if judgement.is_miss:
            self.hurt = 1.0
            self.particles.burst(self.cx, self.cy, (255, 80, 110), count=8, speed=300)
        else:
            self.block_flash = 1.0
            color = REVERSE_COLOR if note.kind == "reverse" else self.scene.theme.lane_color(4, note.lane)
            self.particles.burst(x, y, lighten(color, 0.3), count=8, speed=420, angle=a, spread=1.6, gravity=0)

    def update(self, dt, t):
        target = ANGLE[self.scene.session.facing]
        diff = (target - self.shield_angle + 180) % 360 - 180
        self.shield_angle += diff * min(1.0, dt * 28)
        self.block_flash = max(0.0, self.block_flash - dt * 5)
        self.hurt = max(0.0, self.hurt - dt * 3)
        self.particles.update(dt)

    def _arrow_pos(self, n, t):
        d = (n.time - t) * self.speed
        if n.kind == "reverse" and d > self.flip_d:
            ang = ANGLE[OPPOSITE[n.lane]]
        elif n.kind == "reverse":
            ang = ANGLE[OPPOSITE[n.lane]] + 180.0 * ease_out_cubic(1 - d / self.flip_d)
        else:
            ang = ANGLE[n.lane]
        r = self.hit_r + max(0.0, d)
        a = math.radians(ang)
        return self.cx + math.cos(a) * r, self.cy + math.sin(a) * r, ang

    def draw(self, surf, t):
        scene = self.scene
        s = scene.s
        theme = scene.theme
        w, h = scene.size
        guide = darken(theme.c("panel_light"), 0.05)
        for lane in range(4):
            dx, dy = SIDE[lane]
            pygame.draw.line(surf, guide, (self.cx + dx * self.hit_r, self.cy + dy * self.hit_r),
                             (self.cx + dx * w, self.cy + dy * w), max(2, s(3)))
        shake = math.sin(t * 90) * s(6) * self.hurt
        surf.blit(self.disc, self.disc.get_rect(center=(self.cx + shake, self.cy)))
        surf.blit(self.ring, self.ring.get_rect(center=(self.cx + shake, self.cy)))
        # arrows
        for n in scene.session.notes:
            if n.judged:
                continue
            if n.time - t > self.ahead:
                break
            x, y, ang = self._arrow_pos(n, t)
            dist = (n.time - t) * self.speed
            if n.kind == "reverse" and dist <= self.flip_d:
                img = pygame.transform.rotozoom(self.base_up, 90 - ang, 1.0)   # swinging around the heart
            elif n.kind == "reverse":
                img = self.sprites[(OPPOSITE[n.lane], "reverse")]
            else:
                img = self.sprites[(n.lane, "tap")]
            surf.blit(img, img.get_rect(center=(x, y)))
        # shield
        color = lighten(theme.lane_color(4, scene.session.facing), 0.25 + 0.5 * self.block_flash)
        r = self.hit_r + s(10)
        rect = pygame.Rect(0, 0, r * 2, r * 2)
        rect.center = (self.cx + shake, self.cy)
        start = math.radians(-self.shield_angle - 50)
        end = math.radians(-self.shield_angle + 50)
        pygame.draw.arc(surf, theme.c("ink"), rect.inflate(s(10), s(10)), start - 0.06, end + 0.06, s(22))
        pygame.draw.arc(surf, color, rect, start, end, s(14))
        heart = self.heart
        if self.hurt > 0:
            heart = heart.copy()
            heart.fill((255, 255, 255, int(150 * self.hurt)), special_flags=pygame.BLEND_RGBA_ADD)
        surf.blit(heart, heart.get_rect(center=(self.cx + shake, self.cy)))
        self.particles.draw(surf)
        scene.fonts.draw(surf, self.hint, (w // 2, h - s(54)), "bold", 18, theme.c("text_dim"), anchor="center",
                         outline=2)
