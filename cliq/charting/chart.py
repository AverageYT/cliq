"""Chart data model and file format.

A chart file (``songs/<id>/charts/<difficulty>.json``) looks like::

    {
      "format": "cliq-chart", "version": 1,
      "lanes": 4, "difficulty": "hard",
      "meta": {"generator": "auto", ...},
      "notes": [[12.345, 2], [13.0, 1, 0.5], [14.0, 3, 0, "mine"]]
    }

Each note is ``[time_seconds, lane, hold_duration?, kind?]``. Dict notes
(``{"t": .., "l": .., "d": .., "k": ..}``) are accepted too. ``kind`` is
"tap" by default; game modes add their own (taiko "big"/"roll", shield
"reverse", path "critical"/"mash"). ``mode`` says which game mode the chart is
for ("keys" when missing).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..util import load_json, save_json

CHART_FORMAT = "cliq-chart"
CHART_VERSION = 1


@dataclass
class Note:
    time: float
    lane: int
    duration: float = 0.0
    kind: str = "tap"

    @property
    def end(self) -> float:
        return self.time + self.duration

    @property
    def is_hold(self) -> bool:
        return self.duration > 0.0

    def to_json(self) -> list:
        out: list = [round(self.time, 4), int(self.lane)]
        if self.duration > 0 or self.kind != "tap":
            out.append(round(self.duration, 4))
        if self.kind != "tap":
            out.append(self.kind)
        return out

    @classmethod
    def from_json(cls, raw) -> "Note":
        if isinstance(raw, dict):
            return cls(float(raw["t"]), int(raw["l"]), float(raw.get("d", 0.0)), str(raw.get("k", "tap")))
        time, lane = float(raw[0]), int(raw[1])
        duration = float(raw[2]) if len(raw) > 2 else 0.0
        kind = str(raw[3]) if len(raw) > 3 else "tap"
        return cls(time, lane, max(0.0, duration), kind)


@dataclass
class Chart:
    lanes: int = 4
    difficulty: str = "normal"
    notes: list[Note] = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    mode: str = "keys"            # which game mode plays this chart (see cliq/modes)

    def sort(self) -> "Chart":
        self.notes.sort(key=lambda n: (n.time, n.lane))
        return self

    def copy(self) -> "Chart":
        return copy.deepcopy(self)

    @property
    def end_time(self) -> float:
        return max((n.end for n in self.notes), default=0.0)

    @property
    def start_time(self) -> float:
        return min((n.time for n in self.notes), default=0.0)

    def stats(self) -> dict:
        """Density numbers shown in song select (notes per second etc.)."""
        if not self.notes:
            return {"notes": 0, "holds": 0, "nps": 0.0, "peak_nps": 0.0, "rating": 0.0}
        times = np.array(sorted(n.time for n in self.notes))
        span = max(1.0, times[-1] - times[0])
        nps = len(times) / span
        # peak density over 4-second windows
        right = np.searchsorted(times, times + 4.0)
        peak = float(np.max(right - np.arange(len(times)))) / 4.0
        holds = sum(1 for n in self.notes if n.is_hold)
        rating = round(float(0.75 * nps + 0.35 * peak + 0.25 * (self.lanes - 4)), 1)
        return {"notes": len(times), "holds": holds, "nps": round(float(nps), 2), "peak_nps": round(peak, 2),
                "rating": rating}

    # ------------------------------------------------------------ io
    def to_json(self) -> dict:
        self.sort()
        return {"format": CHART_FORMAT, "version": CHART_VERSION, "mode": self.mode, "lanes": self.lanes,
                "difficulty": self.difficulty, "meta": self.meta,
                "notes": [n.to_json() for n in self.notes]}

    @classmethod
    def from_json(cls, data: dict) -> "Chart":
        lanes = int(data.get("lanes", 4))
        notes = []
        for raw in data.get("notes", []):
            try:
                note = Note.from_json(raw)
            except (KeyError, IndexError, TypeError, ValueError):
                continue
            if 0 <= note.lane < lanes:
                notes.append(note)
        return cls(lanes=lanes, difficulty=str(data.get("difficulty", "normal")), notes=notes,
                   meta=dict(data.get("meta", {})), mode=str(data.get("mode", "keys"))).sort()

    def save(self, path: Path) -> None:
        save_json(path, self.to_json(), indent=None)

    @classmethod
    def load(cls, path: Path) -> "Chart | None":
        data = load_json(path)
        if not isinstance(data, dict):
            return None
        return cls.from_json(data)
