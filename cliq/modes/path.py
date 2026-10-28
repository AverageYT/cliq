"""Path: ride the track and perform each note's action.

Your ball rolls along a winding path. Notes sit on the path and say what to
do when you reach them - not which lane:

* **tap** (round)      - press any key
* **critical** (star)  - press all four keys together
* **mash** (stripes)   - spam keys until the stripe ends
* **hold** (long)      - hold any key until the end

The charter turns big downbeat accents into criticals, busy drum bursts into
mash sections and sustained notes into holds.
"""

from __future__ import annotations

import math

import pygame

from ..charting.autochart import _det_noise, chart_meta, plan_chart, resolve_profile
from ..charting.chart import Chart, Note
from ..gameplay.session import PlaySession
from ..render import vector as V
from ..render.fx import Particles, ease_out_back
from ..util import darken, lighten
from .base import GameMode, ModeView

TAP_COLORS = [(196, 107, 255), (46, 230, 255), (87, 242, 135), (255, 84, 112)]
CRIT_COLOR = (255, 79, 106)
MASH_COLOR = (255, 210, 63)
HOLD_COLOR = (124, 255, 107)


class PathSession(PlaySession):
    CRIT_SPREAD = 0.15      # all four keys must land within this window
    MASH_RATE = 5.0         # presses per second a mash asks for

    def __init__(self, chart, rules, modifiers=(), bus=None, start_time=-math.inf):
        super().__init__(chart, rules, modifiers, bus, start_time)
        self.queue = [ns for ns in self.notes if ns.kind != "mash"]
        self.mashes = [ns for ns in self.notes if ns.kind == "mash"]
        self._q = 0
        self.down: set[int] = set()
        self.crit_presses: dict[int, dict[int, float]] = {}
        self.mash_counts: dict[int, int] = {}
        self.hold: object | None = None
        self._last_hit = -10.0
        self._auto_mash = -1.0

    # ------------------------------------------------------------ helpers
    def _next(self):
        while self._q < len(self.queue) and self.queue[self._q].judged:
            self._q += 1
        return self.queue[self._q] if self._q < len(self.queue) else None

    def active_mash(self, t):
        for m in self.mashes:
            if not m.judged and m.time - 0.05 <= t <= m.end:
                return m
        return None

    def mash_needed(self, ns) -> int:
        return max(3, int(round((ns.end - ns.time) * self.MASH_RATE)))

    def _mash_press(self, m) -> None:
        self.mash_counts[m.index] = self.mash_counts.get(m.index, 0) + 1
        self.score += int(round(20 * self.rules.score_multiplier))
        self.bus.emit("mash_hit", session=self, note=m)

    # ------------------------------------------------------------ input
    def press(self, lane, t):
        if not 0 <= lane < self.lanes:
            return None
        self.pressed[lane] = True
        self.down.add(lane)
        if self.failed or self.finished or self.rules.autoplay:
            return None
        mash = self.active_mash(t)
        if mash is not None:
            self._mash_press(mash)
            return None
        window = self.rules.max_window
        ns = self._next()
        while ns is not None and t - ns.time > window:
            self._expire(ns)
            ns = self._next()
        if ns is not None and t - ns.time >= -window:
            if ns.kind == "critical":
                presses = self.crit_presses.setdefault(ns.index, {})
                presses.setdefault(lane, t)
                if len(presses) >= self.lanes:
                    times = list(presses.values())
                    err = sum(times) / len(times) - ns.time
                    spread = max(times) - min(times)
                    j = self.rules.judge(max(abs(err), spread / 2)) or self.rules.judgements[-1]
                    self._hit(ns, j, err)
                    self._last_hit = t
                return ns
            judgement = self.rules.judge(t - ns.time)
            if judgement is not None:
                self._hit(ns, judgement, t - ns.time)
                self._last_hit = t
                if ns.is_hold:
                    self.active_holds.pop(ns.lane, None)
                    self.hold = ns
                return ns
        if t - self._last_hit < 0.1:
            return None        # extra fingers right after a hit are not spam
        self._ghost(lane, t)
        return None

    def _ghost(self, lane, t):
        self.bus.emit("ghost_tap", session=self, lane=lane, time=t)
        if self.rules.anti_spam:
            ns = self._next()
            if ns is not None and ns.time - t <= self.rules.anti_spam_horizon:
                self._miss(ns)
                self.bus.emit("spam_penalty", session=self, note=ns, lane=lane)
        if not self.rules.ghost_tapping:
            self._break_combo(None)
            self._change_health(self.rules.ghost_tap_health)

    def release(self, lane, t):
        if not 0 <= lane < self.lanes:
            return
        self.pressed[lane] = False
        self.down.discard(lane)
        if self.hold is None or self.down or self.failed or self.finished:
            return
        ns, self.hold = self.hold, None
        ns.holding = False
        if t >= ns.end - self.rules.hold_release_window * self.rules.window_scale:
            self._complete_hold(ns)
        else:
            self._drop_hold(ns)

    def _expire(self, ns) -> None:
        if ns.kind == "critical" and len(self.crit_presses.get(ns.index, {})) >= 2:
            self._hit(ns, self.rules.judgements[-1], self.rules.max_window, record_error=False)
        else:
            self._miss(ns)

    # ------------------------------------------------------------ per frame
    def update(self, t):
        self.time = t
        if self.failed or self.finished:
            return
        window = self.rules.max_window
        if self.rules.autoplay:
            ns = self._next()
            if ns is not None and t >= ns.time:
                self.pressed = [True] * self.lanes
                self._hit(ns, self.rules.judgements[0], 0.0)
                self.bus.emit("auto_press", session=self, lane=0)
                if ns.is_hold:
                    self.active_holds.pop(ns.lane, None)
                    self.hold = ns
                    self.down = set(range(self.lanes))
            elif self.hold is None:
                self.pressed = [False] * self.lanes
            mash = self.active_mash(t)
            if mash is not None and t - self._auto_mash >= 1 / 9:
                self._auto_mash = t
                self._mash_press(mash)
        ns = self._next()
        while ns is not None and t - ns.time > window:
            self._expire(ns)
            ns = self._next()
        if self.hold is not None and t >= self.hold.end:
            ns, self.hold = self.hold, None
            ns.holding = False
            if self.rules.autoplay:
                self.down.clear()
            self._complete_hold(ns)
        for m in self.mashes:
            if not m.judged and t >= m.end:
                need = self.mash_needed(m)
                got = self.mash_counts.get(m.index, 0)
                if got >= need:
                    self._hit(m, self.rules.judgements[0], 0.0, record_error=False)
                elif got >= 0.6 * need:
                    self._hit(m, self.rules.judgements[min(2, len(self.rules.judgements) - 1)], 0.0,
                              record_error=False)
                else:
                    self._miss(m)
        for mod in self.modifiers:
            mod.on_update(self, t)
        if self._judged >= len(self.notes) and self.hold is None and t > self.end_time + window + 0.25:
            self.finished = True
            self.bus.emit("finish", session=self)


