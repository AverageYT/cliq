from cliq.library.playlists import PlaylistBook
from cliq.runs import PlaylistRun, Run, Stage


def test_playlist_book_roundtrip(cliq_home):
    book = PlaylistBook()
    pl = book.create("Warmup")
    pl.add("song-a", "keys", "hard")
    pl.add("song-b", "taiko", "normal")
    assert book.create("Warmup").name == "Warmup 2"          # names stay unique
    book.save()
    again = PlaylistBook()
    loaded = again.get(pl.id)
    assert [(e.song_id, e.mode, e.difficulty) for e in loaded.entries] == [("song-a", "keys", "hard"),
                                                                           ("song-b", "taiko", "normal")]
    assert loaded.move(0, 1) == 1 and loaded.entries[0].song_id == "song-b"
    again.forget_song("song-a")
    assert [e.song_id for e in PlaylistBook().get(pl.id).entries] == ["song-b"]


def test_run_progress_totals_and_shuffle(cliq_home):
    book = PlaylistBook()
    pl = book.create("Set")
    for i in range(6):
        pl.add(f"s{i}")
    run = PlaylistRun.from_playlist(pl)
    assert [s.song_id for s in run.stages] == [f"s{i}" for i in range(6)]
    seen = []
    run.bus.on("stage_end", lambda run, stage, summary: seen.append(stage.song_id))
    for i in range(6):
        assert run.position == (i + 1, 6)
        run.record({"score": 100, "accuracy": 0.9, "failed": i == 2, "full_combo": i == 0, "counts": {"miss": i}})
        assert run.advance() == (i < 5)
    assert run.finished and seen == [f"s{i}" for i in range(6)]
    tot = run.totals()
    assert tot["score"] == 600 and tot["cleared"] == 5 and tot["full_combos"] == 1 and tot["misses"] == 15
    shuffled = PlaylistRun.from_playlist(pl, shuffle=True, seed=4)
    assert sorted(s.song_id for s in shuffled.stages) == [f"s{i}" for i in range(6)]
    assert [s.song_id for s in shuffled.stages] != [f"s{i}" for i in range(6)]
    assert sorted(s.song_id for s in shuffled.again().stages) == [f"s{i}" for i in range(6)]


def test_roguelike_style_run_ends_on_fail():
    class Hardcore(Run):
        continue_on_fail = False

    run = Hardcore("hc", [Stage("a"), Stage("b"), Stage("c")], modifiers=["sudden_death"])
    run.state["coins"] = 3
    run.record({"failed": False})
    assert run.advance()
    run.record({"failed": True})
    assert not run.advance() and run.finished and run.index == 1
    assert run.modifiers_for(Stage("x", modifiers=["hidden"])) == ["sudden_death", "hidden"]
