import pytest

from cliq.charting.chart import Chart, Note
from cliq.charting.profiles import load_profiles
from cliq.gameplay.modifiers import prepare_play
from cliq.modes import MODES, get_mode, split_stem
from cliq.modes.path import PathSession
from cliq.modes.shield import DOWN, LEFT, UP, ShieldSession
from cliq.modes.taiko import DON, KA, TaikoSession
from cliq.settings import Settings


def session_for(cls, notes, lanes=4, mode="keys", **rule_overrides):
    chart = Chart(lanes=lanes, mode=mode, notes=[Note(*n) for n in notes])
    play_chart, rules, mods = prepare_play(chart, rule_overrides.pop("mods", []))
    for k, v in rule_overrides.items():
        setattr(rules, k, v)
    return cls(play_chart, rules, mods)


def test_registry_and_stems():
    assert set(MODES) >= {"keys", "taiko", "shield", "path"}
    assert split_stem("hard") == ("keys", "hard")
    assert split_stem("taiko-hard") == ("taiko", "hard")
    assert get_mode("taiko").chart_stem("hard") == "taiko-hard"
    assert get_mode("keys").chart_stem("hard") == "hard"


@pytest.mark.parametrize("mode_id", ["keys", "taiko", "shield", "path"])
def test_generators_for_every_difficulty(demo_analysis, mode_id):
    an, _ = demo_analysis
    mode = get_mode(mode_id)
    counts = []
    for diff in load_profiles():
        chart = mode.generate(an, diff, an.grid(), Settings(), seed=3)
        assert chart.mode == mode_id
        assert chart.notes, diff
        assert all(0 <= n.lane < chart.lanes for n in chart.notes)
        counts.append(len(chart.notes))
    assert counts[-1] > counts[0]          # master is denser than easy


def test_taiko_inner_outer_keys():
    settings = Settings()
    mode = get_mode("taiko")
    import pygame
    m = mode.key_map(settings, Chart(lanes=2, mode="taiko"))
    assert m[pygame.K_d] == KA and m[pygame.K_l] == KA
    assert m[pygame.K_f] == DON and m[pygame.K_k] == DON


def test_taiko_big_bonus_and_second_hand_is_not_spam():
    s = session_for(TaikoSession, [(1.0, DON, 0, "big"), (2.0, KA)], lanes=2, mode="taiko")
    s.press(DON, 1.0)
    score = s.score
    s.press(DON, 1.02)                      # other hand, same drum
    assert s.score > score and s.counts["miss"] == 0
    assert s.notes[1].result is None        # anti-spam did not eat the next note


def test_taiko_drumroll():
    s = session_for(TaikoSession, [(1.0, DON, 1.0, "roll"), (3.0, KA)], lanes=2, mode="taiko")
    for i in range(8):
        s.press(DON if i % 2 else KA, 1.1 + i * 0.1)
    s.update(2.1)
    assert s.roll_hits == 8 and s.notes[0].result == "roll" and s.counts["miss"] == 0


def test_shield_blocks_by_facing():
    s = session_for(ShieldSession, [(1.0, LEFT), (2.0, UP), (3.0, DOWN)], mode="shield")
    s.press(LEFT, 0.5)
    s.update(1.01)
    assert s.notes[0].result == "perfect"
    s.update(2.01)                          # still facing left: the up arrow gets through
    assert s.notes[1].result == "miss"
    s.press(DOWN, 2.5)
    s.update(3.01)
    assert s.notes[2].result == "perfect"
    assert s.errors == []


def test_path_tap_critical_mash_hold():
    s = session_for(PathSession, [(1.0, 0), (2.0, 0, 0, "critical"), (3.0, 0, 1.0, "mash"), (5.0, 0, 0.5)],
                    mode="path")
    assert s.press(2, 1.01).result == "perfect"          # any key taps
    for lane in range(4):
        s.press(lane, 2.0 + lane * 0.01)
        s.release(lane, 2.1)
    assert s.notes[1].result in ("perfect", "great")
    for i in range(7):
        s.press(i % 4, 3.05 + i * 0.12)
    s.update(4.01)
    assert s.notes[2].result == "perfect"
    s.press(1, 5.0)
    s.update(5.6)
    assert s.counts["hold_ok"] == 1 and s.counts["miss"] == 0


def test_path_critical_needs_all_keys():
    s = session_for(PathSession, [(1.0, 0, 0, "critical")], mode="path")
    s.press(0, 1.0)
    s.update(1.5)
    assert s.notes[0].result == "miss"


def test_modes_autoplay_clean(demo_analysis):
    an, _ = demo_analysis
    for mode_id in ("taiko", "shield", "path"):
        mode = get_mode(mode_id)
        chart = mode.generate(an, "hard", an.grid(), Settings())
        play, rules, mods = prepare_play(chart, ["autoplay"])
        s = mode.session(play, rules, mods, None, float("-inf"))
        t = 0.0
        while t < an.duration + 2 and not s.finished:
            s.update(t)
            t += 1 / 240
        assert s.finished and s.misses == 0, mode_id
