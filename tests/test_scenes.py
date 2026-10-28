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
    # Wall-clock time (audio, key holds), but never stop halfway through a scene fade: fades
    # advance by frame steps, so on a busy machine a short wait could leave one pending.
    end = time.perf_counter() + seconds
    n = 0
    while time.perf_counter() < end or ((app._pending is not None or app._fading_in) and n < 2000):
        app._frame(1 / fps)
        n += 1
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


def test_editor_selection_clipboard_overlap_and_drain(app):
    from cliq.charting.chart import Note
    from cliq.scenes.editor import EditorScene

    song = app.library.songs[0]
    app.push(EditorScene(app, song, "clip"), instant=True)
    frames(app, 0.2)
    ed = app.scene
    ed.help = False
    ctrl = pygame.KMOD_CTRL
    ed.seek(ed.grid.time_at(8))
    for lane_key in (pygame.K_d, pygame.K_f):
        key(app, lane_key)
        key(app, pygame.K_UP)
    assert len(ed.notes) == 2
    key(app, pygame.K_a, mod=ctrl)
    key(app, pygame.K_c, mod=ctrl)
    ed.seek(ed.grid.time_at(16))
    key(app, pygame.K_v, mod=ctrl)
    assert len(ed.notes) == 4 and len(ed.selection) == 2          # pasted notes are selected
    pasted = ed.selected()
    assert ed.grid.beat_at(pasted[0].time) == pytest.approx(16, abs=1e-3)
    key(app, pygame.K_m, mod=ctrl)                                  # mirror lanes 0,1 -> 3,2
    assert sorted(n.lane for n in ed.selected()) == [2, 3]
    key(app, pygame.K_UP, mod=pygame.KMOD_ALT)                      # nudge the selection
    assert ed.grid.beat_at(ed.selected()[0].time) != pytest.approx(16, abs=1e-3)
    key(app, pygame.K_x, mod=ctrl)
    assert len(ed.notes) == 2 and not ed.selection
    # overlapping notes: a hold over existing taps keeps them; an exact duplicate toggles off
    t8 = ed.grid.time_at(8)
    ed.apply([Note(round(t8, 4), 0, round(ed.grid.time_at(10) - t8, 4))], [])
    assert len(ed.notes) == 3
    ed.toggle_note(0, ed.grid.time_at(8.25))                        # 1/16 after the hold head
    assert len(ed.notes) == 4
    ed.toggle_note(0, ed.grid.time_at(8.25))
    assert len(ed.notes) == 3
    # health drain is stored in the chart
    default = ed.drain
    key(app, pygame.K_PERIOD)
    key(app, pygame.K_PERIOD)
    assert ed.drain == pytest.approx(default + 0.2)
    key(app, pygame.K_s, mod=ctrl)
    assert song.load_chart("clip").meta["health_drain"] == pytest.approx(default + 0.2)
    key(app, pygame.K_COMMA, mod=pygame.KMOD_SHIFT)
    assert "health_drain" not in ed.meta
    ed.dirty = False
    key(app, pygame.K_ESCAPE)
    frames(app, 0.4)
    assert scene_name(app) != "EditorScene"


def test_song_select_popup_modes_and_video_background(app, tmp_path):
    from cliq.scenes.song_select import SongSelectScene

    exe = ffmpeg.find_ffmpeg()
    beat = 60 / 120
    y = np.zeros(int(9 * synth.SR))
    k = synth.kick()
    for i in range(16):
        j = int((0.5 + i * beat) * synth.SR)
        y[j:j + len(k)] += k[: len(y) - j]
    wav = tmp_path / "beat.wav"
    synth.write_wav(wav, y * 0.8)
    clip = tmp_path / "Clip With Video.mp4"
    import subprocess
    subprocess.run([exe, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30", "-i", str(wav),
                    "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    str(clip)], check=True)
    app.push(SongSelectScene(app), instant=True)
    frames(app, 0.2)
    scene = app.scene
    app.settings.import_background = "video720"
    key(app, pygame.K_i)
    assert scene.popup.open
    scene.popup.start(str(clip))
    deadline = time.perf_counter() + 60
    while scene.popup.job is not None and time.perf_counter() < deadline:
        frames(app, 0.1)
    assert scene.song.title == "Clip With Video" and not scene.popup.open
    assert scene.song.background_kind() == "video"
    key(app, pygame.K_TAB)                                          # keys -> taiko
    assert scene.mode_id == "taiko" and scene.difficulty
    key(app, pygame.K_RETURN)
    assert scene.entering is not None                               # zooming into the cover
    deadline = time.perf_counter() + 5
    while scene_name(app) == "SongSelectScene" and time.perf_counter() < deadline:
        frames(app, 0.05)
    assert scene_name(app) == "GameplayScene" and app.scene.mode.id == "taiko"
    frames(app, 1.5)
    assert app.scene.video is not None and app.scene.video.ready
    assert scene.song.load_chart("taiko-" + scene.difficulty) is not None   # generated on demand
    app.scene.quit()
    frames(app, 0.5)
    for _ in range(3):
        key(app, pygame.K_TAB)                                      # back to keys
    assert scene.mode_id == "keys"
    key(app, pygame.K_ESCAPE)
    frames(app, 0.4)


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


def test_playlist_plays_songs_back_to_back(app):
    from cliq.library.playlists import PlaylistBook
    from cliq.scenes.playlists import PlaylistsScene

    short = [s for s in app.library.scan() if s.duration < 15][:2]
    assert len(short) == 2
    app.settings.enabled_modifiers = ["autoplay"]
    app.settings.last_mode, app.settings.last_difficulty = "keys", "easy"
    app.push(PlaylistsScene(app), instant=True)
    frames(app, 0.2)
    scene = app.scene
    key(app, pygame.K_n)                                  # new playlist, straight into renaming
    assert scene.renaming
    scene.name_input.set_text("Road trip")
    key(app, pygame.K_RETURN)
    assert scene.playlist.name == "Road trip" and not scene.renaming
    key(app, pygame.K_a)                                  # song picker
    songs = app.library.songs
    for s in short:
        scene.picker["index"] = songs.index(s)
        key(app, pygame.K_RETURN)
    key(app, pygame.K_ESCAPE)
    assert [e.song_id for e in scene.playlist.entries] == [s.id for s in short]
    assert PlaylistBook().get(scene.playlist.id).name == "Road trip"   # saved
    key(app, pygame.K_RETURN)                             # play in order
    frames(app, 0.5)
    titles = []
    deadline = time.perf_counter() + 90
    while scene_name(app) != "RunSummaryScene" and time.perf_counter() < deadline:
        if scene_name(app) == "GameplayScene" and (not titles or titles[-1] != app.scene.song.title):
            titles.append(app.scene.song.title)
            assert app.scene.run is not None
        if scene_name(app) == "ResultsScene":
            frames(app, 0.3)
            key(app, pygame.K_RETURN)                     # next song / finish
        frames(app, 0.1)
    assert scene_name(app) == "RunSummaryScene"
    assert titles == [s.title for s in short]
    run = app.scene.run
    assert run.totals()["played"] == 2 and run.totals()["cleared"] == 2
    key(app, pygame.K_RETURN)
    frames(app, 0.5)
    assert scene_name(app) == "PlaylistsScene"
    app.settings.enabled_modifiers = []
    key(app, pygame.K_ESCAPE)
    frames(app, 0.4)
