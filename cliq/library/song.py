"""Songs on disk.

Each song is a folder in ``songs/``::

    songs/<song-id>/
        song.json        metadata + timing (bpm, offset, beat list, downbeat)
        audio.ogg        playback audio (converted on import)
        analysis.npz     cached beat/onset analysis (re-chart instantly)
        cover.jpg        optional thumbnail
        charts/<difficulty>.json

Charts you make in the mapping editor live in the same ``charts`` folder, so a
song folder is a self-contained, shareable unit.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from .. import paths
from ..charting.beatgrid import BeatGrid
from ..charting.chart import Chart
from ..charting.profiles import load_profiles
from ..util import load_json, save_json, short_hash, slugify

SONG_FORMAT = "cliq-song"


@dataclass
class Song:
    id: str
    folder: Path
    title: str = "Untitled"
    artist: str = "Unknown artist"
    audio: str = "audio.ogg"
    duration: float = 0.0
    grid: BeatGrid = field(default_factory=BeatGrid)
    preview: float = 0.0
    source: dict = field(default_factory=dict)
    cover: str | None = None
    created: float = 0.0
    lanes: int = 4
    extra: dict = field(default_factory=dict)

    # ------------------------------------------------------------ paths
    @property
    def audio_path(self) -> Path:
        return self.folder / self.audio

    @property
    def cover_path(self) -> Path | None:
        return self.folder / self.cover if self.cover else None

    @property
    def charts_dir(self) -> Path:
        return self.folder / "charts"

    @property
    def analysis_path(self) -> Path:
        return self.folder / "analysis.npz"

    def chart_path(self, difficulty: str) -> Path:
        return self.charts_dir / f"{slugify(difficulty, 32)}.json"

    # ------------------------------------------------------------ charts
    def chart_names(self) -> list[str]:
        if not self.charts_dir.exists():
            return []
        order = {k: p.order for k, p in load_profiles().items()}
        names = [p.stem for p in self.charts_dir.glob("*.json")]
        return sorted(names, key=lambda n: (order.get(n, 100), n))

    def load_chart(self, difficulty: str) -> Chart | None:
        return Chart.load(self.chart_path(difficulty))

    def difficulties_for(self, mode_id: str) -> list[str]:
        """Difficulties playable in a mode. Non-keys charts are generated on demand."""
        from ..modes import split_stem

        if mode_id == "keys":
            return [n for n in self.chart_names() if split_stem(n)[0] == "keys"]
        have = [split_stem(n)[1] for n in self.chart_names() if split_stem(n)[0] == mode_id]
        extra = [d for d in load_profiles() if d not in have] if self.analysis_path.exists() else []
        order = {k: p.order for k, p in load_profiles().items()}
        return sorted(set(have) | set(extra), key=lambda d: (order.get(d, 100), d))

    def chart_for(self, mode_id: str, difficulty: str, settings=None, create: bool = True) -> Chart | None:
        """Load the chart for (mode, difficulty), auto-generating and saving it if missing."""
        from ..modes import get_mode

        mode = get_mode(mode_id)
        stem = mode.chart_stem(difficulty)
        chart = self.load_chart(stem)
        if chart is None and create:
            analysis = self.load_analysis()
            if analysis is None:
                return None
            from ..settings import Settings

            chart = mode.generate(analysis, difficulty, self.grid, settings or Settings(),
                                  seed=sum(map(ord, self.id)) % 10007)
            self.save_chart(chart, stem)
        if chart is not None and chart.mode != mode.id and mode.id != "keys":
            chart.mode = mode.id
        return chart

    def save_chart(self, chart: Chart, name: str | None = None) -> None:
        name = name or chart.difficulty
        chart.difficulty = name
        self.charts_dir.mkdir(parents=True, exist_ok=True)
        chart.save(self.chart_path(name))

    def load_analysis(self):
        from ..analysis.analyzer import SongAnalysis

        if not self.analysis_path.exists():
            return None
        return SongAnalysis.load(self.analysis_path)

    # ------------------------------------------------------------ io
    def to_json(self) -> dict:
        return {
            "format": SONG_FORMAT, "version": 1, "id": self.id, "title": self.title, "artist": self.artist,
            "audio": self.audio, "duration": round(self.duration, 3), "timing": self.grid.to_dict(),
            "preview": round(self.preview, 3), "source": self.source, "cover": self.cover,
            "created": self.created, "lanes": self.lanes, **({"extra": self.extra} if self.extra else {}),
        }

    def save(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        save_json(self.folder / "song.json", self.to_json())

    @classmethod
    def load(cls, folder: Path) -> "Song | None":
        data = load_json(folder / "song.json")
        if not isinstance(data, dict):
            return None
        try:
            return cls(id=str(data.get("id") or folder.name), folder=folder,
                       title=str(data.get("title") or folder.name), artist=str(data.get("artist") or ""),
                       audio=str(data.get("audio") or "audio.ogg"), duration=float(data.get("duration") or 0.0),
                       grid=BeatGrid.from_dict(data.get("timing") or {}), preview=float(data.get("preview") or 0.0),
                       source=dict(data.get("source") or {}), cover=data.get("cover"),
                       created=float(data.get("created") or 0.0), lanes=int(data.get("lanes") or 4),
                       extra=dict(data.get("extra") or {}))
        except (TypeError, ValueError):
            return None


class SongLibrary:
    def __init__(self, root: Path | None = None):
        self.root = Path(root or paths.SONGS_DIR)
        self.songs: list[Song] = []

    def scan(self) -> list[Song]:
        self.root.mkdir(parents=True, exist_ok=True)
        songs = []
        for folder in sorted(self.root.iterdir()):
            if folder.is_dir() and (folder / "song.json").exists():
                song = Song.load(folder)
                if song and song.audio_path.exists():
                    songs.append(song)
        songs.sort(key=lambda s: (-s.created, s.title.lower()))
        self.songs = songs
        return songs

    def get(self, song_id: str) -> Song | None:
        for song in self.songs:
            if song.id == song_id:
                return song
        folder = self.root / song_id
        return Song.load(folder) if (folder / "song.json").exists() else None

    def find_by_source(self, key: str) -> Song | None:
        for song in self.scan():
            if song.source.get("key") == key:
                return song
        return None

    def new_id(self, title: str, source_key: str) -> str:
        base = f"{slugify(title, 36)}-{short_hash(source_key)}"
        candidate, i = base, 2
        while (self.root / candidate).exists():
            candidate, i = f"{base}-{i}", i + 1
        return candidate

    def delete(self, song_id: str) -> None:
        folder = (self.root / song_id).resolve()
        if folder.parent == self.root.resolve() and folder.is_dir():
            shutil.rmtree(folder)
        self.songs = [s for s in self.songs if s.id != song_id]


def now() -> float:
    return time.time()
