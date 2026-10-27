"""Automatic chart generation from a :class:`SongAnalysis`.

How it works
------------
1. **Slots** - every grid position the difficulty allows (beats, 8ths, 16ths,
   triplets) between the first and last onset of the song.
2. **Snap** - each detected onset is attached to its nearest slot, so every note
   lands exactly on the beat grid (this is what keeps charts in sync).
3. **Score** - a slot's salience is its onset strength relative to the
   surrounding music (so quiet verses still get notes), weighted by metrical
   importance (downbeat > beat > 8th > 16th). Busy sections also keep a steady
   pulse on the beat even where onsets are unclear.
4. **Select** - per measure, keep the most salient slots up to a note budget
   (difficulty nps x loudness), never closer than the minimum gap.
5. **Holds** - notes followed by a long gap over a sustained sound become holds.
6. **Lanes** - a cost function picks each lane: follow the melody's pitch
   direction, kick-ish sounds lean left / hat-ish sounds lean right, avoid
   fast same-lane "jacks", alternate hands in streams and keep lanes balanced.
7. **Chords** - very strong accents on beats get extra notes in the other hand.
"""

from __future__ import annotations

import bisect
import math

import numpy as np

from .beatgrid import BeatGrid
from .chart import Chart, Note
from .profiles import DifficultyProfile, get_profile

GENERATOR_VERSION = 1

# level ids: 0 measure start, 1 beat, 2 eighth, 3 sixteenth, 4 triplet, 5 finer
METRIC_WEIGHT = {0: 1.3, 1: 1.15, 2: 0.95, 3: 0.8, 4: 0.72, 5: 0.6}


def _level_of(frac: float) -> int:
    if frac == 0:
        return 1
    if abs(frac - 0.5) < 1e-6:
        return 2
    if abs(frac - 0.25) < 1e-6 or abs(frac - 0.75) < 1e-6:
        return 3
    if abs(frac - 1 / 3) < 1e-6 or abs(frac - 2 / 3) < 1e-6:
        return 4
    return 5


def _moving_mean(x: np.ndarray, half: int) -> np.ndarray:
    c = np.concatenate([[0.0], np.cumsum(np.pad(x, (half, half), mode="edge"))])
    return (c[2 * half + 1:] - c[: -(2 * half + 1)]) / (2 * half + 1)


def _det_noise(*keys: float) -> float:
    """Deterministic pseudo-random number in [0, 1) from musical features."""
    x = 2166136261
    for k in keys:
        x = ((x ^ (int(k * 1000) & 0xFFFFFFFF)) * 16777619) & 0xFFFFFFFF
    return (x % 10007) / 10007.0


class _Loudness:
    def __init__(self, rms: np.ndarray, fps: float):
        self.fps = fps
        smooth = _moving_mean(rms.astype(np.float64), max(1, int(fps * 0.5)))
        self.db = 20 * np.log10(smooth + 1e-5)
        self.ref = float(np.percentile(self.db, 95)) if len(self.db) else 0.0
        self.rms = rms.astype(np.float64)

    def _idx(self, t):
        return np.clip((np.asarray(t) * self.fps).astype(int), 0, len(self.db) - 1)

    def energy(self, t):
        """0.3..1 loudness factor relative to the song's loud parts."""
        return np.clip((self.db[self._idx(t)] - (self.ref - 20.0)) / 20.0, 0.3, 1.0)

    def active(self, t):
        return self.db[self._idx(t)] > self.ref - 32.0

    def sustain_ratio(self, t0: float, t1: float) -> float:
        """How much of the attack's loudness survives through [t0, t1]."""
        i0 = int((t0 + 0.03) * self.fps)
        i1 = int((t0 + 0.12) * self.fps)
        i2 = int(t1 * self.fps)
        if i2 - i1 < 3 or i1 >= len(self.rms):
            return 0.0
        head = float(self.rms[i0:i1].max()) if i1 > i0 else float(self.rms[i0])
        body = float(np.percentile(self.rms[i1:i2], 30))
        return body / (head + 1e-9)


