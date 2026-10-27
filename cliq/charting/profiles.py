"""Difficulty profiles for the auto-charter (loaded from ``data/difficulties.json``)."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from functools import lru_cache

from .. import paths
from ..util import load_json


@dataclass
class DifficultyProfile:
    id: str
    label: str = ""
    color: str = "#FFFFFF"
    order: int = 0
    divisions: list[int] = field(default_factory=lambda: [1, 2])
    triplets: bool = False
    nps: float = 2.5                 # target notes/second in the loudest sections
    min_gap_beats: float = 0.5       # minimum spacing between notes (beats)...
    min_gap_s: float = 0.2           # ...and (seconds)
    pulse: float = 0.4               # keep a steady beat in busy sections even without clear onsets
    strength_floor: float = 0.15     # ignore onsets weaker than this fraction of the song's strong ones
    min_score: float = 0.3           # minimum salience for a grid slot to become a note
    max_chord: int = 2
    chord_threshold: float = 1.5
    chord3_threshold: float = 99.0
    chord_min_gap_beats: float = 4.0
    hold_min_beats: float = 1.5
    hold_ratio: float = 0.3
    hold_sustain: float = 0.45
    hold_release_beats: float = 0.5
    jack_gap_s: float = 0.4          # minimum time between two notes in one lane

    def with_overrides(self, **overrides) -> "DifficultyProfile":
        known = {f.name for f in dataclasses.fields(self)}
        return dataclasses.replace(self, **{k: v for k, v in overrides.items() if k in known})


@lru_cache(maxsize=1)
def load_profiles() -> dict[str, DifficultyProfile]:
    raw = load_json(paths.DATA_DIR / "difficulties.json", {}) or {}
    known = {f.name for f in dataclasses.fields(DifficultyProfile)}
    out: dict[str, DifficultyProfile] = {}
    for key, values in raw.items():
        if key.startswith("_") or not isinstance(values, dict):
            continue
        out[key] = DifficultyProfile(id=key, **{k: v for k, v in values.items() if k in known})
        if not out[key].label:
            out[key].label = key.title()
    if not out:
        out["normal"] = DifficultyProfile(id="normal", label="Normal")
    return dict(sorted(out.items(), key=lambda kv: kv[1].order))


def get_profile(name: str) -> DifficultyProfile:
    profiles = load_profiles()
    return profiles.get(name) or profiles.get("normal") or next(iter(profiles.values()))


def difficulty_ids() -> list[str]:
    return list(load_profiles().keys())
