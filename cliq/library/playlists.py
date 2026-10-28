"""Playlists: named lists of songs (with a mode and difficulty each), saved in
``user/playlists.json``.

A playlist is just data; playing one creates a :class:`cliq.runs.PlaylistRun`,
which is where "songs back to back" behaviour lives (and what roguelike runs
will build on).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from .. import paths
from ..util import load_json, save_json

FORMAT = "cliq-playlists"


@dataclass
class PlaylistEntry:
    song_id: str
    mode: str = "keys"
    difficulty: str = "normal"
    modifiers: list[str] = field(default_factory=list)   # per-song extras on top of the run's

    def to_json(self) -> dict:
        data = {"song": self.song_id, "mode": self.mode, "difficulty": self.difficulty}
        if self.modifiers:
            data["modifiers"] = list(self.modifiers)
        return data

    @classmethod
    def from_json(cls, raw: dict) -> "PlaylistEntry | None":
        if not isinstance(raw, dict) or not raw.get("song"):
            return None
        return cls(str(raw["song"]), str(raw.get("mode") or "keys"), str(raw.get("difficulty") or "normal"),
                   [str(m) for m in raw.get("modifiers") or []])


@dataclass
class Playlist:
    id: str
    name: str
    entries: list[PlaylistEntry] = field(default_factory=list)
    shuffle: bool = False                       # remembered choice for the Play button
    created: float = 0.0

    def to_json(self) -> dict:
        return {"id": self.id, "name": self.name, "shuffle": self.shuffle, "created": self.created,
                "entries": [e.to_json() for e in self.entries]}

    @classmethod
    def from_json(cls, raw: dict) -> "Playlist | None":
        if not isinstance(raw, dict) or not raw.get("id"):
            return None
        entries = [e for e in (PlaylistEntry.from_json(x) for x in raw.get("entries") or []) if e]
        return cls(str(raw["id"]), str(raw.get("name") or "Playlist"), entries, bool(raw.get("shuffle")),
                   float(raw.get("created") or 0.0))

    def add(self, song_id: str, mode: str = "keys", difficulty: str = "normal") -> PlaylistEntry:
        entry = PlaylistEntry(song_id, mode, difficulty)
        self.entries.append(entry)
        return entry

    def contains(self, song_id: str, mode: str | None = None, difficulty: str | None = None) -> bool:
        return any(e.song_id == song_id and (mode is None or e.mode == mode)
                   and (difficulty is None or e.difficulty == difficulty) for e in self.entries)

    def move(self, index: int, delta: int) -> int:
        j = index + delta
        if 0 <= index < len(self.entries) and 0 <= j < len(self.entries):
            self.entries[index], self.entries[j] = self.entries[j], self.entries[index]
            return j
        return index


class PlaylistBook:
    def __init__(self, path=None):
        self.path = path or (paths.USER_DIR / "playlists.json")
        self.playlists: list[Playlist] = []
        self.load()

    def load(self) -> None:
        raw = load_json(self.path, {}) or {}
        items = raw.get("playlists", []) if isinstance(raw, dict) else []
        self.playlists = [p for p in (Playlist.from_json(x) for x in items) if p]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        save_json(self.path, {"format": FORMAT, "version": 1, "playlists": [p.to_json() for p in self.playlists]})

    def get(self, playlist_id: str | None) -> Playlist | None:
        return next((p for p in self.playlists if p.id == playlist_id), None)

    def create(self, name: str) -> Playlist:
        names = {p.name for p in self.playlists}
        base, n = name.strip() or "Playlist", 2
        name = base
        while name in names:
            name, n = f"{base} {n}", n + 1
        playlist = Playlist(uuid.uuid4().hex[:10], name, created=time.time())
        self.playlists.append(playlist)
        self.save()
        return playlist

    def delete(self, playlist_id: str) -> None:
        self.playlists = [p for p in self.playlists if p.id != playlist_id]
        self.save()

    def forget_song(self, song_id: str) -> None:
        """Drop a deleted song from every playlist."""
        changed = False
        for p in self.playlists:
            keep = [e for e in p.entries if e.song_id != song_id]
            changed |= len(keep) != len(p.entries)
            p.entries = keep
        if changed:
            self.save()