def generate_chart(analysis, difficulty: str | DifficultyProfile = "normal", lanes: int = 4,
                   grid: BeatGrid | None = None, seed: int = 0, **overrides) -> Chart:
    profile = difficulty if isinstance(difficulty, DifficultyProfile) else get_profile(difficulty)
    if overrides:
        profile = profile.with_overrides(**overrides)
    grid = grid or analysis.grid()
    lanes = max(1, int(lanes))
    meta = {"generator": f"auto v{GENERATOR_VERSION}", "profile": profile.id, "seed": seed,
            "bpm": round(grid.bpm, 3)}
    chart = Chart(lanes=lanes, difficulty=profile.id, notes=[], meta=meta)

    ons = analysis.onsets
    if len(ons) == 0:
        return chart
    loud = _Loudness(analysis.rms, analysis.fps)
    strong_mask = ons.strength >= 0.08
    if not strong_mask.any():
        return chart
    active_times = ons.times[strong_mask & loud.active(ons.times)]
    if len(active_times) == 0:
        active_times = ons.times[strong_mask]
    start_t, end_t = float(active_times[0]), float(active_times[-1])
    start_t = max(start_t, 0.15)

    # ------------------------------------------------------------ 1. slots
    fracs = sorted({k / d for d in profile.divisions for k in range(d)} |
                   ({1 / 3, 2 / 3} if profile.triplets else set()))
    b0 = math.floor(grid.beat_at(start_t - 0.1))
    b1 = math.ceil(grid.beat_at(end_t + 0.1))
    beats = np.array([b + f for b in range(b0, b1 + 1) for f in fracs])
    times = np.asarray(grid.time_at(beats), dtype=np.float64)
    keep = (times >= start_t - 0.06) & (times <= end_t + 0.06)
    beats, times = beats[keep], times[keep]
    if len(times) == 0:
        return chart
    levels = np.array([_level_of(round(b - math.floor(b), 6)) for b in beats])
    for i, b in enumerate(beats):
        if levels[i] == 1 and grid.is_measure_start(int(round(b))):
            levels[i] = 0

    # ------------------------------------------------------------ 2. snap onsets
    n = len(times)
    spacing = np.full(n, 1.0)
    if n > 1:
        d = np.diff(times)
        spacing[:-1] = d
        spacing[1:] = np.minimum(spacing[1:], d)
    slot_strength = np.zeros(n)
    slot_onset = np.full(n, -1)
    pos = np.searchsorted(times, ons.times)
    for k, t in enumerate(ons.times):
        best_j, best_d = -1, 1e9
        for j in (pos[k] - 1, pos[k]):
            if 0 <= j < n and abs(times[j] - t) < best_d:
                best_j, best_d = j, abs(times[j] - t)
        if best_j < 0 or best_d > min(0.06, 0.45 * spacing[best_j]):
            continue
        if ons.strength[k] > slot_strength[best_j]:
            slot_strength[best_j] = ons.strength[k]
            slot_onset[best_j] = k

    # ------------------------------------------------------------ 3. salience
    strong = ons.strength[strong_mask]
    global_ref = float(np.percentile(strong, 90)) if len(strong) else 1.0
    seconds = np.arange(0.0, analysis.duration + 1.0, 1.0)
    local_ref = np.empty(len(seconds))
    for i, s in enumerate(seconds):
        lo, hi = np.searchsorted(ons.times, [s - 5.0, s + 5.0])
        vals = ons.strength[lo:hi]
        local_ref[i] = np.percentile(vals, 85) if len(vals) >= 4 else global_ref
    ref_at = np.maximum(np.interp(times, seconds, local_ref), 0.4 * global_ref)
    rel = slot_strength / ref_at
    has_onset = (slot_onset >= 0) & (slot_strength >= profile.strength_floor * global_ref)
    score = np.where(has_onset, rel * np.vectorize(METRIC_WEIGHT.get)(levels), 0.0)
    energy = loud.energy(times)
    active = loud.active(times)
    # steady pulse on beats in busy sections
    pulse_ok = (levels <= 1) & active & (energy >= 0.55) & ~has_onset
    score = np.where(pulse_ok, np.maximum(score, profile.pulse * energy), score)
    # triplets only where an onset clearly asks for one
    score = np.where((levels == 4) & (rel < 0.6), 0.0, score)
    score = np.where(active | has_onset, score, 0.0)

    # ------------------------------------------------------------ 4. select
    measure_of = np.floor((beats - grid.downbeat) / grid.beats_per_measure).astype(int)
    chosen_times: list[float] = []
    chosen: list[int] = []
    for m in np.unique(measure_of):
        idx = np.flatnonzero((measure_of == m) & (score >= profile.min_score))
        if len(idx) == 0:
            continue
        m_start = grid.time_at(m * grid.beats_per_measure + grid.downbeat)
        m_end = grid.time_at((m + 1) * grid.beats_per_measure + grid.downbeat)
        budget = max(1, int(round(profile.nps * float(np.mean(energy[idx])) * (m_end - m_start))))
        taken = 0
        for j in idx[np.argsort(-score[idx], kind="stable")]:
            if taken >= budget:
                break
            t = times[j]
            gap = max(profile.min_gap_beats * grid.beat_length_at(t), profile.min_gap_s) - 1e-4
            p = bisect.bisect_left(chosen_times, t)
            if p > 0 and t - chosen_times[p - 1] < gap:
                continue
            if p < len(chosen_times) and chosen_times[p] - t < gap:
                continue
            chosen_times.insert(p, t)
            chosen.insert(p, int(j))
            taken += 1
    if not chosen:
        return chart
    chosen_arr = np.array(chosen)

    # ------------------------------------------------------------ 5. holds
    durations = np.zeros(len(chosen_arr))
    candidates = []
    for i, j in enumerate(chosen_arr):
        t = times[j]
        nxt = times[chosen_arr[i + 1]] if i + 1 < len(chosen_arr) else min(analysis.duration, end_t + 1.0)
        bl = grid.beat_length_at(t)
        if nxt - t < profile.hold_min_beats * bl:
            continue
        k = slot_onset[j]
        if k >= 0 and ons.mid[k] < 0.6 * max(ons.low[k], ons.high[k]):
            continue  # drum-like hit: nothing to hold
        lo, hi = np.searchsorted(ons.times, [t + 0.05, nxt - 0.05])
        if np.any(ons.strength[lo:hi] >= 0.5 * ref_at[j]):
            continue  # the music keeps re-attacking; a hold would ignore it
        ratio = loud.sustain_ratio(t, nxt - 0.08)
        if ratio >= profile.hold_sustain:
            candidates.append((ratio, i, nxt, bl))
    candidates.sort(reverse=True)
    for ratio, i, nxt, bl in candidates[: int(profile.hold_ratio * len(chosen_arr))]:
        t = times[chosen_arr[i]]
        end = grid.snap(nxt - profile.hold_release_beats * bl, 4)
        if end - t >= 0.45 * bl:
            durations[i] = end - t

    # ------------------------------------------------------------ 6. lanes
    half = lanes // 2
    def hand(lane: int) -> int:
        if lanes % 2 == 1 and lane == lanes // 2:
            return 2  # middle lane (thumb)
        return 0 if lane < half else 1

    notes: list[Note] = []
    last_lane, last_time, last_tone = (lanes - 1) // 2, -10.0, None
    lane_last_time = np.full(lanes, -10.0)
    recent: list[tuple[float, int]] = []
    rel_of = {}
    for i, j in enumerate(chosen_arr):
        t = float(times[j])
        k = int(slot_onset[j])
        tone = float(ons.tone[k]) if k >= 0 else last_tone
        low = float(ons.low[k]) if k >= 0 else 0.0
        mid = float(ons.mid[k]) if k >= 0 else 0.0
        high = float(ons.high[k]) if k >= 0 else 0.0
        gap = t - last_time
        direction, interval = 0, 0.0
        if tone is not None and last_tone is not None:
            interval = tone - last_tone
            if abs(interval) >= 0.75:
                direction = 1 if interval > 0 else -1
        recent = [(rt, rl) for rt, rl in recent if t - rt <= 2.0]
        usage = np.zeros(lanes)
        for _, rl in recent:
            usage[rl] += 1
        costs = np.zeros(lanes)
        for lane in range(lanes):
            move = lane - last_lane
            c = 0.0
            if t - lane_last_time[lane] < profile.jack_gap_s:
                c += 50.0
            if move == 0:
                c += 0.25 if direction == 0 else 1.3
            if direction > 0 and move <= 0:
                c += 1.0
            elif direction < 0 and move >= 0:
                c += 1.0
            if direction != 0:
                c += 0.25 * abs(abs(move) - (2 if abs(interval) >= 5 else 1))
            elif move != 0:
                c += 0.12 * abs(move)
            pos01 = lane / max(1, lanes - 1)
            if low > 1.2 * max(mid, high):
                c += 0.35 * pos01
            elif high > 1.2 * max(low, mid):
                c += 0.35 * (1.0 - pos01)
            c += 0.2 * usage[lane]
            if gap < 0.2 and hand(lane) == hand(last_lane) and hand(lane) != 2:
                c += 0.6
            c += 0.35 * _det_noise(seed, round(tone or 0), levels[j], lane, i % 7)
            costs[lane] = c
        lane = int(np.argmin(costs))
        notes.append(Note(t, lane, float(durations[i])))
        rel_of[len(notes) - 1] = (float(rel[j]), int(levels[j]))
        lane_last_time[lane] = t + durations[i]
        last_lane, last_time = lane, t
        if tone is not None:
            last_tone = tone
        recent.append((t, lane))

    # ------------------------------------------------------------ 7. chords
    extra: list[Note] = []
    last_chord = -1e9
    if profile.max_chord >= 2 and lanes >= 2:
        lane_busy_until = {}
        prev_in_lane = np.full(lanes, -10.0)
        main_times = [[n.time for n in notes if n.lane == lane] for lane in range(lanes)]
        for idx, note in enumerate(notes):
            prev_in_lane[note.lane] = note.end
            r, level = rel_of[idx]
            bl = grid.beat_length_at(note.time)
            if level > 1 or r < profile.chord_threshold:
                continue
            if note.time - last_chord < profile.chord_min_gap_beats * bl - 1e-3:
                continue
            want = 3 if (profile.max_chord >= 3 and level == 0 and r >= profile.chord3_threshold) else 2
            used = {note.lane}
            for _ in range(want - 1):
                options = []
                for lane in range(lanes):
                    if lane in used or lane_busy_until.get(lane, -1) > note.time:
                        continue
                    if note.time - prev_in_lane[lane] < profile.jack_gap_s:
                        continue
                    later = main_times[lane]
                    p = bisect.bisect_right(later, note.time + 1e-6)
                    if p < len(later) and later[p] - note.time < profile.jack_gap_s:
                        continue
                    same_hand = hand(lane) == hand(note.lane)
                    options.append((same_hand, _det_noise(seed, note.time, lane), lane))
                if not options:
                    break
                lane = min(options)[2]
                used.add(lane)
                extra.append(Note(note.time, lane))
                prev_in_lane[lane] = note.time
            if len(used) > 1:
                last_chord = note.time
            if note.is_hold:
                lane_busy_until[note.lane] = note.end

    chart.notes = notes + extra
    return chart.sort()


def generate_all(analysis, difficulties: list[str], lanes: int = 4, grid: BeatGrid | None = None,
                 seed: int = 0) -> dict[str, Chart]:
    return {d: generate_chart(analysis, d, lanes=lanes, grid=grid, seed=seed) for d in difficulties}
