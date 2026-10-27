"""Tempo (BPM), beat grid and downbeat estimation.

Pipeline
--------
1. ``estimate_tempo``: autocorrelation of the onset envelope with a log-normal
   tempo prior gives a coarse BPM.
2. ``fit_constant_grid``: treats every onset as a point on a circle whose
   circumference is one beat, and searches the BPM that makes the onsets line
   up best across the *whole song* (phase concentration at the beat, 8th and
   16th levels). Long songs make this extremely precise (~0.01 BPM).
3. ``grid_residuals``: checks whether the constant grid stays in sync in every
   part of the song. If not (live drummers, tempo changes), we fall back to
   ``track_beats_dp`` - a dynamic-programming beat tracker (Ellis 2007) - and
   use its smoothed beats as a variable grid.
4. ``estimate_downbeat``: kick-on-1, snare-on-2-and-4 and section-start
   heuristics pick which beat starts each measure.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .features import Features, Onsets, _moving_average

BPM_RANGE = (78.0, 185.0)   # charts feel best in this range; octave errors are folded into it


@dataclass
class GridFit:
    bpm: float
    offset: float                     # time of a beat, within [0, 60/bpm)
    confidence: float                 # 0..1, how tightly onsets line up with the grid
    beat_times: np.ndarray | None = None   # explicit beats when the tempo varies
    downbeat: int = 0                 # beat index (mod 4) that starts a measure
    residual_ms: float = 0.0          # worst local drift of the constant grid
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- coarse tempo
def estimate_tempo(feat: Features, prior_bpm: float = 120.0, prior_octaves: float = 1.0,
                   min_bpm: float = 50.0, max_bpm: float = 230.0) -> float:
    fps = feat.fps
    x = feat.env.astype(np.float64)
    trend = _moving_average(x, int(fps * 0.4), int(fps * 0.4))
    x = np.maximum(x - trend, 0.0)
    if not np.any(x):
        return prior_bpm
    lag_min = max(1, int(np.floor(60.0 * fps / max_bpm)))
    lag_max = int(np.ceil(60.0 * fps / min_bpm))
    nfft = 1 << int(np.ceil(np.log2(2 * len(x) + 1)))
    spec = np.fft.rfft(x, nfft)
    acf = np.fft.irfft(spec * np.conj(spec), nfft)[: 4 * lag_max + 2]
    acf /= acf[0] + 1e-12
    lags = np.arange(lag_min, lag_max + 1)
    enhanced = acf[lags] + 0.5 * acf[2 * lags] + 0.25 * acf[4 * lags]
    bpms = 60.0 * fps / lags
    prior = np.exp(-0.5 * (np.log2(bpms / prior_bpm) / prior_octaves) ** 2)
    score = enhanced * prior
    i = int(np.argmax(score))
    lag = float(lags[i])
    if 0 < i < len(score) - 1:
        a, b, c = score[i - 1], score[i], score[i + 1]
        denom = a - 2 * b + c
        if denom < 0:
            lag += float(np.clip(0.5 * (a - c) / denom, -0.5, 0.5))
    return 60.0 * fps / lag


def fold_bpm(bpm: float, lo: float = BPM_RANGE[0], hi: float = BPM_RANGE[1]) -> float:
    """Double or halve until the BPM lands in the comfortable charting range."""
    if bpm <= 0:
        return 120.0
    while bpm < lo:
        bpm *= 2.0
    while bpm >= hi:
        bpm /= 2.0
    return bpm


# --------------------------------------------------------------------------- constant grid
def _phase_scores(times: np.ndarray, weights: np.ndarray, bpms: np.ndarray) -> np.ndarray:
    """Weighted phase concentration at beat, 8th and 16th level for each BPM."""
    out = np.empty(len(bpms))
    total = weights.sum() + 1e-12
    for s in range(0, len(bpms), 64):
        f = bpms[s:s + 64] / 60.0
        z = np.exp(2j * np.pi * np.outer(times, f))        # (events, candidates)
        s1 = np.abs(weights @ z)
        z2 = z * z
        s2 = np.abs(weights @ z2)
        s4 = np.abs(weights @ (z2 * z2))
        out[s:s + 64] = (s1 + s2 + 0.5 * s4) / (2.5 * total)
    return out


def _best(bpms: np.ndarray, scores: np.ndarray) -> float:
    i = int(np.argmax(scores))
    if 0 < i < len(scores) - 1:
        a, b, c = scores[i - 1], scores[i], scores[i + 1]
        denom = a - 2 * b + c
        if denom < 0:
            return float(bpms[i] + np.clip(0.5 * (a - c) / denom, -0.5, 0.5) * (bpms[1] - bpms[0]))
    return float(bpms[i])


def _circ_dist(a: float, b: float, period: float) -> float:
    d = (a - b) % period
    return min(d, period - d)


def fit_constant_grid(onsets: Onsets, bpm_guess: float, search: float = 0.045) -> GridFit:
    times = onsets.times
    if len(times) < 8:
        return GridFit(bpm=bpm_guess, offset=0.0, confidence=0.0, notes=["too few onsets"])
    w = onsets.strength ** 1.5
    lo, hi = bpm_guess * (1 - search), bpm_guess * (1 + search)
    coarse = np.arange(lo, hi, 0.02)
    best = _best(coarse, _phase_scores(times, w, coarse))
    fine = np.arange(best - 0.04, best + 0.04, 0.001)
    bpm = _best(fine, _phase_scores(times, w, fine))
    period = 60.0 / bpm

    # 8th-note grid phase from both on- and off-beats (most robust estimate)...
    z2 = np.sum(w * np.exp(2j * np.pi * 2 * times / period))
    t8 = (np.angle(z2) / (4 * np.pi)) * period
    # ...then decide whether the beat sits on that grid or half a beat later,
    # using kick + snare energy (they live on the beat; hats often don't).
    wb = (onsets.low + onsets.mid) * onsets.strength
    zb = np.sum(wb * np.exp(2j * np.pi * times / period))
    tb = (np.angle(zb) / (2 * np.pi)) * period
    cands = [t8 % period, (t8 + period / 2) % period]
    offset = min(cands, key=lambda c: _circ_dist(c, tb, period))
    confidence = float(np.abs(z2) / (w.sum() + 1e-12))
    return GridFit(bpm=bpm, offset=float(offset % period), confidence=confidence)


def grid_residuals(onsets: Onsets, bpm: float, offset: float, window: float = 12.0,
                   hop: float = 6.0) -> list[tuple[float, float, float]]:
    """Local (start_time, drift_seconds, concentration) of the onsets vs. a constant grid."""
    period = 60.0 / bpm
    times, w = onsets.times, onsets.strength ** 1.5
    if len(times) == 0:
        return []
    out = []
    start = max(0.0, times[0] - 1.0)
    while start < times[-1]:
        m = (times >= start) & (times < start + window)
        if m.sum() >= 8:
            z = np.sum(w[m] * np.exp(2j * np.pi * 2 * (times[m] - offset) / period))
            conc = float(np.abs(z) / (w[m].sum() + 1e-12))
            drift = float(np.angle(z) / (4 * np.pi) * period)
            out.append((start, drift, conc))
        start += hop
    return out


# --------------------------------------------------------------------------- dynamic beats
def track_beats_dp(feat: Features, bpm: float, tightness: float = 120.0) -> np.ndarray:
    """Ellis-style DP beat tracker. Returns beat times in seconds."""
    fps = feat.fps
    env = feat.env.astype(np.float64)
    env = env / (env.std() + 1e-9)
    period = 60.0 * fps / bpm
    n = len(env)
    sigma = max(1.0, period / 32.0)
    k = np.arange(-int(4 * sigma), int(4 * sigma) + 1)
    local = np.convolve(env, np.exp(-0.5 * (k / sigma) ** 2), mode="same")

    offsets = np.arange(-int(round(2 * period)), -int(round(period / 2)) + 1)   # negative
    txcost = -tightness * np.log(-offsets / period) ** 2
    cum = local.copy()
    back = np.full(n, -1, dtype=np.int64)
    block = max(1, int(round(period / 2)))
    for s in range(0, n, block):
        idx = np.arange(s, min(n, s + block))
        cand = idx[:, None] + offsets[None, :]
        valid = cand >= 0
        scores = np.where(valid, cum[np.clip(cand, 0, n - 1)] + txcost[None, :], -np.inf)
        j = np.argmax(scores, axis=1)
        best = scores[np.arange(len(idx)), j]
        ok = np.isfinite(best) & (best > 0)
        cum[idx[ok]] = local[idx[ok]] + best[ok]
        back[idx[ok]] = cand[np.arange(len(idx)), j][ok]

    # last beat: the latest strong local maximum of the cumulative score
    tail = cum[max(0, n - int(2 * period)):]
    i = int(np.argmax(tail)) + max(0, n - int(2 * period))
    beats = []
    while i >= 0:
        beats.append(i)
        i = int(back[i])
    beats = np.asarray(beats[::-1], dtype=np.float64) / fps
    # trim beats in leading/trailing silence
    loud = feat.env > 0.05
    if loud.any():
        first, last = np.flatnonzero(loud)[[0, -1]] / fps
        beats = beats[(beats >= first - period / fps) & (beats <= last + period / fps)]
    return beats


def refine_beats(beats: np.ndarray, onsets: Onsets, max_shift: float = 0.035) -> np.ndarray:
    """Snap beats to nearby onsets, then smooth with a local linear fit."""
    if len(beats) < 4:
        return beats
    snapped = beats.copy()
    if len(onsets):
        idx = np.searchsorted(onsets.times, beats)
        for b, i in enumerate(idx):
            best, best_w = None, 0.0
            for j in (i - 1, i):
                if 0 <= j < len(onsets.times):
                    d = onsets.times[j] - beats[b]
                    if abs(d) <= max_shift and onsets.strength[j] > best_w:
                        best, best_w = onsets.times[j], onsets.strength[j]
            if best is not None:
                snapped[b] = best
    smooth = snapped.copy()
    half = 4
    for b in range(len(snapped)):
        lo, hi = max(0, b - half), min(len(snapped), b + half + 1)
        x = np.arange(lo, hi)
        coef = np.polyfit(x, snapped[lo:hi], 1)
        smooth[b] = coef[0] * b + coef[1]
    return smooth


# --------------------------------------------------------------------------- downbeats
def estimate_downbeat(beat_times: np.ndarray, onsets: Onsets, feat: Features, per_measure: int = 4) -> int:
    """Which beat index (mod ``per_measure``) begins a measure."""
    if len(beat_times) < per_measure * 2:
        return 0
    tol = 0.05
    low_at = np.zeros(len(beat_times))
    mid_at = np.zeros(len(beat_times))
    if len(onsets):
        idx = np.searchsorted(onsets.times, beat_times)
        for b, i in enumerate(idx):
            for j in (i - 1, i):
                if 0 <= j < len(onsets.times) and abs(onsets.times[j] - beat_times[b]) <= tol:
                    low_at[b] = max(low_at[b], onsets.low[j] * onsets.strength[j])
                    mid_at[b] = max(mid_at[b], onsets.mid[j] * onsets.strength[j])
    # loudness jump into each beat (sections start on downbeats)
    fps = feat.fps
    rms = feat.rms.astype(np.float64)
    period = float(np.median(np.diff(beat_times)))
    jump = np.zeros(len(beat_times))
    for b, t in enumerate(beat_times):
        i = int(t * fps)
        w = max(1, int(period * fps))
        before = rms[max(0, i - w):i]
        after = rms[i:i + w]
        if len(before) and len(after):
            # only big jumps (new sections), not beat-to-beat groove variation
            jump[b] = max(0.0, np.log((after.mean() + 1e-4) / (before.mean() + 1e-4)) - 0.4)
    jump = np.minimum(jump, 1.0)

    low_at /= max(1e-9, float(low_at.max()))
    mid_at /= max(1e-9, float(mid_at.max()))

    # Songs usually come in on beat 1: small prior for the first clearly active beat.
    strong = np.flatnonzero((low_at + mid_at) > 0.25 * max(1e-9, float((low_at + mid_at).max())))
    first_active = int(strong[0]) if len(strong) else 0

    scores = []
    for k in range(per_measure):
        def mean_at(arr, phase):
            sel = arr[(np.arange(len(arr)) - phase) % per_measure == 0]
            return float(sel.mean()) if len(sel) else 0.0
        # kick on 1 (and 3), backbeat on 2 and 4, new sections start on 1
        score = (mean_at(low_at, k) + 0.5 * mean_at(low_at, (k + 2) % per_measure)
                 + 0.6 * (mean_at(mid_at, (k + 1) % per_measure) + mean_at(mid_at, (k + 3) % per_measure))
                 + 1.5 * mean_at(jump, k)
                 + (0.15 if (first_active - k) % per_measure == 0 else 0.0))
        scores.append(score)
    return int(np.argmax(scores))


# --------------------------------------------------------------------------- entry point
def fit_grid(feat: Features, onsets: Onsets, max_drift_ms: float = 22.0) -> GridFit:
    coarse = estimate_tempo(feat)
    bpm0 = fold_bpm(coarse)
    fit = fit_constant_grid(onsets, bpm0)
    fit.bpm = fold_bpm(fit.bpm)
    period = 60.0 / fit.bpm
    fit.offset %= period
    fit.notes.append(f"coarse tempo {coarse:.2f} -> {bpm0:.2f}")

    res = grid_residuals(onsets, fit.bpm, fit.offset)
    good = [(t, d) for t, d, c in res if c >= 0.3]
    worst = max((abs(d) for _, d in good), default=0.0)
    fit.residual_ms = worst * 1000.0
    if good and worst * 1000.0 > max_drift_ms:
        beats = refine_beats(track_beats_dp(feat, fit.bpm), onsets)
        if len(beats) >= 8:
            fit.beat_times = beats
            fit.bpm = float(60.0 / np.median(np.diff(beats)))
            fit.offset = float(beats[0])
            fit.notes.append(f"variable tempo (constant grid drifted {worst * 1000:.0f} ms)")

    if fit.beat_times is not None:
        beats_for_downbeat = fit.beat_times
    else:
        start = onsets.times[0] if len(onsets) else 0.0
        end = onsets.times[-1] if len(onsets) else feat.duration
        first = fit.offset + np.ceil((start - fit.offset) / period - 0.5) * period
        beats_for_downbeat = np.arange(first, end + period, period)
    k = estimate_downbeat(beats_for_downbeat, onsets, feat)
    # express the downbeat relative to beat index 0 of the grid
    if fit.beat_times is not None:
        fit.downbeat = k % 4
    else:
        first_index = int(round((beats_for_downbeat[0] - fit.offset) / period))
        fit.downbeat = (first_index + k) % 4
    return fit