class PathMode(GameMode):
    id = "path"
    name = "Path"
    tagline = "Ride the track: tap, mash, hold and smash criticals"
    color = "#7CFF6B"

    def generate(self, analysis, difficulty, grid, settings, seed=0):
        profile = resolve_profile(difficulty)
        plan = plan_chart(analysis, profile, grid, density=0.7, min_gap_s=0.12)
        chart = Chart(lanes=4, difficulty=self.chart_stem(profile.id), mode=self.id,
                      meta=chart_meta(profile, grid, seed, mode=self.id))
        if plan is None:
            return chart
        ons = plan.onsets
        crit_gap = {"easy": 16, "normal": 12, "hard": 8, "expert": 8, "master": 4}.get(profile.id, 8)
        notes: list[Note] = []
        last_crit, mash_until, last_mash = -1e9, -1.0, -1e9
        for i, t in enumerate(plan.times):
            if t < mash_until:
                continue
            beat = grid.beat_length_at(t)
            # busy drum bursts become a mash section
            lo, hi = (ons.times.searchsorted(t), ons.times.searchsorted(t + 2 * beat))
            busy = int((ons.strength[lo:hi] > 0.25).sum())
            if busy >= 9 and t - last_mash >= 8 * beat and profile.id != "easy":
                length = grid.snap(t + 2 * beat, 4) - t
                notes.append(Note(t, 0, length, "mash"))
                mash_until, last_mash = t + length + beat * 0.5, t
                continue
            if (plan.level[i] == 0 and plan.intensity(i) >= profile.chord_threshold * 1.15
                    and t - last_crit >= crit_gap * beat and _det_noise(seed, t) < 0.8):
                notes.append(Note(t, 0, 0.0, "critical"))
                last_crit = t
                continue
            notes.append(Note(t, 0, plan.duration[i], "tap"))
        chart.notes = notes
        return chart.sort()

    def key_hint(self, settings, chart):
        return "Any key = tap   all 4 = star   spam = MASH   hold = long notes"

    def session(self, chart, rules, modifiers, bus, start_time):
        return PathSession(chart, rules, modifiers, bus, start_time=start_time)

    def view(self, scene):
        return PathView(scene)


