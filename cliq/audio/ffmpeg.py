"""ffmpeg helpers: find the binary, decode any audio to PCM, convert for playback.

Lookup order for the binary: ``CLIQ_FFMPEG`` env var, ``ffmpeg`` on PATH, then
the static build shipped with the ``imageio-ffmpeg`` pip package (so players do
not have to install ffmpeg themselves).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

import numpy as np


class FFmpegError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def find_ffmpeg() -> str | None:
    env = os.environ.get("CLIQ_FFMPEG")
    if env and Path(env).exists():
        return env
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg  # type: ignore

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def _run(args: list[str], capture_stdout: bool = True) -> subprocess.CompletedProcess:
    exe = find_ffmpeg()
    if not exe:
        raise FFmpegError("ffmpeg was not found. Install it, or run: pip install imageio-ffmpeg")
    kwargs = {}
    if os.name == "nt":  # don't flash a console window on Windows
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run([exe, "-hide_banner", "-nostdin", *args],
                          stdout=subprocess.PIPE if capture_stdout else subprocess.DEVNULL,
                          stderr=subprocess.PIPE, **kwargs)


def decode_mono(path: str | Path, sr: int = 22050) -> np.ndarray:
    """Decode any audio/video file ffmpeg understands to mono float32 at ``sr``."""
    proc = _run(["-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"])
    if proc.returncode != 0 or not proc.stdout:
        msg = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        raise FFmpegError(f"Couldn't read audio from {Path(path).name}: {msg[-1] if msg else 'unknown error'}")
    return np.frombuffer(proc.stdout, dtype=np.float32).copy()


def convert_for_playback(src: str | Path, dst_stem: str | Path) -> Path:
    """Convert ``src`` to an Ogg Vorbis file (exact seeking in pygame); WAV as fallback."""
    dst_stem = Path(dst_stem)
    attempts = [
        (".ogg", ["-c:a", "libvorbis", "-q:a", "6"]),
        (".ogg", ["-c:a", "vorbis", "-strict", "-2", "-b:a", "192k"]),
        (".wav", ["-c:a", "pcm_s16le"]),
    ]
    last_err = ""
    for ext, codec in attempts:
        dst = dst_stem.with_suffix(ext)
        proc = _run(["-v", "error", "-y", "-i", str(src), "-vn", "-map", "0:a:0", "-ac", "2", "-ar", "44100",
                     *codec, str(dst)], capture_stdout=False)
        if proc.returncode == 0 and dst.exists() and dst.stat().st_size > 0:
            return dst
        last_err = proc.stderr.decode("utf-8", "replace").strip()
        if dst.exists():
            dst.unlink()
    raise FFmpegError(f"Couldn't convert {Path(src).name}: {last_err.splitlines()[-1] if last_err else 'unknown'}")


def encode_pcm(samples: np.ndarray, dst_stem: str | Path, sr: int = 44100) -> Path:
    """Encode float stereo samples [n, 2] to Ogg (or WAV if ffmpeg is missing)."""
    from .synth import write_wav

    dst_stem = Path(dst_stem)
    if not find_ffmpeg():
        dst = dst_stem.with_suffix(".wav")
        write_wav(dst, samples, sr)
        return dst
    tmp = dst_stem.with_suffix(".tmp.wav")
    write_wav(tmp, samples, sr)
    try:
        return convert_for_playback(tmp, dst_stem)
    finally:
        tmp.unlink(missing_ok=True)


_TAG_RE = re.compile(r"^\s{4}(title|artist|album_artist)\s*:\s*(.+)$", re.IGNORECASE)


def read_tags(path: str | Path) -> dict[str, str]:
    """Best-effort title/artist tags from a media file."""
    try:
        proc = _run(["-i", str(path)], capture_stdout=False)
    except FFmpegError:
        return {}
    tags: dict[str, str] = {}
    for line in proc.stderr.decode("utf-8", "replace").splitlines():
        m = _TAG_RE.match(line)
        if m and m.group(1).lower() not in tags:
            tags[m.group(1).lower()] = m.group(2).strip()
    if "artist" not in tags and "album_artist" in tags:
        tags["artist"] = tags["album_artist"]
    return tags


def extract_video(src: str | Path, dst_stem: str | Path) -> Path | None:
    """Copy the first real video stream (not embedded cover art) of ``src``, without audio.

    No re-encode: the container is chosen to fit whatever codec is inside.
    Returns None if the file has no video.
    """
    dst_stem = Path(dst_stem)
    for ext in (".mp4", ".mkv"):
        dst = dst_stem.with_suffix(ext)
        proc = _run(["-v", "error", "-y", "-i", str(src), "-map", "0:V:0", "-an", "-sn", "-c:v", "copy", str(dst)],
                    capture_stdout=False)
        if proc.returncode == 0 and dst.exists() and dst.stat().st_size > 1024:
            return dst
        dst.unlink(missing_ok=True)
    return None


def video_size(path: str | Path) -> tuple[int, int] | None:
    """(width, height) of the first video stream, from ffmpeg's banner."""
    try:
        proc = _run(["-i", str(path)], capture_stdout=False)
    except FFmpegError:
        return None
    for line in proc.stderr.decode("utf-8", "replace").splitlines():
        if "Video:" in line and "attached pic" not in line:
            m = re.search(r"\b(\d{2,5})x(\d{2,5})\b", line)
            if m:
                return int(m.group(1)), int(m.group(2))
    return None
