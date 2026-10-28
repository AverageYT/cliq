"""Backgrounds behind the notes: a song's video (synced to song time) or a still image.

The video is decoded by an ffmpeg child process on a worker thread, already
scaled, cropped and dimmed to the render size, so the game loop only wraps
the newest due frame in a Surface and blits it. A big jump in song time
(restart, editor playtest, seeking) restarts ffmpeg at the new position.
"""

from __future__ import annotations

import os
import queue
import subprocess
import threading
from pathlib import Path

import pygame

from ..audio.ffmpeg import find_ffmpeg

FPS = 30.0


class VideoStream:
    """Frames of ``path`` from ``start`` seconds on, produced by a worker thread."""

    def __init__(self, path: Path, size: tuple[int, int], start: float, dim: float):
        self.size = size
        self.start = max(0.0, start)
        self.frame_bytes = size[0] * size[1] * 3
        self.frames: queue.Queue = queue.Queue(maxsize=6)
        self.ended = False
        self.failed = False
        self._stop = threading.Event()
        w, h = size
        keep = max(0.0, min(1.0, 1.0 - dim))
        vf = (f"fps={FPS:g},scale={w}:{h}:force_original_aspect_ratio=increase:flags=bilinear,crop={w}:{h},"
              f"colorchannelmixer=rr={keep:.3f}:gg={keep:.3f}:bb={keep:.3f}")
        exe = find_ffmpeg()
        self.proc = None
        if exe is None:
            self.failed = True
            return
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self.proc = subprocess.Popen(
                [exe, "-hide_banner", "-nostdin", "-v", "error", "-ss", f"{self.start:.3f}", "-i", str(path),
                 "-an", "-sn", "-vf", vf, "-pix_fmt", "bgr24", "-f", "rawvideo", "-"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=self.frame_bytes * 2, **kwargs)
        except OSError:
            self.failed = True
            return
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        i = 0
        out = self.proc.stdout
        while not self._stop.is_set():
            buf = out.read(self.frame_bytes)
            if not buf or len(buf) < self.frame_bytes:
                break
            item = (self.start + i / FPS, buf)
            i += 1
            while not self._stop.is_set():
                try:
                    self.frames.put(item, timeout=0.1)
                    break
                except queue.Full:
                    continue
        self.ended = True

    def close(self) -> None:
        self._stop.set()
        if self.proc is not None:
            try:
                self.proc.kill()
                self.proc.wait(timeout=1)
            except Exception:
                pass
            self.proc = None


class VideoBackground:
    """Shows the video frame for song time ``t``; draws nothing before frames arrive."""

    def __init__(self, path: Path, size: tuple[int, int], dim: float = 0.5):
        self.path = Path(path)
        self.size = size
        self.dim = dim
        self.stream: VideoStream | None = None
        self.frame: pygame.Surface | None = None
        self.frame_time = -1.0
        self.last_t = None

    def _restart(self, t: float) -> None:
        if self.stream is not None:
            self.stream.close()
        self.stream = VideoStream(self.path, self.size, t, self.dim)
        self.frame_time = -1.0

    def update(self, t: float) -> None:
        if t < 0:
            t = 0.0
        jumped = self.last_t is not None and (t < self.last_t - 0.05 or t > self.last_t + 1.0)
        self.last_t = t
        if self.stream is None or jumped:
            self._restart(t)
        stream = self.stream
        if stream.failed:
            return
        newest = None
        while True:
            try:
                ft, buf = stream.frames.queue[0]
            except IndexError:
                break
            if ft > t + 0.5 / FPS:
                break
            newest = stream.frames.get_nowait()
        if newest is not None:
            self.frame_time, buf = newest
            self.frame = pygame.image.frombuffer(buf, self.size, "BGR")

    @property
    def ready(self) -> bool:
        return self.frame is not None

    def draw(self, surf: pygame.Surface) -> None:
        if self.frame is not None:
            surf.blit(self.frame, (0, 0))

    def close(self) -> None:
        if self.stream is not None:
            self.stream.close()
            self.stream = None


def image_background(path: Path, size: tuple[int, int], dim: float = 0.5) -> pygame.Surface | None:
    """A still background: cover-fit, softly blurred and dimmed."""
    try:
        raw = pygame.image.load(str(path))
    except (pygame.error, FileNotFoundError):
        return None
    w, h = size
    rw, rh = raw.get_size()
    k = max(w / rw, h / rh)
    sw, sh = max(1, int(rw * k)), max(1, int(rh * k))
    big = pygame.transform.smoothscale(raw.convert_alpha() if pygame.display.get_surface() else raw, (sw, sh))
    crop = big.subsurface(((sw - w) // 2, (sh - h) // 2, w, h)).copy()
    # Thumbnails are small; blur hides the upscale and keeps notes readable on top.
    small = pygame.transform.smoothscale(crop, (max(1, w // 6), max(1, h // 6)))
    soft = pygame.transform.smoothscale(small, (w, h))
    out = pygame.Surface(size)
    out.blit(soft, (0, 0))
    keep = int(255 * max(0.0, min(1.0, 1.0 - dim)))
    out.fill((keep, keep, keep), special_flags=pygame.BLEND_RGB_MULT)
    return out
