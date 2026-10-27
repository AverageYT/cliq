"""Headless smoke tests: drive the real app through every scene."""

import time

import numpy as np
import pygame
import pytest

from cliq import paths
from cliq.audio import ffmpeg, synth

pytestmark = pytest.mark.skipif(ffmpeg.find_ffmpeg() is None, reason="needs ffmpeg")


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    home = tmp_path_factory.mktemp("cliq_home")
    mp = pytest.MonkeyPatch()
    mp.setattr(paths, "HOME", home)
    mp.setattr(paths, "SONGS_DIR", home / "songs")
    mp.setattr(paths, "MODS_DIR", home / "mods")
    mp.setattr(paths, "USER_DIR", home / "user")
    mp.setattr(paths, "CACHE_DIR", home / "user" / "cache")
    mp.setattr(paths, "SETTINGS_FILE", home / "user" / "settings.json")
    mp.setattr(paths, "SCORES_FILE", home / "user" / "scores.json")
    from cliq.app import App
    from cliq.scenes.title import TitleScene

    application = App()
    application._apply(("push", TitleScene(application), {}))
    deadline = time.time() + 120
    while application.demo_job is not None and time.time() < deadline:
        application._frame(1 / 60)
        time.sleep(0.01)
    yield application
    mp.undo()


def frames(app, seconds=0.2, fps=240):
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        app._frame(1 / fps)
        time.sleep(1 / fps)


def key(app, k, mod=0, hold=0.02):
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=k, mod=mod, unicode="", scancode=0))
    frames(app, hold)
    pygame.event.post(pygame.event.Event(pygame.KEYUP, key=k, mod=mod, unicode="", scancode=0))
    frames(app, 0.02)


def scene_name(app):
    return type(app.scene).__name__


def test_demo_song_installed(app):
    assert [s.title for s in app.library.songs] == ["Cliq Starter"]


def test_autoplay_run_reaches_results(app):
    from cliq.scenes.gameplay import GameplayScene
    from cliq.scenes.song_select import SongSelectScene

    app.push(SongSelectScene(app), instant=True)
    frames(app, 0.2)
    song = app.library.songs[0]
    chart = song.load_chart("easy")
    app.push(GameplayScene(app, song, chart, "easy", ["autoplay"], start_time=50.0), instant=True)
    frames(app, 0.2)
    assert scene_name(app) == "GameplayScene"
    deadline = time.perf_counter() + 40
    while scene_name(app) == "GameplayScene" and time.perf_counter() - deadline < 0:
        frames(app, 0.25)
    assert scene_name(app) == "ResultsScene"
    summary = app.scene.summary
    assert summary["counts"]["miss"] == 0 and summary["counts"]["perfect"] > 0
    key(app, pygame.K_RETURN)
    frames(app, 0.5)
    assert scene_name(app) == "SongSelectScene"


def test_playing_by_hand_registers_hits_and_misses(app):
    from cliq.scenes.gameplay import GameplayScene

    song = app.library.songs[0]
    chart = song.load_chart("normal")
    scene = GameplayScene(app, song, chart, "normal", [], start_time=20.0)
    app.push(scene, instant=True)
    deadline = time.perf_counter() + 6
    hits = 0
    lanes = {0: pygame.K_d, 1: pygame.K_f, 2: pygame.K_k, 3: pygame.K_l}
    while time.perf_counter() < deadline:
        t = scene.conductor.time
        for n in scene.session.notes:
            if not n.judged and abs(n.time - t) < 0.01:
                key(app, lanes[n.lane], hold=0.01)
                hits += 1
                break
        frames(app, 0.004)
    judged = sum(scene.session.counts.get(k, 0) for k in ("perfect", "great", "good", "bad"))
    assert judged > 0
    key(app, pygame.K_ESCAPE)
    frames(app, 0.2)
    assert scene.paused
    key(app, pygame.K_q)
    frames(app, 0.5)
    assert scene_name(app) == "SongSelectScene"


