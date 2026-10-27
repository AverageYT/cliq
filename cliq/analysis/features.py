"""Low-level audio features for beat tracking and charting (numpy only).

The core signal is a *log-mel spectral flux* onset envelope: how much louder
each mel band got compared with a few milliseconds earlier. Peaks in it are
note/drum onsets. We also keep per-band envelopes (low = kick/bass, mid =
snare/vocals/instruments, high = hats/cymbals) which the charter uses to decide
which hand plays a note, and which the downbeat finder uses to locate "beat 1".
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

SR = 22050          # analysis sample rate
N_FFT = 1024        # 46 ms window
HOP = 128           # 5.8 ms between frames -> fine timing resolution
N_MELS = 48
FMIN, FMAX = 30.0, 11000.0
FLUX_LAG = 2        # frames between compared spectra (~11.6 ms)
LOW_MAX_HZ = 180.0
MID_MAX_HZ = 2500.0
LOG_GAIN = 1.0
CHUNK = 4096        # frames per FFT batch (bounds memory use on long songs)

# With centred frames the flux peak arrives slightly *before* a sharp attack
# (the window's leading half already sees the new energy). Measured on synthetic
# drums with sample-exact attacks: -6.5..-8.6 ms. Subtracting this keeps beat
# grids unbiased; see tests/test_analysis.py::test_onset_timing_is_unbiased.
ONSET_LATENCY = -0.0072


@dataclass
class Features:
    sr: int
    hop: int
    env: np.ndarray        # full-band onset strength, roughly 0..1
    low: np.ndarray        # per-band onset strength, each roughly 0..1
    mid: np.ndarray
    high: np.ndarray
    rms: np.ndarray        # frame loudness (linear, un-normalised)
    centroid: np.ndarray   # log2(Hz) spectral centroid (brightness)
    duration: float

    @property
    def fps(self) -> float:
        return self.sr / self.hop

    @property
    def n_frames(self) -> int:
        return len(self.env)

    def frame_times(self) -> np.ndarray:
        return np.arange(self.n_frames) / self.fps


@dataclass
class Onsets:
    """Detected onset events (parallel arrays, sorted by time)."""

    times: np.ndarray
    strength: np.ndarray   # full-band strength, ~0..1
    low: np.ndarray
    mid: np.ndarray
    high: np.ndarray
    centroid: np.ndarray   # log2 Hz
    tone: np.ndarray       # dominant pitch (MIDI number) shortly after the onset

    def __len__(self) -> int:
        return len(self.times)

    def to_dict(self) -> dict[str, np.ndarray]:
        return {f"onset_{k}": getattr(self, k) for k in ("times", "strength", "low", "mid", "high", "centroid", "tone")}

    @classmethod
    def from_dict(cls, d) -> "Onsets":
        return cls(**{k: np.asarray(d[f"onset_{k}"], dtype=np.float64)
                      for k in ("times", "strength", "low", "mid", "high", "centroid", "tone")})


# --------------------------------------------------------------------------- spectra
def hz_to_mel(f):
    return 2595.0 * np.log10(1.0 + np.asarray(f) / 700.0)


def mel_to_hz(m):
    return 700.0 * (10.0 ** (np.asarray(m) / 2595.0) - 1.0)


def mel_filterbank(sr: int = SR, n_fft: int = N_FFT, n_mels: int = N_MELS,
                   fmin: float = FMIN, fmax: float = FMAX) -> tuple[np.ndarray, np.ndarray]:
    """Triangular mel filters, each normalised to unit area. Returns (fb, centre_hz)."""
    fftfreqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
    edges = mel_to_hz(np.linspace(hz_to_mel(fmin), hz_to_mel(min(fmax, sr / 2)), n_mels + 2))
    fb = np.zeros((n_mels, len(fftfreqs)), dtype=np.float32)
    for i in range(n_mels):
        lo, c, hi = edges[i], edges[i + 1], edges[i + 2]
        up = (fftfreqs - lo) / max(c - lo, 1e-9)
        down = (hi - fftfreqs) / max(hi - c, 1e-9)
        fb[i] = np.maximum(0.0, np.minimum(up, down))
        if fb[i].sum() <= 0:  # band narrower than one FFT bin
            fb[i, int(np.argmin(np.abs(fftfreqs - c)))] = 1.0
    fb /= fb.sum(axis=1, keepdims=True)
    return fb, edges[1:-1]


def _frames(y: np.ndarray, n_fft: int, hop: int) -> np.ndarray:
    pad = n_fft // 2
    yp = np.pad(y, (pad, pad))
    if len(yp) < n_fft:
        yp = np.pad(yp, (0, n_fft - len(yp)))
    return sliding_window_view(yp, n_fft)[::hop]


def _robust_norm(x: np.ndarray, pct: float = 99.0) -> np.ndarray:
    ref = np.percentile(x, pct) if len(x) else 0.0
    if ref <= 1e-9:
        ref = float(x.max()) if len(x) and x.max() > 0 else 1.0
    return (x / ref).astype(np.float32)


def compute_features(y: np.ndarray, sr: int = SR, progress=None) -> Features:
    """Compute onset envelopes and loudness for a mono signal at ``sr``."""
    y = np.asarray(y, dtype=np.float32)
    peak = float(np.max(np.abs(y))) if len(y) else 0.0
    if peak > 0:
        y = y / peak
    frames = _frames(y, N_FFT, HOP)
    n = frames.shape[0]
    window = np.hanning(N_FFT).astype(np.float32)
    fb, centers = mel_filterbank(sr)
    mel = np.empty((n, N_MELS), dtype=np.float32)
    rms = np.empty(n, dtype=np.float32)
    for start in range(0, n, CHUNK):
        block = np.asarray(frames[start:start + CHUNK], dtype=np.float32)
        rms[start:start + len(block)] = np.sqrt(np.mean(block * block, axis=1))
        spec = np.abs(np.fft.rfft(block * window, axis=1)).astype(np.float32)
        mel[start:start + len(block)] = spec @ fb.T
        if progress:
            progress(min(1.0, (start + CHUNK) / n))

    logmel = np.log1p(LOG_GAIN * mel)
    # SuperFlux-style reference: max over neighbouring bands suppresses vibrato.
    ref = logmel.copy()
    ref[:, 1:-1] = np.maximum(np.maximum(logmel[:, :-2], logmel[:, 1:-1]), logmel[:, 2:])
    flux = np.zeros_like(logmel)
    flux[FLUX_LAG:] = np.maximum(0.0, logmel[FLUX_LAG:] - ref[:-FLUX_LAG])

    low_mask = centers < LOW_MAX_HZ
    mid_mask = (centers >= LOW_MAX_HZ) & (centers < MID_MAX_HZ)
    high_mask = centers >= MID_MAX_HZ
    env = _robust_norm(flux.mean(axis=1))
    low = _robust_norm(flux[:, low_mask].mean(axis=1))
    mid = _robust_norm(flux[:, mid_mask].mean(axis=1))
    high = _robust_norm(flux[:, high_mask].mean(axis=1))

    weights = mel + 1e-9
    centroid = (weights * np.log2(centers)[None, :]).sum(axis=1) / weights.sum(axis=1)
    return Features(sr=sr, hop=HOP, env=env, low=low, mid=mid, high=high, rms=rms,
                    centroid=centroid.astype(np.float32), duration=len(y) / sr)


# --------------------------------------------------------------------------- peaks
def _moving_average(x: np.ndarray, before: int, after: int) -> np.ndarray:
    c = np.concatenate([[0.0], np.cumsum(np.pad(x.astype(np.float64), (before, after), mode="edge"))])
    w = before + after + 1
    return (c[w:] - c[:-w]) / w


def _moving_max(x: np.ndarray, before: int, after: int) -> np.ndarray:
    padded = np.pad(x, (before, after), mode="constant", constant_values=-np.inf)
    return sliding_window_view(padded, before + after + 1).max(axis=1)


def pick_peaks(env: np.ndarray, fps: float, delta: float = 0.035, wait: float = 0.028,
               max_window: float = 0.03, avg_before: float = 0.10, avg_after: float = 0.07) -> np.ndarray:
    """Indices of local maxima that stand out from their surroundings."""
    if len(env) < 3:
        return np.zeros(0, dtype=np.int64)
    mw = max(1, int(round(max_window * fps)))
    mov_max = _moving_max(env, mw, mw)
    mov_avg = _moving_average(env, int(round(avg_before * fps)), int(round(avg_after * fps)))
    cand = np.flatnonzero((env >= mov_max) & (env > mov_avg + delta))
    if len(cand) == 0:
        return cand
    # Within `wait`, keep only the strongest peak.
    min_gap = max(1, int(round(wait * fps)))
    keep: list[int] = []
    for idx in cand:
        if keep and idx - keep[-1] < min_gap:
            if env[idx] > env[keep[-1]]:
                keep[-1] = idx
            continue
        keep.append(int(idx))
    return np.asarray(keep, dtype=np.int64)


def refine_peak_times(env: np.ndarray, peaks: np.ndarray, fps: float) -> np.ndarray:
    """Sub-frame peak times via parabolic interpolation."""
    idx = np.clip(peaks, 1, len(env) - 2)
    a, b, c = env[idx - 1], env[idx], env[idx + 1]
    denom = a - 2 * b + c
    with np.errstate(divide="ignore", invalid="ignore"):
        off = np.where(denom < 0, 0.5 * (a - c) / denom, 0.0)
    off = np.clip(np.nan_to_num(off), -0.5, 0.5)
    return (peaks + off) / fps


def _band_value(band: np.ndarray, peaks: np.ndarray, reach: int = 2) -> np.ndarray:
    out = np.zeros(len(peaks), dtype=np.float32)
    for k in range(-reach, reach + 1):
        out = np.maximum(out, band[np.clip(peaks + k, 0, len(band) - 1)])
    return out


# --------------------------------------------------------------------------- pitch
TONE_FFT = 4096
TONE_MIDI = np.arange(48.0, 88.0, 1.0 / 3.0)  # ~130 Hz .. 1.3 kHz candidate fundamentals


def estimate_tones(y: np.ndarray, sr: int, times: np.ndarray, delay: float = 0.025) -> np.ndarray:
    """Rough dominant pitch (MIDI) just after each onset via a harmonic sum."""
    if len(times) == 0:
        return np.zeros(0)
    window = np.hanning(TONE_FFT).astype(np.float32)
    df = sr / TONE_FFT
    f0 = 440.0 * 2.0 ** ((TONE_MIDI - 69.0) / 12.0)
    harmonics = np.arange(1, 5)
    bins = np.clip(np.round(f0[:, None] * harmonics[None, :] / df).astype(int), 0, TONE_FFT // 2)
    hw = 0.8 ** (harmonics - 1)
    starts = np.clip(((times + delay) * sr).astype(int), 0, max(0, len(y) - 1))
    yp = np.pad(np.asarray(y, dtype=np.float32), (0, TONE_FFT))
    out = np.empty(len(times))
    for s in range(0, len(times), 512):
        st = starts[s:s + 512]
        seg = np.stack([yp[i:i + TONE_FFT] for i in st]) * window
        mag = np.log1p(np.abs(np.fft.rfft(seg, axis=1)))
        sal = (mag[:, bins] * hw).sum(axis=2)
        out[s:s + 512] = TONE_MIDI[np.argmax(sal, axis=1)]
    return out


def detect_onsets(feat: Features, y: np.ndarray | None = None, sr: int = SR) -> Onsets:
    peaks = pick_peaks(feat.env, feat.fps)
    times = refine_peak_times(feat.env, peaks, feat.fps) - ONSET_LATENCY
    tone = estimate_tones(y, sr, times) if y is not None else np.zeros(len(times))
    return Onsets(
        times=times.astype(np.float64),
        strength=_band_value(feat.env, peaks, 0).astype(np.float64),
        low=_band_value(feat.low, peaks).astype(np.float64),
        mid=_band_value(feat.mid, peaks).astype(np.float64),
        high=_band_value(feat.high, peaks).astype(np.float64),
        centroid=feat.centroid[np.clip(peaks + 2, 0, len(feat.centroid) - 1)].astype(np.float64),
        tone=tone.astype(np.float64),
    )
