"""Mapping between song time (seconds) and musical time (beats).

A grid is either *constant* (``bpm`` + ``offset`` = time of beat 0) or
*variable* (an explicit list of beat times, used when the tempo drifts). Beats
before/after an explicit list are extrapolated with the nearest beat length.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass
class BeatGrid:
    bpm: float = 120.0
    offset: float = 0.0
    beat_times: np.ndarray | None = None
    downbeat: int = 0            # beat index (mod beats_per_measure) that starts a measure
    beats_per_measure: int = 4

    def __post_init__(self) -> None:
        if self.beat_times is not None:
            bt = np.asarray(self.beat_times, dtype=np.float64)
            self.beat_times = bt if len(bt) >= 2 else None
        self.bpm = float(self.bpm) if self.bpm and self.bpm > 0 else 120.0

    # ------------------------------------------------------------------ basics
    @property
    def variable(self) -> bool:
        return self.beat_times is not None

    @property
    def period(self) -> float:
        """Average beat length in seconds."""
        return 60.0 / self.bpm

    def time_at(self, beat):
        beat = np.asarray(beat, dtype=np.float64)
        if self.beat_times is None:
            out = self.offset + beat * self.period
        else:
            bt = self.beat_times
            n = len(bt)
            first, last = bt[1] - bt[0], bt[-1] - bt[-2]
            out = np.interp(beat, np.arange(n), bt)
            out = np.where(beat < 0, bt[0] + beat * first, out)
            out = np.where(beat > n - 1, bt[-1] + (beat - (n - 1)) * last, out)
        return float(out) if out.ndim == 0 else out

    def beat_at(self, time):
        time = np.asarray(time, dtype=np.float64)
        if self.beat_times is None:
            out = (time - self.offset) / self.period
        else:
            bt = self.beat_times
            n = len(bt)
            first, last = bt[1] - bt[0], bt[-1] - bt[-2]
            out = np.interp(time, bt, np.arange(n))
            out = np.where(time < bt[0], (time - bt[0]) / first, out)
            out = np.where(time > bt[-1], (n - 1) + (time - bt[-1]) / last, out)
        return float(out) if out.ndim == 0 else out

    def beat_length_at(self, time: float) -> float:
        b = self.beat_at(time)
        return self.time_at(math.floor(b) + 1) - self.time_at(math.floor(b))

    def is_measure_start(self, beat_index: int) -> bool:
        return (beat_index - self.downbeat) % self.beats_per_measure == 0

    # ------------------------------------------------------------------ snapping
    def snap(self, time: float, division: int) -> float:
        """Nearest grid point with ``division`` steps per beat (0 = no snapping)."""
        if division <= 0:
            return time
        b = self.beat_at(time)
        return self.time_at(round(b * division) / division)

    @staticmethod
    def _stepped(position: float, steps: int) -> int:
        # From between two lines, the first step lands on the adjacent line.
        if steps >= 0:
            return math.floor(position + 1e-6) + steps
        return math.ceil(position - 1e-6) + steps

    def step(self, time: float, division: int, steps: int = 1) -> float:
        """Time of the grid line ``steps`` lines away (``division`` lines per beat)."""
        division = max(1, division)
        return self.time_at(self._stepped(self.beat_at(time) * division, steps) / division)

    def measure_step(self, time: float, measures: int = 1) -> float:
        """Time of the measure line ``measures`` measures away."""
        per = self.beats_per_measure
        position = (self.beat_at(time) - self.downbeat) / per
        return self.time_at(self._stepped(position, measures) * per + self.downbeat)

    def lines(self, t0: float, t1: float, division: int = 1):
        """Yield (time, kind) grid lines between t0 and t1. kind: measure | beat | sub."""
        division = max(1, division)
        b0 = math.floor(self.beat_at(t0) * division)
        b1 = math.ceil(self.beat_at(t1) * division)
        for i in range(b0, b1 + 1):
            if i % division == 0:
                beat = i // division
                kind = "measure" if self.is_measure_start(beat) else "beat"
            else:
                kind = "sub"
            yield self.time_at(i / division), kind

    # ------------------------------------------------------------------ edits
    def with_bpm(self, bpm: float, anchor_time: float | None = None) -> "BeatGrid":
        """Change tempo (constant grid), keeping the beat nearest ``anchor_time`` in place."""
        anchor_time = self.offset if anchor_time is None else anchor_time
        anchor_beat = round(self.beat_at(anchor_time))
        anchor = self.time_at(anchor_beat)
        new = BeatGrid(bpm=bpm, offset=0.0, downbeat=self.downbeat, beats_per_measure=self.beats_per_measure)
        new.offset = (anchor - anchor_beat * new.period)
        new.offset, shift = new.offset % new.period, math.floor(new.offset / new.period)
        new.downbeat = (self.downbeat + shift) % self.beats_per_measure
        return new

    def shifted(self, seconds: float) -> "BeatGrid":
        bt = None if self.beat_times is None else self.beat_times + seconds
        return BeatGrid(bpm=self.bpm, offset=self.offset + seconds, beat_times=bt, downbeat=self.downbeat,
                        beats_per_measure=self.beats_per_measure)

    def to_dict(self) -> dict:
        return {
            "bpm": round(self.bpm, 4),
            "offset": round(self.offset, 5),
            "beats": None if self.beat_times is None else [round(float(b), 5) for b in self.beat_times],
            "downbeat": int(self.downbeat),
            "beats_per_measure": int(self.beats_per_measure),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BeatGrid":
        return cls(bpm=float(d.get("bpm", 120.0)), offset=float(d.get("offset", 0.0)),
                   beat_times=d.get("beats"), downbeat=int(d.get("downbeat", 0)),
                   beats_per_measure=int(d.get("beats_per_measure", 4)))

    @classmethod
    def from_taps(cls, taps: list[float], downbeat: int = 0) -> "BeatGrid | None":
        """Fit a constant grid to tap-tempo presses (least squares)."""
        if len(taps) < 4:
            return None
        t = np.asarray(taps, dtype=np.float64)
        idx = np.arange(len(t))
        slope, intercept = np.polyfit(idx, t, 1)
        if slope <= 0:
            return None
        grid = cls(bpm=60.0 / slope, offset=intercept % slope, downbeat=downbeat)
        return grid
