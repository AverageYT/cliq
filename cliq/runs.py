"""Runs: several songs played back to back, with state that carries between them.

A :class:`Run` is the thing a GameplayScene/ResultsScene pair belongs to when
you are not just playing one song. Phase one has :class:`PlaylistRun` (play a
playlist in order or shuffled). The roguelike will subclass :class:`Run` and
use its hooks:

* ``state``          - free-form dict that lives for the whole run (items,
                       upgrades, currency, carried-over health...)
* ``bus``            - run-wide events: ``run_start``, ``stage_start``,
                       ``stage_end``, ``run_end``
* ``modifiers_for``  - which modifiers a stage is played with
* ``on_stage_end``   - decide what happens after a song (reward screens,
                       ending the run on a fail, inserting stages...)
* ``stages``         - a plain list, so a run can grow or branch as it goes
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .events import EventBus


@dataclass
class Stage:
    song_id: str
    mode: str = "keys"
    difficulty: str = "normal"
    modifiers: list[str] = field(default_factory=list)
    result: dict | None = None
    skipped: str | None = None          # why a stage could not be played (e.g. song deleted)


class Run:
    kind = "run"
    continue_on_fail = True             # a fail ends the run when False (roguelike style)

    def __init__(self, name: str, stages: list[Stage], modifiers=(), seed: int | None = None):
        self.name = name
        self.stages = list(stages)
        self.modifiers = list(modifiers)
        self.seed = random.randrange(1 << 30) if seed is None else seed
        self.index = 0
        self.state: dict = {}
        self.bus = EventBus()
        self.ended = False

    # ------------------------------------------------------------ progress
    @property
    def current(self) -> Stage | None:
        return self.stages[self.index] if 0 <= self.index < len(self.stages) else None

    @property
    def finished(self) -> bool:
        return self.ended or self.index >= len(self.stages)

    @property
    def position(self) -> tuple[int, int]:
        """(1-based number of the current stage, total stages)."""
        return min(self.index + 1, len(self.stages)), len(self.stages)

    def modifiers_for(self, stage: Stage) -> list[str]:
        mods = list(self.modifiers)
        mods += [m for m in stage.modifiers if m not in mods]
        return mods

    def start_stage(self) -> None:
        if self.index == 0 and not any(s.result for s in self.stages):
            self.bus.emit("run_start", run=self)
        self.bus.emit("stage_start", run=self, stage=self.current)

    def record(self, summary: dict) -> None:
        """Store the result of the current stage (a retry overwrites it)."""
        stage = self.current
        if stage is None:
            return
        stage.result = dict(summary)
        self.bus.emit("stage_end", run=self, stage=stage, summary=summary)

    def on_stage_end(self, stage: Stage) -> None:
        if stage.result and stage.result.get("failed") and not self.continue_on_fail:
            self.end()

    def advance(self) -> bool:
        """Move to the next stage. False when the run is over."""
        stage = self.current
        if stage is not None:
            self.on_stage_end(stage)
        if self.ended:
            return False
        self.index += 1
        if self.finished:
            self.end()
            return False
        return True

    def skip(self, reason: str) -> None:
        if self.current is not None:
            self.current.skipped = reason

    def end(self) -> None:
        if not self.ended:
            self.ended = True
            self.bus.emit("run_end", run=self)

    # ------------------------------------------------------------ results
    def totals(self) -> dict:
        played = [s.result for s in self.stages if s.result]
        if not played:
            return {"played": 0, "cleared": 0, "score": 0, "accuracy": 0.0, "full_combos": 0, "misses": 0}
        return {
            "played": len(played),
            "cleared": sum(1 for r in played if not r.get("failed")),
            "score": sum(int(r.get("score", 0)) for r in played),
            "accuracy": sum(float(r.get("accuracy", 0.0)) for r in played) / len(played),
            "full_combos": sum(1 for r in played if r.get("full_combo")),
            "misses": sum(int(r.get("counts", {}).get("miss", 0)) for r in played),
        }


class PlaylistRun(Run):
    kind = "playlist"

    def __init__(self, name: str, stages: list[Stage], playlist_id: str | None = None, shuffled: bool = False,
                 modifiers=(), seed: int | None = None):
        super().__init__(name, stages, modifiers, seed)
        self.playlist_id = playlist_id
        self.shuffled = shuffled
        if shuffled:
            random.Random(self.seed).shuffle(self.stages)

    @classmethod
    def from_playlist(cls, playlist, shuffle: bool = False, modifiers=(), seed: int | None = None) -> "PlaylistRun":
        stages = [Stage(e.song_id, e.mode, e.difficulty, list(e.modifiers)) for e in playlist.entries]
        return cls(playlist.name, stages, playlist.id, shuffle, modifiers, seed)

    def again(self) -> "PlaylistRun":
        """A fresh run over the same songs (reshuffled if this one was shuffled)."""
        stages = [Stage(s.song_id, s.mode, s.difficulty, list(s.modifiers)) for s in self.stages]
        return PlaylistRun(self.name, stages, self.playlist_id, self.shuffled, self.modifiers)
