"""Personal bests and play history (``user/scores.json``)."""

from __future__ import annotations

import time

from .. import paths
from ..util import load_json, save_json


class ScoreBook:
    def __init__(self, path=None):
        self.path = path or paths.SCORES_FILE
        self.data: dict = load_json(self.path, {}) or {}

    @staticmethod
    def key(song_id: str, difficulty: str) -> str:
        return f"{song_id}::{difficulty}"

    def best(self, song_id: str, difficulty: str) -> dict | None:
        return self.data.get(self.key(song_id, difficulty), {}).get("best")

    def record(self, song_id: str, difficulty: str, result: dict) -> bool:
        """Store a play. Returns True when it is a new personal best."""
        entry = self.data.setdefault(self.key(song_id, difficulty), {"plays": 0, "best": None, "history": []})
        entry["plays"] = int(entry.get("plays", 0)) + 1
        stamped = {**result, "time": time.time()}
        history = entry.setdefault("history", [])
        history.append({k: stamped[k] for k in ("score", "accuracy", "mean_offset_ms", "time") if k in stamped})
        del history[:-20]
        best = entry.get("best")
        is_best = best is None or result.get("score", 0) > best.get("score", 0)
        if is_best:
            entry["best"] = stamped
        save_json(self.path, self.data)
        return is_best
