"""Turn a YouTube link or an audio file into a playable song folder.

``import_song`` does the work synchronously (used by the CLI and tests);
``ImportJob`` runs it on a background thread so the UI stays responsive.

Stages: download (URLs only) -> convert to Ogg -> analyse beats -> auto-chart
every difficulty -> write song.json.
"""

from __future__ import annotations

import shutil
import threading
import traceback
from pathlib import Path

import numpy as np

from .. import paths
from ..analysis import features as F
from ..analysis.analyzer import analyze_signal
from ..audio import ffmpeg, youtube
from ..charting.autochart import generate_chart
from ..charting.profiles import difficulty_ids
from .song import Song, SongLibrary, now


class ImportFailed(Exception):
    """A user-facing import failure (message is shown in the UI)."""


class Cancelled(Exception):
    pass


AUDIO_EXTS = {".mp3", ".ogg", ".oga", ".wav", ".flac", ".m4a", ".aac", ".opus", ".wma", ".aif", ".aiff",
              ".mp4", ".webm", ".mkv", ".mov", ".avi", ".wv", ".ape"}


def clean_path(text: str) -> Path:
    text = text.strip().strip("\"'")
    if text.lower().startswith("file://"):
        from urllib.parse import unquote, urlparse

        text = unquote(urlparse(text).path)
        if len(text) > 2 and text[0] == "/" and text[2] == ":":  # file:///C:/...
            text = text[1:]
    return Path(text).expanduser()


def pick_preview(analysis) -> float:
    """Start of the most energetic 12 s, snapped to a measure line."""
    fps, rms = analysis.fps, analysis.rms.astype(np.float64)
    win = int(12 * fps)
    if len(rms) <= win:
        return 0.0
    c = np.concatenate([[0.0], np.cumsum(rms)])
    energy = c[win:] - c[:-win]
    # prefer the middle of the song a little (avoid outros)
    pos = np.arange(len(energy)) / len(energy)
    energy = energy * (1.0 - 0.25 * np.abs(pos - 0.45))
    t = float(np.argmax(energy)) / fps
    grid = analysis.grid()
    return max(0.0, grid.measure_step(t + 0.01, -1))


BACKGROUNDS = ("video720", "video1080", "image", "none")
BACKGROUND_LABELS = {"video720": "Video 720p", "video1080": "Video 1080p", "image": "Thumbnail", "none": "Nothing"}


