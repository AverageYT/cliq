"""One play of one chart: judging, combo, score, health. No rendering, no audio.

Feed it key presses/releases stamped with song time and call ``update(t)``
every frame. Everything interesting is also announced on the event bus
(``judgement``, ``hold_complete``, ``hold_drop``, ``combo_break``, ``fail``,
``finish``...) so effects, sounds and modifiers can react without the session
knowing about them. Being renderer-free makes it easy to unit test and to reuse
for future game modes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..charting.chart import Chart
from ..events import EventBus
from .rules import Judgement, Rules


@dataclass
class NoteState:
    index: int
    time: float
    lane: int
    end: float
    is_hold: bool
    kind: str = "tap"
    judged: bool = False
    result: str | None = None      # judgement id, "miss" or "skip"
    error: float | None = None     # seconds; negative = early
    holding: bool = False
    hold_done: bool = False
    hold_dropped: bool = False


class PlaySession:
    def __init__(self, chart: Chart, rules: Rules, modifiers=(), bus: EventBus | None = None,
                 start_time: float = -math.inf):
        self.chart = chart
        self.lanes = chart.lanes
        self.rules = rules
        self.bus = bus or EventBus()
        self.modifiers = list(modifiers)
        ordered = sorted(chart.notes, key=lambda n: (n.time, n.lane))
        self.notes = [NoteState(i, n.time, n.lane, n.end, n.is_hold, n.kind) for i, n in enumerate(ordered)]
        self._queues: list[list[NoteState]] = [[] for _ in range(self.lanes)]
        for ns in self.notes:
            self._queues[ns.lane].append(ns)
        self._ptr = [0] * self.lanes
        self.active_holds: dict[int, NoteState] = {}
        self.pressed = [False] * self.lanes
        self._auto_release: dict[int, float] = {}

        self.score = 0
        self.combo = 0
        self.max_combo = 0
        self.combo_breaks = 0
        self.health = rules.health_start
        self.counts = {j.id: 0 for j in rules.judgements}
        self.counts.update({"miss": 0, "hold_ok": 0, "hold_drop": 0})
        self.errors: list[float] = []
        self._acc_sum = 0.0
        self._acc_n = 0
        self._judged = 0
        self.failed = False
        self.finished = False
        self.time = start_time
        self.end_time = max((n.end for n in self.notes), default=0.0)

        if start_time > -math.inf:
            for ns in self.notes:
                if ns.time < start_time:
                    ns.judged, ns.result = True, "skip"
                    self._judged += 1
        for m in self.modifiers:
            m.on_session_start(self)

    # ------------------------------------------------------------ queries
    @property
    def accuracy(self) -> float:
        return self._acc_sum / self._acc_n if self._acc_n else 1.0

    @property
    def misses(self) -> int:
        return self.counts["miss"] + self.counts["hold_drop"]

    @property
    def full_combo(self) -> bool:
        return self.combo_breaks == 0 and not self.failed

    def next_note(self, lane: int) -> NoteState | None:
        q, p = self._queues[lane], self._ptr[lane]
        while p < len(q) and q[p].judged:
            p += 1
        self._ptr[lane] = p
        return q[p] if p < len(q) else None

    # ------------------------------------------------------------ input
    def press(self, lane: int, t: float) -> NoteState | None:
        """A lane key went down at song time ``t``. Returns the note it hit, if any."""
        if not 0 <= lane < self.lanes:
            return None
        self.pressed[lane] = True
        if self.failed or self.finished or self.rules.autoplay:
            return None
        window = self.rules.max_window
        ns = self.next_note(lane)
        while ns is not None and t - ns.time > window:   # stale note not yet auto-missed
            self._miss(ns)
            ns = self.next_note(lane)
        if ns is not None and t - ns.time >= -window:
            judgement = self.rules.judge(t - ns.time)
            if judgement is not None:
                self._hit(ns, judgement, t - ns.time)
                return ns
        self._ghost(lane, t)
        return None

    def release(self, lane: int, t: float) -> None:
        if not 0 <= lane < self.lanes:
            return
        self.pressed[lane] = False
        ns = self.active_holds.pop(lane, None)
        if ns is None or self.failed or self.finished:
            return
        ns.holding = False
        if t >= ns.end - self.rules.hold_release_window * self.rules.window_scale:
            self._complete_hold(ns)
        else:
            self._drop_hold(ns)

    # ------------------------------------------------------------ per frame
    def update(self, t: float) -> None:
        self.time = t
        if self.failed or self.finished:
            return
        if self.rules.autoplay:
            self._autoplay(t)
        window = self.rules.max_window
        for lane in range(self.lanes):
            ns = self.next_note(lane)
            while ns is not None and t - ns.time > window:
                self._miss(ns)
                ns = self.next_note(lane)
        for lane, ns in list(self.active_holds.items()):
            if t >= ns.end:
                del self.active_holds[lane]
                ns.holding = False
                self._complete_hold(ns)
        for m in self.modifiers:
            m.on_update(self, t)
        if (self._judged >= len(self.notes) and not self.active_holds
                and t > self.end_time + window + 0.25 and not self.failed):
            self.finished = True
            self.bus.emit("finish", session=self)

    def _autoplay(self, t: float) -> None:
        for lane, until in list(self._auto_release.items()):
            if t >= until and lane not in self.active_holds:
                self.pressed[lane] = False
                del self._auto_release[lane]
        for lane in range(self.lanes):
            ns = self.next_note(lane)
            if ns is not None and t >= ns.time:
                self.pressed[lane] = True
                self._auto_release[lane] = ns.end + 0.07
                self._hit(ns, self.rules.judgements[0], 0.0)
                self.bus.emit("auto_press", session=self, lane=lane)

    # ------------------------------------------------------------ outcomes
    def _add_accuracy(self, value: float) -> None:
        self._acc_sum += value
        self._acc_n += 1

    def _hit(self, ns: NoteState, judgement: Judgement, error: float) -> None:
        ns.judged, ns.result, ns.error = True, judgement.id, error
        self._judged += 1
        self.counts[judgement.id] = self.counts.get(judgement.id, 0) + 1
        self._add_accuracy(judgement.accuracy)
        self.errors.append(error)
        self.score += int(round(judgement.score * self.rules.score_multiplier))
        if judgement.breaks_combo:
            self._break_combo(ns)
        else:
            self._bump_combo()
        self._change_health(judgement.health)
        if ns.is_hold:
            ns.holding = True
            self.active_holds[ns.lane] = ns
            self.bus.emit("hold_start", session=self, note=ns)
        self.bus.emit("judgement", session=self, note=ns, judgement=judgement, error=error)
        for m in self.modifiers:
            m.on_judgement(self, ns, judgement, error)

    def _miss(self, ns: NoteState) -> None:
        ns.judged, ns.result = True, "miss"
        self._judged += 1
        self.counts["miss"] += 1
        self._add_accuracy(0.0)
        if ns.is_hold:  # the tail is lost too
            ns.hold_dropped = True
            self.counts["hold_drop"] += 1
            self._add_accuracy(0.0)
        self._break_combo(ns)
        self._change_health(self.rules.miss.health)
        self.bus.emit("judgement", session=self, note=ns, judgement=self.rules.miss, error=None)
        for m in self.modifiers:
            m.on_judgement(self, ns, self.rules.miss, None)
        if self.rules.sudden_death:
            self._fail()

    def _complete_hold(self, ns: NoteState) -> None:
        ns.hold_done = True
        self.counts["hold_ok"] += 1
        self._add_accuracy(1.0)
        self.score += int(round(self.rules.hold_complete_score * self.rules.score_multiplier))
        self._bump_combo()
        self.bus.emit("hold_complete", session=self, note=ns)

    def _drop_hold(self, ns: NoteState) -> None:
        ns.hold_dropped = True
        self.counts["hold_drop"] += 1
        self._add_accuracy(0.0)
        self._break_combo(ns)
        self._change_health(self.rules.hold_drop_health)
        self.bus.emit("hold_drop", session=self, note=ns)
        if self.rules.sudden_death:
            self._fail()

    def _ghost(self, lane: int, t: float) -> None:
        self.bus.emit("ghost_tap", session=self, lane=lane, time=t)
        if self.rules.anti_spam:
            # A stray press costs the next note coming down this lane: mashing never pays.
            ns = self.next_note(lane)
            if ns is not None and ns.time - t <= self.rules.anti_spam_horizon:
                self._miss(ns)
                self.bus.emit("spam_penalty", session=self, note=ns, lane=lane)
        if not self.rules.ghost_tapping:
            self._break_combo(None)
            self._change_health(self.rules.ghost_tap_health)

    def _bump_combo(self) -> None:
        self.combo += 1
        self.max_combo = max(self.max_combo, self.combo)
        if self.combo % 50 == 0:
            self.bus.emit("combo_milestone", session=self, combo=self.combo)

    def _break_combo(self, ns: NoteState | None) -> None:
        for m in self.modifiers:
            if m.prevent_combo_break(self, ns):
                self.bus.emit("combo_shielded", session=self, note=ns, modifier=m)
                return
        if self.combo > 0:
            self.bus.emit("combo_break", session=self, combo=self.combo)
        self.combo_breaks += 1
        self.combo = 0

    def _change_health(self, delta: float) -> None:
        self.health = min(self.rules.health_max, max(0.0, self.health + self.rules.health_delta(delta)))
        if self.health <= 0.0:
            self._fail()

    def _fail(self) -> None:
        if self.rules.no_fail or self.failed:
            return
        self.failed = True
        self.bus.emit("fail", session=self)

    def heal(self, amount: float) -> None:
        """For modifiers/items."""
        self.health = min(self.rules.health_max, max(0.0, self.health + amount))

    # ------------------------------------------------------------ results
    def summary(self) -> dict:
        errs = np.array(self.errors) * 1000.0
        grade, _ = self.rules.grade_for(self.accuracy)
        return {
            "score": int(self.score),
            "accuracy": round(float(self.accuracy), 5),
            "grade": "F" if self.failed else grade,
            "max_combo": int(self.max_combo),
            "full_combo": self.full_combo and self._acc_n > 0,
            "counts": dict(self.counts),
            "failed": self.failed,
            "notes": len(self.notes),
            "mean_offset_ms": round(float(errs.mean()), 2) if len(errs) else 0.0,
            "std_offset_ms": round(float(errs.std()), 2) if len(errs) else 0.0,
            "modifiers": [m.id for m in self.modifiers],
        }
