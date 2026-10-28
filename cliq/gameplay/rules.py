"""Judgement windows, scoring, health and grades (loaded from ``data/judgement.json``).

A :class:`Rules` instance is created per play and handed to every active
modifier first, so items can widen windows, scale health, multiply score, etc.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from functools import lru_cache

from .. import paths
from ..util import hex_to_rgb, load_json


@dataclass
class Judgement:
    id: str
    label: str
    window: float          # seconds (+/-)
    score: int
    accuracy: float
    health: float
    breaks_combo: bool
    color: tuple[int, int, int]

    @property
    def is_miss(self) -> bool:
        return self.id == "miss"


@dataclass
class Rules:
    judgements: list[Judgement]
    miss: Judgement
    hold_release_window: float = 0.12
    hold_complete_score: int = 100
    hold_drop_health: float = -0.04
    ghost_tap_health: float = -0.02
    health_start: float = 0.5
    health_max: float = 1.0
    grades: list[tuple[str, float, tuple[int, int, int]]] = field(default_factory=list)

    # knobs for settings and modifiers
    window_scale: float = 1.0
    score_multiplier: float = 1.0
    health_gain_scale: float = 1.0
    health_loss_scale: float = 1.0
    ghost_tapping: bool = True
    anti_spam: bool = True           # a press with no note in range misses the next note in that lane
    anti_spam_horizon: float = 1.0   # ...if that note is within this many seconds (set to the visible range)
    no_fail: bool = False
    sudden_death: bool = False
    autoplay: bool = False
    scroll_speed_scale: float = 1.0

    @property
    def max_window(self) -> float:
        return self.judgements[-1].window * self.window_scale

    def judge(self, error: float) -> Judgement | None:
        """Judgement for a hit ``error`` seconds off (None = outside every window)."""
        e = abs(error)
        for j in self.judgements:
            if e <= j.window * self.window_scale:
                return j
        return None

    def health_delta(self, amount: float) -> float:
        return amount * (self.health_gain_scale if amount > 0 else self.health_loss_scale)

    def grade_for(self, accuracy: float) -> tuple[str, tuple[int, int, int]]:
        for grade, minimum, color in self.grades:
            if accuracy >= minimum:
                return grade, color
        return "D", (255, 80, 100)

    def copy(self) -> "Rules":
        return copy.deepcopy(self)


def _judgement(raw: dict) -> Judgement:
    return Judgement(id=str(raw["id"]), label=str(raw.get("label", raw["id"].upper())),
                     window=float(raw.get("window_ms", 0)) / 1000.0, score=int(raw.get("score", 0)),
                     accuracy=float(raw.get("accuracy", 0.0)), health=float(raw.get("health", 0.0)),
                     breaks_combo=bool(raw.get("breaks_combo", False)),
                     color=hex_to_rgb(raw.get("color", "#FFFFFF")))


@lru_cache(maxsize=1)
def _base_rules() -> Rules:
    raw = load_json(paths.DATA_DIR / "judgement.json", {}) or {}
    judgements = sorted((_judgement(j) for j in raw.get("judgements", [])), key=lambda j: j.window)
    if not judgements:
        judgements = [_judgement({"id": "perfect", "window_ms": 45, "score": 350, "accuracy": 1.0, "health": 0.02}),
                      _judgement({"id": "good", "window_ms": 135, "score": 100, "accuracy": 0.5, "health": 0.0})]
    miss = _judgement({"id": "miss", "breaks_combo": True, "health": -0.06, **raw.get("miss", {})})
    miss.id = "miss"
    hold = raw.get("hold", {})
    health = raw.get("health", {})
    grades = [(g["grade"], float(g["min_accuracy"]), hex_to_rgb(g.get("color", "#FFFFFF")))
              for g in raw.get("grades", [])]
    grades.sort(key=lambda g: -g[1])
    return Rules(judgements=judgements, miss=miss,
                 hold_release_window=float(hold.get("release_window_ms", 120)) / 1000.0,
                 hold_complete_score=int(hold.get("complete_score", 100)),
                 hold_drop_health=float(hold.get("drop_health", -0.04)),
                 ghost_tap_health=float(raw.get("ghost_tap_health", -0.02)),
                 health_start=float(health.get("start", 0.5)), health_max=float(health.get("max", 1.0)),
                 grades=grades)


def load_rules() -> Rules:
    """A fresh, mutable copy of the default rules."""
    return _base_rules().copy()
