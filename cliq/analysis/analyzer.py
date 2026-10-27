"""High-level song analysis: audio in, beat grid + onset table out.

The result is cached next to the song (``analysis.npz``) so charts can be
regenerated for any difficulty instantly, and future game modes (shield mode,
taiko mode, ...) can build their own patterns from the same musical data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import features as F
from .tempo import fit_grid

ANALYSIS_VERSION = 1


@dataclass
class SongAnalysis:
    duration: float
    bpm: float
    offset: float
    downbeat: int
    confidence: float
    onsets: F.Onsets
    fps: float
    env: np.ndarray            # onset strength envelope (feature fps)
    rms: np.ndarray            # loudness envelope (feature fps)
    beat_times: np.ndarray | None = None
    residual_ms: float = 0.0
    notes: list[str] = field(default_factory=list)
    version: int = ANALYSIS_VERSION

    # ------------------------------------------------------------ helpers
    def grid(self):
        from ..charting.beatgrid import BeatGrid

        return BeatGrid(bpm=self.bpm, offset=self.offset, beat_times=self.beat_times, downbeat=self.downbeat)

    def rms_at(self, t: float | np.ndarray) -> np.ndarray:
        idx = np.clip((np.asarray(t) * self.fps).astype(int), 0, len(self.rms) - 1)
        return self.rms[idx]

    def summary(self) -> dict:
        return {
            "bpm": round(float(self.bpm), 4),
            "offset": round(float(self.offset), 5),
            "downbeat": int(self.downbeat),
            "beats": None if self.beat_times is None else [round(float(b), 5) for b in self.beat_times],
            "confidence": round(float(self.confidence), 3),
            "variable_tempo": self.beat_times is not None,
        }

    # ------------------------------------------------------------ io
    def save(self, path: Path) -> None:
        arrays = {
            "env": self.env.astype(np.float32),
            "rms": self.rms.astype(np.float32),
            "meta": np.array([self.version, self.duration, self.bpm, self.offset, self.downbeat,
                              self.confidence, self.fps, self.residual_ms], dtype=np.float64),
            "beat_times": self.beat_times if self.beat_times is not None else np.zeros(0),
            **self.onsets.to_dict(),
        }
        tmp = Path(path).with_suffix(".tmp.npz")
        np.savez_compressed(tmp, **arrays)
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> "SongAnalysis | None":
        try:
            with np.load(path) as d:
                meta = d["meta"]
                if int(meta[0]) != ANALYSIS_VERSION:
                    return None
                beats = d["beat_times"]
                return cls(duration=float(meta[1]), bpm=float(meta[2]), offset=float(meta[3]),
                           downbeat=int(meta[4]), confidence=float(meta[5]), fps=float(meta[6]),
                           residual_ms=float(meta[7]), env=d["env"].copy(), rms=d["rms"].copy(),
                           beat_times=beats.copy() if len(beats) else None,
                           onsets=F.Onsets.from_dict(d))
        except (OSError, KeyError, ValueError):
            return None


def analyze_signal(y: np.ndarray, sr: int = F.SR, progress=None) -> SongAnalysis:
    """Analyse a mono float signal sampled at ``sr`` (use 22050 Hz)."""
    def stage(lo: float, hi: float):
        return (lambda f: progress(lo + (hi - lo) * f)) if progress else None

    feat = F.compute_features(y, sr, progress=stage(0.0, 0.6))
    onsets = F.detect_onsets(feat, y, sr)
    if progress:
        progress(0.75)
    fit = fit_grid(feat, onsets)
    if progress:
        progress(1.0)
    return SongAnalysis(duration=feat.duration, bpm=fit.bpm, offset=fit.offset, downbeat=fit.downbeat,
                        confidence=fit.confidence, onsets=onsets, fps=feat.fps, env=feat.env, rms=feat.rms,
                        beat_times=fit.beat_times, residual_ms=fit.residual_ms, notes=fit.notes)


def analyze_file(path: str | Path, progress=None) -> SongAnalysis:
    from ..audio.ffmpeg import decode_mono

    y = decode_mono(path, F.SR)
    return analyze_signal(y, F.SR, progress=progress)