def test_editor_edit_undo_save(app):
    from cliq.scenes.editor import EditorScene

    song = app.library.songs[0]
    app.push(EditorScene(app, song, "custom"), instant=True)
    frames(app, 0.3)
    editor = app.scene
    assert editor.notes == [] and editor.help         # new chart starts empty with help shown
    key(app, pygame.K_h)
    key(app, pygame.K_PAGEUP)                         # move forward a measure
    key(app, pygame.K_d)                              # paused: toggle a note at the playhead
    key(app, pygame.K_UP)
    key(app, pygame.K_k)
    assert len(editor.notes) == 2
    key(app, pygame.K_z, mod=pygame.KMOD_CTRL)
    assert len(editor.notes) == 1
    key(app, pygame.K_y, mod=pygame.KMOD_CTRL)
    assert len(editor.notes) == 2
    key(app, pygame.K_EQUALS)                         # nudge BPM
    assert editor.grid.bpm == pytest.approx(song.grid.bpm + 0.1, abs=1e-6)
    key(app, pygame.K_s, mod=pygame.KMOD_CTRL)
    saved = song.load_chart("custom")
    assert saved is not None and len(saved.notes) == 2 and saved.meta.get("edited")
    # record by playing along
    key(app, pygame.K_SPACE)
    frames(app, 0.6)
    key(app, pygame.K_f, hold=0.05)
    frames(app, 0.2)
    key(app, pygame.K_l, hold=0.6)
    key(app, pygame.K_SPACE)
    assert len(editor.notes) == 4
    assert any(n.is_hold for n in editor.notes)
    key(app, pygame.K_ESCAPE)                         # unsaved -> asks first
    frames(app, 0.1)
    assert scene_name(app) == "EditorScene"
    key(app, pygame.K_ESCAPE)
    frames(app, 0.5)
    assert scene_name(app) != "EditorScene"


def test_settings_change_and_rebind(app):
    from cliq.scenes.settings_menu import SettingsScene

    app.push(SettingsScene(app), instant=True)
    frames(app, 0.1)
    before = app.settings.scroll_direction
    key(app, pygame.K_RIGHT)                          # scroll direction
    assert app.settings.scroll_direction != before
    key(app, pygame.K_LEFT)
    key(app, pygame.K_TAB)                            # controls
    key(app, pygame.K_RETURN)
    key(app, pygame.K_a)                              # lane 1 -> A, flows to lane 2
    key(app, pygame.K_ESCAPE)
    assert app.settings.keys_for(4)[0] == "a"
    app.settings.set_key(4, 0, "d")
    for _ in range(2):
        key(app, pygame.K_TAB)                        # audio, display
    for _ in range(8):
        key(app, pygame.K_DOWN)                       # wraps around safely
    key(app, pygame.K_ESCAPE)
    frames(app, 0.4)
    assert scene_name(app) != "SettingsScene"


def test_import_scene_adds_a_file(app, tmp_path):
    from cliq.scenes.import_song import ImportScene

    beat = 60 / 110
    y = np.zeros(int(10 * synth.SR))
    k = synth.kick()
    for i in range(16):
        j = int((0.4 + i * beat) * synth.SR)
        y[j:j + len(k)] += k[: len(y) - j]
    src = tmp_path / "Imported Groove.wav"
    synth.write_wav(src, y * 0.8)
    app.push(ImportScene(app), instant=True)
    scene = app.scene
    scene.start(str(src))
    deadline = time.perf_counter() + 60
    while scene_name(app) == "ImportScene" and time.perf_counter() < deadline:
        frames(app, 0.1)
    assert scene_name(app) == "SongSelectScene"
    assert app.scene.song.title == "Imported Groove"


def test_calibration_measures_taps(app):
    from cliq.scenes.calibration import CalibrationScene

    app.push(CalibrationScene(app), instant=True)
    scene = app.scene
    frames(app, 0.2)
    for _ in range(10):                               # tap every 0.5 s, roughly on the clicks
        t = scene.conductor.time
        nxt = min((b for b in scene.beats if b > t + 0.05), default=None)
        if nxt is None:
            break
        frames(app, max(0.0, nxt - scene.conductor.time + 0.02))
        key(app, pygame.K_SPACE, hold=0.005)
    assert len(scene.errors) >= 6
    assert abs(scene.median_ms) < 60
    key(app, pygame.K_ESCAPE)
    frames(app, 0.3)