class PathView(ModeView):
    def __init__(self, scene):
        super().__init__(scene)
        w, h = scene.size
        s = scene.s
        settings = scene.app.settings
        theme = scene.theme
        ink = theme.c("ink")
        self.px, self.py = int(w * 0.3), int(h * 0.55)
        self.speed = 520 * settings.scroll_speed * scene.rules.scroll_speed_scale * scene.ui.scale
        self.amp = s(120)
        seed = sum(map(ord, scene.song.id))
        self.phase = (seed % 97) / 97 * math.tau
        self.r = s(30)
        self.taps = [V.glossy_shape(self.r * 2, V.circle_points(), c, ink, radius=0.0) for c in TAP_COLORS]
        self.crit = V.glossy_shape(int(self.r * 3.2), V.star_points(5, 0.78, 0.4), CRIT_COLOR, ink, radius=0.06)
        self.mash_head = V.glossy_shape(int(self.r * 2.2), V.diamond_points(), MASH_COLOR, ink)
        self.ball = V.glossy_shape(int(self.r * 2.4), V.circle_points(), (255, 255, 255), ink, radius=0.0)
        self.particles = Particles(scene.ui.scale)
        self.bounce = 0.0
        self.center_x = self.px
        self.judge_y = self.py - s(170)
        self.countdown_y = self.py - s(170)
        self.error_y = h - s(46)
        self.health_x = w - s(52)
        self.info_limit = w * 0.4
        self.ahead = (w - self.px) / self.speed + 0.1
        self.autoplay_y = s(30)
        self.hint = scene.mode.key_hint(settings, scene.session.chart)

    def Y(self, tau: float) -> float:
        return self.amp * (0.62 * math.sin(tau * 0.9 + self.phase) + 0.38 * math.sin(tau * 0.37 + 2 * self.phase))

    def pos(self, tau: float, t: float) -> tuple[float, float]:
        return self.px + (tau - t) * self.speed, self.py + self.Y(tau) - self.Y(t)

    def on_judgement(self, note, judgement, error):
        if judgement.is_miss:
            return
        self.bounce = 1.0
        color = CRIT_COLOR if note.kind == "critical" else MASH_COLOR if note.kind == "mash" else \
            TAP_COLORS[note.index % 4]
        count = 18 if note.kind == "critical" else 8
        self.particles.burst(self.px, self.py, lighten(color, 0.3), count=count, speed=560, spread=math.tau)

    def update(self, dt, t):
        self.bounce = max(0.0, self.bounce - dt * 5)
        self.particles.update(dt)

    def _polyline(self, t0, t1, t, step=0.03):
        pts = []
        tau = t0
        while tau <= t1:
            pts.append(self.pos(tau, t))
            tau += step
        return pts

    def draw(self, surf, t):
        scene = self.scene
        s = scene.s
        theme = scene.theme
        w, h = scene.size
        t_end = t + self.ahead
        track = self._polyline(t - self.px / self.speed - 0.1, t_end, t)
        if len(track) > 1:
            pygame.draw.lines(surf, theme.c("ink"), False, track, s(30))
            pygame.draw.lines(surf, theme.c("panel_light"), False, track, s(22))
            pygame.draw.lines(surf, lighten(theme.c("panel_light"), 0.18), False, track, s(6))
            for p in track[::6]:
                pygame.draw.circle(surf, theme.c("ink"), p, s(15))
                pygame.draw.circle(surf, theme.c("panel_light"), p, s(11))
        # beat dots along the path
        grid = scene.grid
        for bt, kind in grid.lines(t, t_end, 1):
            x, y = self.pos(bt, t)
            pygame.draw.circle(surf, lighten(theme.c("panel_light"), 0.35 if kind == "measure" else 0.15), (x, y),
                               s(5 if kind == "measure" else 3))
        session = scene.session
        notes = session.notes
        for n in reversed(notes):
            if n.time > t_end or n.end < t - 0.3:
                continue
            done = n.result not in (None, "miss")
            if n.kind == "mash":
                if n.judged:
                    continue
                seg = self._polyline(max(n.time, t if n.time <= t else n.time), n.end, t, 0.02)
                if len(seg) > 1:
                    pygame.draw.lines(surf, theme.c("ink"), False, seg, s(40))
                    pygame.draw.lines(surf, MASH_COLOR, False, seg, s(30))
                    for k, p in enumerate(seg[::3]):
                        if k % 2:
                            pygame.draw.circle(surf, lighten(MASH_COLOR, 0.45), p, s(9))
                hx, hy = self.pos(max(n.time, t), t)
                surf.blit(self.mash_head, self.mash_head.get_rect(center=(hx, hy)))
                got = session.mash_counts.get(n.index, 0)
                need = session.mash_needed(n)
                label = f"MASH {got}/{need}" if n.time <= t else "MASH!"
                scene.fonts.draw(surf, label, (hx, hy - s(52)), "display", 26, MASH_COLOR, anchor="center", outline=4)
                continue
            if done and not (n.is_hold and getattr(n, "holding", False)):
                continue
            if n.is_hold:
                start = max(n.time, t) if getattr(n, "holding", False) else n.time
                seg = self._polyline(start, n.end, t, 0.02)
                if len(seg) > 1:
                    color = HOLD_COLOR if not n.hold_dropped else (120, 112, 150)
                    pygame.draw.lines(surf, theme.c("ink"), False, seg, s(34))
                    pygame.draw.lines(surf, color, False, seg, s(24))
                    ex, ey = seg[-1]
                    pygame.draw.circle(surf, theme.c("ink"), (ex, ey), s(17))
                    pygame.draw.circle(surf, lighten(color, 0.3), (ex, ey), s(12))
                if getattr(n, "holding", False):
                    continue
            x, y = self.pos(n.time, t)
            if n.kind == "critical":
                pulse = 1.0 + 0.08 * math.sin(t * 14)
                img = pygame.transform.rotozoom(self.crit, t * 40 % 360, pulse)
                surf.blit(img, img.get_rect(center=(x, y)))
                scene.fonts.draw(surf, "ALL 4!", (x, y - s(62)), "display", 22, CRIT_COLOR, anchor="center", outline=3)
                presses = session.crit_presses.get(n.index, {})
                for k in range(session.lanes):
                    col = CRIT_COLOR if k in presses else darken(theme.c("panel_light"), 0.1)
                    pygame.draw.circle(surf, theme.c("ink"), (x - s(27) + k * s(18), y + s(52)), s(8))
                    pygame.draw.circle(surf, col, (x - s(27) + k * s(18), y + s(52)), s(6))
            else:
                img = self.taps[n.index % 4]
                if n.result == "miss":
                    img.set_alpha(90)
                    surf.blit(img, img.get_rect(center=(x, y)))
                    img.set_alpha(255)
                else:
                    surf.blit(img, img.get_rect(center=(x, y)))
        # the player
        squash = 1.0 + 0.25 * ease_out_back(self.bounce) * self.bounce
        any_down = any(session.pressed)
        ball = pygame.transform.rotozoom(self.ball, 0, (0.92 if any_down else 1.0) * squash)
        surf.blit(ball, ball.get_rect(center=(self.px, self.py)))
        eye = theme.c("ink")
        pygame.draw.circle(surf, eye, (self.px + s(6), self.py - s(6)), s(5))
        pygame.draw.circle(surf, eye, (self.px + s(20), self.py - s(6)), s(5))
        pygame.draw.arc(surf, eye, pygame.Rect(self.px + s(2), self.py - s(4), s(22), s(16)), math.pi * 1.1,
                        math.pi * 1.9, max(2, s(3)))
        self.particles.draw(surf)
        scene.fonts.draw(surf, self.hint, (w // 2, h - s(80)), "bold", 18, theme.c("text_dim"), anchor="center",
                         outline=2)
