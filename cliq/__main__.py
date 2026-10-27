"""Command line entry point.

    python -m cliq                     start the game
    python -m cliq import <url|file>   add a song without opening the game
    python -m cliq analyze <file>      print the detected BPM / offset / beats
    python -m cliq list                list songs in your library
"""

from __future__ import annotations

import argparse
import sys


def _import(args) -> int:
    from . import paths
    from .library.importer import ImportFailed, import_song
    from .library.song import SongLibrary

    paths.ensure_dirs()
    last = [-1]

    def progress(f: float) -> None:
        pct = int(f * 100)
        if pct // 10 != last[0] // 10:
            last[0] = pct
            print(f"  {pct:3d}%", flush=True)

    try:
        song, existed = import_song(args.source, SongLibrary(), lanes=args.lanes, progress=progress,
                                    stage=lambda s: print(f"- {s}", flush=True))
    except ImportFailed as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1
    note = " (already in library)" if existed else ""
    print(f"{song.title} - {song.artist}{note}\n  id: {song.id}\n  {song.grid.bpm:.2f} BPM, "
          f"first beat {song.grid.offset * 1000:.0f} ms, charts: {', '.join(song.chart_names())}")
    return 0


def _analyze(args) -> int:
    from .analysis.analyzer import analyze_file
    from .charting.autochart import generate_chart
    from .charting.profiles import difficulty_ids

    a = analyze_file(args.file)
    kind = "variable" if a.beat_times is not None else "constant"
    print(f"{args.file}\n  duration {a.duration:.1f}s  bpm {a.bpm:.3f} ({kind})  first beat {a.offset * 1000:.1f} ms"
          f"  bar starts on beat {a.downbeat}  confidence {a.confidence:.2f}  onsets {len(a.onsets)}")
    for note in a.notes:
        print(f"  note: {note}")
    for diff in difficulty_ids():
        print(f"  {diff:7s} {generate_chart(a, diff).stats()}")
    return 0


def _list(args) -> int:
    from .library.song import SongLibrary

    for song in SongLibrary().scan():
        print(f"{song.id:40s} {song.grid.bpm:7.2f} BPM  {song.title} - {song.artist}  [{', '.join(song.chart_names())}]")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="cliq", description="Cliq rhythm game")
    sub = parser.add_subparsers(dest="cmd")
    p = sub.add_parser("import", help="import a YouTube link or audio file")
    p.add_argument("source")
    p.add_argument("--lanes", type=int, default=4, choices=(4, 5, 6, 7))
    p = sub.add_parser("analyze", help="detect BPM/beats of an audio file")
    p.add_argument("file")
    sub.add_parser("list", help="list songs")
    args = parser.parse_args(argv)

    if args.cmd == "import":
        return _import(args)
    if args.cmd == "analyze":
        return _analyze(args)
    if args.cmd == "list":
        return _list(args)

    from .app import App
    from .scenes.title import TitleScene

    app = App()
    app.run(TitleScene(app))
    return 0


if __name__ == "__main__":
    sys.exit(main())
