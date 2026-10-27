import numpy as np
import pytest

from cliq.audio import ffmpeg, synth
from cliq.library.importer import ImportFailed, import_song, install_demo_song
from cliq.library.scores import ScoreBook
from cliq.library.song import SongLibrary
from cliq.settings import Settings

pytestmark = pytest.mark.skipif(ffmpeg.find_ffmpeg() is None, reason="needs ffmpeg")


def _write_song(path, seconds=12.0, bpm=120.0):
    beat = 60.0 / bpm
    y = np.zeros(int(seconds * synth.SR))
    k = synth.kick()
    for i in range(int(seconds / beat) - 1):
        j = int((0.5 + i * beat) * synth.SR)
        y[j:j + len(k)] += k[: len(y) - j]
    synth.write_wav(path, y * 0.8)


def test_import_local_file(cliq_home, tmp_path):
    src = tmp_path / "My Track.wav"
    _write_song(src)
    lib = SongLibrary()
    song, existed = import_song(str(src), lib)
    assert not existed
    assert song.audio_path.exists() and song.analysis_path.exists()
    assert song.chart_names() == ["easy", "normal", "hard", "expert"]
    assert song.title == "My Track"
    assert abs(song.grid.bpm - 120.0) < 0.1
    assert lib.scan()[0].id == song.id
    again, existed = import_song(f'"{src}"', lib)       # quoted path, same file
    assert existed and again.id == song.id


def test_import_errors_are_friendly(cliq_home, tmp_path):
    lib = SongLibrary()
    with pytest.raises(ImportFailed, match="not found"):
        import_song(str(tmp_path / "nope.mp3"), lib)
    bad = tmp_path / "notes.txt"
    bad.write_text("hi")
    with pytest.raises(ImportFailed, match="Unsupported"):
        import_song(str(bad), lib)
    silent = tmp_path / "silent.wav"
    synth.write_wav(silent, np.zeros(synth.SR * 5))
    with pytest.raises(ImportFailed, match="silent"):
        import_song(str(silent), lib)
    assert lib.scan() == []      # failed imports leave nothing behind


def test_demo_song_install(cliq_home):
    lib = SongLibrary()
    song = install_demo_song(lib)
    assert song is not None and abs(song.grid.bpm - 128) < 0.1
    assert install_demo_song(lib) is None


def test_settings_roundtrip(cliq_home):
    s = Settings.load()
    s.scroll_direction = "up"
    s.set_key(4, 0, "a")
    s.save()
    back = Settings.load()
    assert back.scroll_direction == "up" and back.keys_for(4) == ["a", "f", "k", "l"]
    back.set_key(4, 1, "a")      # rebinding to a used key swaps them
    assert back.keys_for(4) == ["f", "a", "k", "l"]


def test_settings_survive_garbage(cliq_home):
    from cliq import paths

    paths.SETTINGS_FILE.write_text('{"scroll_speed": "fast", "note_skin": "nope", "unknown": 1}')
    s = Settings.load()
    assert s.scroll_speed == 1.6 and s.note_skin == "arrows"


def test_scorebook(cliq_home):
    book = ScoreBook()
    assert book.record("song", "hard", {"score": 100, "accuracy": 0.9})
    assert not book.record("song", "hard", {"score": 50, "accuracy": 0.5})
    assert ScoreBook().best("song", "hard")["score"] == 100
