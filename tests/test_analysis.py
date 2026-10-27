import numpy as np
import pytest

from cliq.analysis import features as F
from cliq.analysis.analyzer import SongAnalysis, analyze_signal
from cliq.audio import synth

SR = F.SR


def _add(y, buf, t):
    i = int(round(t * SR))
    seg = buf[: max(0, len(y) - i)]
    y[i:i + len(seg)] += seg


def _place(buf, times, total):
    y = np.zeros(int(total * SR))
    for t in times:
        _add(y, buf, t)
    return y


def _drum_track(bpm, bars=40, offset=0.37, drift=0.0, jitter_ms=0.0, seed=0):
    rng = np.random.default_rng(seed)
    kick, clap, hat = synth.kick(SR), synth.clap(SR), synth.hat(False, SR)
    n = bars * 4
    beats = [offset]
    for k in range(1, n + 1):
        beats.append(beats[-1] + 60.0 / (bpm * (1 + drift * k / n)))
    beats = np.array(beats)
    y = np.zeros(int((beats[-1] + 2) * SR))
    def jitter():
        return rng.normal(0, jitter_ms / 1000) if jitter_ms else 0.0

    for i in range(n):
        tb, half = beats[i], (beats[i] + beats[i + 1]) / 2
        _add(y, kick * 0.9, tb + jitter())
        if i % 4 in (1, 3):
            _add(y, clap * 0.5, tb + jitter())
        _add(y, hat * 0.15, half + jitter())
    return (y / np.abs(y).max()).astype(np.float32), beats[:-1]


def _beat_errors(an: SongAnalysis, true_beats):
    if an.beat_times is not None:
        pred = an.beat_times
    else:
        period = 60.0 / an.bpm
        j0 = np.floor((true_beats[0] - an.offset) / period) - 2
        pred = an.offset + np.arange(j0, j0 + len(true_beats) + 6) * period
    return np.array([pred[np.argmin(np.abs(pred - t))] - t for t in true_beats])


@pytest.mark.parametrize("name,sound", [("kick", synth.kick(SR)), ("clap", synth.clap(SR)),
                                         ("click", synth.click(1500, SR)), ("pluck", synth.pluck(440, 0.3, SR))])
def test_onset_timing_is_unbiased(name, sound):
    times = 0.5 + np.arange(30) * 0.61
    y = _place(sound, times, times[-1] + 1.5)
    feat = F.compute_features(y, SR)
    ons = F.detect_onsets(feat, y, SR)
    err = np.array([ons.times[np.argmin(np.abs(ons.times - t))] - t for t in times])
    assert abs(np.median(err)) < 0.0025, f"{name}: onset bias {np.median(err) * 1000:.2f} ms"
    assert np.std(err) < 0.002


def test_pitch_estimate_follows_notes():
    times = [0.5, 1.5]
    y = _place(synth.pluck(440.0, 0.4, SR), times[:1], 3.0) + _place(synth.pluck(659.26, 0.4, SR), times[1:], 3.0)
    tones = F.estimate_tones(y, SR, np.array(times))
    assert abs(tones[0] - 69) <= 0.5 and abs(tones[1] - 76) <= 0.5


@pytest.mark.parametrize("bpm,offset", [(128.0, 0.37), (100.0, 1.234), (140.0, 0.05), (96.3, 0.6)])
def test_constant_tempo_grid(bpm, offset):
    y, beats = _drum_track(bpm, offset=offset)
    an = analyze_signal(y, SR)
    assert an.beat_times is None
    assert abs(an.bpm - bpm) < 0.02
    err = _beat_errors(an, beats)
    assert np.max(np.abs(err)) < 0.004
    # measure lines land on the real downbeats
    first = int(round((beats[0] - an.offset) / (60.0 / an.bpm)))
    assert (first - an.downbeat) % 4 == 0


def test_humanised_timing_still_locks_on():
    y, beats = _drum_track(133.0, jitter_ms=10, seed=3)
    an = analyze_signal(y, SR)
    assert abs(an.bpm - 133.0) < 0.05
    assert np.mean(np.abs(_beat_errors(an, beats))) < 0.004


def test_tempo_drift_switches_to_variable_grid():
    y, beats = _drum_track(110.0, bars=40, drift=0.05)
    an = analyze_signal(y, SR)
    assert an.beat_times is not None
    assert np.mean(np.abs(_beat_errors(an, beats))) < 0.005


def test_demo_song(demo_analysis):
    an, info = demo_analysis
    assert abs(an.bpm - info["bpm"]) < 0.05
    true_beats = info["offset"] + np.arange(32 * 4) * 60.0 / info["bpm"]
    assert np.mean(np.abs(_beat_errors(an, true_beats))) < 0.008


def test_analysis_roundtrip(tmp_path, demo_analysis):
    an, _ = demo_analysis
    path = tmp_path / "analysis.npz"
    an.save(path)
    back = SongAnalysis.load(path)
    assert back is not None
    assert back.bpm == pytest.approx(an.bpm)
    assert len(back.onsets) == len(an.onsets)
    np.testing.assert_allclose(back.onsets.times, an.onsets.times)


def test_silence_does_not_crash():
    an = analyze_signal(np.zeros(SR * 5, dtype=np.float32), SR)
    assert an.bpm > 0
