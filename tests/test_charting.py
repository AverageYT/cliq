import numpy as np
import pytest

from cliq.charting.autochart import generate_chart
from cliq.charting.beatgrid import BeatGrid
from cliq.charting.chart import Chart, Note
from cliq.charting.profiles import get_profile, load_profiles


# ------------------------------------------------------------------ beat grid
def test_constant_grid_roundtrip():
    g = BeatGrid(bpm=120, offset=0.25)
    assert g.time_at(4) == pytest.approx(2.25)
    assert g.beat_at(2.25) == pytest.approx(4)
    assert g.snap(1.01, 4) == pytest.approx(1.0)
    assert g.snap(1.13, 2) == pytest.approx(1.25)


def test_grid_steps_never_skip_lines():
    g = BeatGrid(bpm=120, offset=0.0)          # beat = 0.5 s
    assert g.step(1.0, 1, 1) == pytest.approx(1.5)
    assert g.step(1.2, 1, 1) == pytest.approx(1.5)   # from between lines -> next line
    assert g.step(1.2, 1, -1) == pytest.approx(1.0)  # ... or previous line
    assert g.step(1.0, 4, -1) == pytest.approx(0.875)
    assert g.measure_step(0.3, 1) == pytest.approx(2.0)
    assert g.measure_step(2.3, -1) == pytest.approx(2.0)
    assert g.measure_step(2.0, -1) == pytest.approx(0.0)


def test_variable_grid_interpolates_and_extrapolates():
    beats = [1.0, 1.5, 2.1, 2.8]
    g = BeatGrid(bpm=100, beat_times=beats)
    assert g.time_at(1.5) == pytest.approx(1.8)
    assert g.beat_at(2.45) == pytest.approx(2.5)
    assert g.time_at(-1) == pytest.approx(0.5)
    assert g.time_at(4) == pytest.approx(3.5)
    assert g.beat_at(g.time_at(5.25)) == pytest.approx(5.25)


def test_with_bpm_keeps_anchor_beat():
    g = BeatGrid(bpm=120, offset=0.1, downbeat=1)
    anchor = g.time_at(9)
    g2 = g.with_bpm(121.0, anchor_time=anchor)
    assert any(abs(g2.time_at(b) - anchor) < 1e-9 for b in range(-2, 40))
    assert 0 <= g2.offset < g2.period


def test_tap_tempo():
    taps = [0.3 + i * 0.5 + (0.004 if i % 2 else -0.004) for i in range(8)]
    g = BeatGrid.from_taps(taps)
    assert g.bpm == pytest.approx(120, abs=0.5)


# ------------------------------------------------------------------ chart io
def test_chart_json_roundtrip(tmp_path):
    chart = Chart(lanes=4, difficulty="hard", notes=[Note(1.0, 0), Note(1.5, 3, 0.5), Note(2.0, 1, 0, "mine")])
    chart.save(tmp_path / "c.json")
    back = Chart.load(tmp_path / "c.json")
    assert [(n.time, n.lane, n.duration, n.kind) for n in back.notes] == \
        [(1.0, 0, 0.0, "tap"), (1.5, 3, 0.5, "tap"), (2.0, 1, 0.0, "mine")]


def test_chart_ignores_bad_notes():
    chart = Chart.from_json({"lanes": 4, "notes": [[1, 0], [2, 9], "junk", {"t": 3, "l": 2, "d": 1}]})
    assert [(n.time, n.lane) for n in chart.notes] == [(1.0, 0), (3.0, 2)]


# ------------------------------------------------------------------ auto charter
@pytest.fixture(scope="module")
def charts(demo_analysis):
    an, _ = demo_analysis
    return an, {d: generate_chart(an, d, lanes=4) for d in load_profiles()}


def test_density_rises_with_difficulty(charts):
    _, cs = charts
    counts = [len(cs[d].notes) for d in ("easy", "normal", "hard", "expert")]
    assert counts == sorted(counts) and counts[0] > 20


def test_notes_sit_on_the_beat_grid(charts):
    an, cs = charts
    grid = an.grid()
    for chart in cs.values():
        for n in chart.notes:
            b = grid.beat_at(n.time) * 12   # 12 = lcm of 4 (16ths) and 3 (triplets)
            assert abs(b - round(b)) < 1e-3


def test_playability_rules(charts):
    _, cs = charts
    for diff, chart in cs.items():
        profile = get_profile(diff)
        by_time = {}
        for n in chart.notes:
            by_time.setdefault(round(n.time, 4), []).append(n)
        assert max(len(v) for v in by_time.values()) <= profile.max_chord
        for lane in range(chart.lanes):
            lane_notes = [n for n in chart.notes if n.lane == lane]
            for a, b in zip(lane_notes, lane_notes[1:]):
                assert b.time - a.end >= min(profile.jack_gap_s, 0.15) - 1e-6, (diff, a, b)
        easy_gaps = np.diff(sorted({n.time for n in chart.notes}))
        assert easy_gaps.min() >= profile.min_gap_s - 1e-3


def test_all_lanes_used_and_balanced(charts):
    _, cs = charts
    counts = np.bincount([n.lane for n in cs["hard"].notes], minlength=4)
    assert counts.min() > 0.5 * counts.mean()


def test_generation_is_deterministic(demo_analysis):
    an, _ = demo_analysis
    a = generate_chart(an, "hard", seed=5)
    b = generate_chart(an, "hard", seed=5)
    assert [n.to_json() for n in a.notes] == [n.to_json() for n in b.notes]


def test_other_lane_counts(demo_analysis):
    an, _ = demo_analysis
    for lanes in (5, 6, 7):
        chart = generate_chart(an, "hard", lanes=lanes)
        assert {n.lane for n in chart.notes} == set(range(lanes))


def test_profile_overrides(demo_analysis):
    an, _ = demo_analysis
    dense = generate_chart(an, "normal", nps=8.0, min_gap_beats=0.25, divisions=[1, 2, 4])
    assert len(dense.notes) > len(generate_chart(an, "normal").notes)