def import_song(source: str, library: SongLibrary | None = None, lanes: int = 4, difficulties=None,
                title: str | None = None, artist: str | None = None, progress=None, cancelled=None,
                stage=None, background: str = "image") -> tuple[Song, bool]:
    """Import ``source`` (URL or file path). Returns (song, already_existed).

    ``background`` picks what plays behind the notes: ``video720``/``video1080``
    (the video track, downloaded or copied from a local video file), ``image``
    (the thumbnail / album art) or ``none``.
    """
    library = library or SongLibrary()
    difficulties = difficulties or difficulty_ids()
    report = progress or (lambda f: None)
    set_stage = stage or (lambda s: None)

    def check_cancel():
        if cancelled and cancelled():
            raise Cancelled()

    source = source.strip()
    if not source:
        raise ImportFailed("Paste a YouTube link or choose an audio file first.")

    work = paths.CACHE_DIR / f"import-{threading.get_ident()}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    thumb = None
    video = None
    want_video = background.startswith("video")
    try:
        if youtube.is_url(source):
            url = youtube.normalize_url(source)
            set_stage("Downloading audio")
            share = 0.3 if want_video else 0.4
            try:
                res = youtube.download_audio(url, work, progress=lambda f: report(share * f), cancelled=cancelled)
            except youtube.DownloadCancelled as exc:
                raise Cancelled() from exc
            except youtube.DownloadFailed as exc:
                raise ImportFailed(str(exc)) from exc
            key = res.key
            existing = library.find_by_source(key)
            if existing:
                return existing, True
            media, thumb = res.path, res.thumbnail
            if want_video:
                set_stage("Downloading video")
                height = 1080 if background == "video1080" else 720
                try:
                    video = youtube.download_video(url, work, height, progress=lambda f: report(0.3 + 0.1 * f),
                                                   cancelled=cancelled)
                except youtube.DownloadCancelled as exc:
                    raise Cancelled() from exc
                except youtube.DownloadFailed:
                    video = None        # not fatal: fall back to the thumbnail
            title = title or res.title
            artist = artist or res.artist
            src_info = {"type": "url", "url": res.url, "key": key}
        else:
            path = clean_path(source)
            if not path.exists():
                raise ImportFailed(f"File not found: {path}")
            if path.is_dir():
                raise ImportFailed("That's a folder - pick an audio file instead.")
            if path.suffix.lower() not in AUDIO_EXTS:
                raise ImportFailed(f"Unsupported file type '{path.suffix}'. Try mp3, ogg, wav, flac, m4a or opus.")
            key = f"file:{path.name}:{path.stat().st_size}"
            existing = library.find_by_source(key)
            if existing:
                return existing, True
            tags = ffmpeg.read_tags(path)
            media = path
            title = title or tags.get("title") or path.stem.replace("_", " ")
            artist = artist or tags.get("artist") or "Unknown artist"
            src_info = {"type": "file", "name": path.name, "key": key}
        check_cancel()

        song_id = library.new_id(title, key)
        folder = library.root / song_id
        folder.mkdir(parents=True, exist_ok=True)
        try:
            set_stage("Converting audio")
            report(0.42)
            try:
                audio_path = ffmpeg.convert_for_playback(media, folder / "audio")
            except ffmpeg.FFmpegError as exc:
                raise ImportFailed(str(exc)) from exc
            check_cancel()

            set_stage("Finding the beat")
            report(0.5)
            try:
                y = ffmpeg.decode_mono(audio_path, F.SR)
            except ffmpeg.FFmpegError as exc:
                raise ImportFailed(str(exc)) from exc
            if len(y) < F.SR * 3 or float(np.max(np.abs(y))) < 1e-3:
                raise ImportFailed("That audio is too short or silent to chart.")
            analysis = analyze_signal(y, F.SR, progress=lambda f: report(0.5 + 0.35 * f))
            analysis.save(folder / "analysis.npz")
            check_cancel()

            set_stage("Writing charts")
            song = Song(id=song_id, folder=folder, title=title.strip() or "Untitled",
                        artist=(artist or "").strip() or "Unknown artist", audio=audio_path.name,
                        duration=analysis.duration, grid=analysis.grid(), preview=pick_preview(analysis),
                        source=src_info, created=now(), lanes=lanes,
                        extra={"confidence": round(analysis.confidence, 3),
                               "variable_tempo": analysis.beat_times is not None})
            seed = sum(map(ord, song_id)) % 10007
            for i, diff in enumerate(difficulties):
                chart = generate_chart(analysis, diff, lanes=lanes, grid=song.grid, seed=seed)
                song.save_chart(chart)
                report(0.85 + 0.13 * (i + 1) / len(difficulties))

            cover = _save_cover(thumb, media, folder)
            song.cover = cover.name if cover else None
            if want_video:
                set_stage("Saving video")
                try:
                    clip = video and ffmpeg.extract_video(video, folder / "background")
                    clip = clip or (None if video else ffmpeg.extract_video(media, folder / "background"))
                except ffmpeg.FFmpegError:
                    clip = None
                if clip is not None:
                    song.background = {"type": "video", "file": clip.name}
            if not song.background and background != "none" and cover is not None:
                song.background = {"type": "image", "file": cover.name}
            if background == "none":
                song.background = {"type": "none"}
            song.save()
            library.songs.insert(0, song)
            report(1.0)
            set_stage("Done")
            return song, False
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)
            raise
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _save_cover(thumb: Path | None, media: Path, folder: Path) -> Path | None:
    dst = folder / "cover.jpg"
    if thumb and thumb.exists():
        shutil.copyfile(thumb, dst)
        return dst
    # embedded album art in local files
    try:
        proc = ffmpeg._run(["-v", "error", "-y", "-i", str(media), "-map", "0:v:0", "-frames:v", "1",
                            "-vf", "scale=360:-2", str(dst)], capture_stdout=False)
        if proc.returncode == 0 and dst.exists() and dst.stat().st_size > 0:
            return dst
    except ffmpeg.FFmpegError:
        pass
    dst.unlink(missing_ok=True)
    return None


def install_demo_song(library: SongLibrary, lanes: int = 4) -> Song | None:
    """Synthesize and import the bundled demo track (first launch)."""
    from ..audio import synth

    if library.find_by_source("demo:cliq-starter"):
        return None
    samples, info = synth.render_demo_song()
    work = paths.CACHE_DIR / "demo"
    work.mkdir(parents=True, exist_ok=True)
    audio = ffmpeg.encode_pcm(samples, work / "cliq-starter")
    try:
        song, _ = import_song(str(audio), library, lanes=lanes, title=info["title"], artist=info["artist"])
    finally:
        audio.unlink(missing_ok=True)
    song.source = {"type": "demo", "key": "demo:cliq-starter"}
    song.save()
    return song


class ImportJob(threading.Thread):
    """Background import with progress for the UI."""

    def __init__(self, source: str, library: SongLibrary, lanes: int = 4, background: str = "image"):
        super().__init__(daemon=True)
        self.source = source
        self.background = background
        self.library = library
        self.lanes = lanes
        self.progress = 0.0
        self.stage = "Starting"
        self.error: str | None = None
        self.song: Song | None = None
        self.already_existed = False
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    @property
    def done(self) -> bool:
        return not self.is_alive()

    def _progress(self, f: float) -> None:
        self.progress = max(self.progress, min(1.0, f))

    def _stage(self, s: str) -> None:
        self.stage = s

    def run(self) -> None:
        try:
            self.song, self.already_existed = import_song(
                self.source, self.library, lanes=self.lanes, progress=self._progress,
                cancelled=self._cancel.is_set, stage=self._stage,
                background=self.background)
        except Cancelled:
            self.error = "Import cancelled."
        except ImportFailed as exc:
            self.error = str(exc)
        except Exception as exc:  # unexpected: keep the game alive, show a short message
            traceback.print_exc()
            self.error = f"Import failed: {exc}"
