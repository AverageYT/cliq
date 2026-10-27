import pytest

from cliq.charting.chart import Chart, Note
from cliq.gameplay.modifiers import REGISTRY, create_modifiers, prepare_play
from cliq.gameplay.rules import load_rules
from cliq.gameplay.session import PlaySession


def make_session(notes, mods=(), lanes=4, **rule_overrides):
    chart = Chart(lanes=lanes, notes=[Note(*n) for n in notes])
    play_chart, rules, modifiers = prepare_play(chart, mods)
    for k, v in rule_overrides.items():
        setattr(rules, k, v)
    events = []
    session = PlaySession(play_chart, rules, modifiers)
    for name in ("judgement", "hold_complete", "hold_drop", "combo_break", "fail", "finish", "ghost_tap"):
        session.bus.on(name, lambda name=name, **kw: events.append((name, kw)))
    return session, events


def test_perfect_hit_and_windows():
    s, ev = make_session([(1.0, 0), (2.0, 1), (3.0, 2), (4.0, 3)])
    assert s.press(0, 1.010).result == "perfect"
    assert s.press(1, 2.070).result == "great"
    assert s.press(2, 2.880).result == "good"      # 120 ms early
    assert s.press(3, 4.160).result == "bad"
    assert s.counts["perfect"] == 1 and s.combo == 0   # bad breaks combo
    assert s.errors[0] == pytest.approx(0.010)


def test_too_early_press_is_ghost_and_note_waits():
    s, ev = make_session([(1.0, 0)])
    assert s.press(0, 0.5) is None
    assert ev[-1][0] == "ghost_tap"
    assert s.press(0, 1.0).result == "perfect"


def test_late_notes_are_missed_by_update():
    s, ev = make_session([(1.0, 0), (1.1, 1)])
    s.update(1.5)
    assert s.counts["miss"] == 2 and s.accuracy == 0.0 and s.combo == 0


def test_press_after_window_misses_stale_note_and_hits_next():
    s, _ = make_session([(1.0, 0), (1.25, 0)])
    hit = s.press(0, 1.24)   # first note's window has passed, nobody called update
    assert hit is not None and hit.time == 1.25
    assert s.counts["miss"] == 1


def test_hold_complete_and_drop():
    s, ev = make_session([(1.0, 0, 1.0), (3.0, 1, 1.0)])
    s.press(0, 1.0)
    s.update(1.5)
    s.release(0, 1.95)            # within the release window -> ok
    assert s.counts["hold_ok"] == 1
    s.press(1, 3.0)
    s.release(1, 3.3)             # far too early -> dropped
    assert s.counts["hold_drop"] == 1 and s.combo == 0
    names = [e[0] for e in ev]
    assert "hold_complete" in names and "hold_drop" in names


def test_hold_completes_automatically_when_still_held():
    s, _ = make_session([(1.0, 2, 0.5)])
    s.press(2, 1.0)
    s.update(1.6)
    assert s.counts["hold_ok"] == 1 and not s.active_holds


def test_ghost_tapping_off_breaks_combo():
    s, _ = make_session([(1.0, 0), (2.0, 0)], ghost_tapping=False)
    s.press(0, 1.0)
    assert s.combo == 1
    s.press(3, 1.5)
    assert s.combo == 0 and s.health < 0.55


def test_health_runs_out_and_fails():
    s, ev = make_session([(i * 0.1, 0) for i in range(1, 40)])
    s.update(10.0)
    assert s.failed and any(name == "fail" for name, _ in ev)


def test_finish_event_and_summary():
    s, ev = make_session([(1.0, 0), (1.5, 1)])
    s.press(0, 1.0)
    s.press(1, 1.52)
    s.update(3.0)
    assert s.finished
    summary = s.summary()
    assert summary["full_combo"] and summary["grade"] in ("S+", "S")
    assert summary["mean_offset_ms"] == pytest.approx(10.0)


def test_autoplay_hits_everything_perfectly():
    notes = [(0.5 + i * 0.25, i % 4, 0.5 if i % 7 == 0 else 0.0) for i in range(40)]
    s, _ = make_session(notes, mods=["autoplay"])
    t = 0.0
    while t < 13.0:
        s.update(t)
        t += 1 / 240
    assert s.counts["perfect"] == 40 and s.counts["miss"] == 0 and s.accuracy == 1.0
    assert s.finished


def test_start_time_skips_earlier_notes():
    chart = Chart(lanes=4, notes=[Note(1.0, 0), Note(5.0, 1)])
    s = PlaySession(chart, load_rules(), start_time=3.0)
    s.update(4.0)
    assert s.counts["miss"] == 0          # the note at 1.0 was skipped, not missed
    s.update(5.5)
    assert s.counts["miss"] == 1


def test_mirror_and_shuffle():
    chart = Chart(lanes=4, notes=[Note(1.0, 0), Note(2.0, 1), Note(3.0, 2), Note(4.0, 3)])
    mirrored, _, _ = prepare_play(chart, ["mirror"])
    assert [n.lane for n in mirrored.notes] == [3, 2, 1, 0]
    assert [n.lane for n in chart.notes] == [0, 1, 2, 3]       # original untouched
    for seed in range(5):
        shuffled, _, _ = prepare_play(chart, ["shuffle"], seed=seed)
        lanes = [n.lane for n in sorted(shuffled.notes, key=lambda n: n.time)]
        assert sorted(lanes) == [0, 1, 2, 3] and lanes != [0, 1, 2, 3]


def test_modifier_rules_and_incompatibility():
    _, rules, mods = prepare_play(Chart(), ["generous", "precise", "sudden_death"])
    assert [m.id for m in mods] == ["generous", "sudden_death"]
    assert rules.window_scale == pytest.approx(1.4) and rules.sudden_death


def test_combo_shield_item():
    s, _ = make_session([(1.0, 0), (2.0, 0), (3.0, 0)], mods=["shield"])
    s.press(0, 1.0)
    s.update(2.5)   # miss the second note
    assert s.combo == 1 and s.modifiers[0].charges == 2


def test_sudden_death():
    s, _ = make_session([(1.0, 0), (2.0, 0)], mods=["sudden_death"])
    s.update(1.5)
    assert s.failed


def test_registry_has_builtins():
    assert {"autoplay", "mirror", "hidden", "sudden", "shield"} <= set(REGISTRY)
    assert all(m.name for m in create_modifiers(list(REGISTRY)))
