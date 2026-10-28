"""Download audio from YouTube (or any site yt-dlp supports).

YouTube needs two extras besides yt-dlp itself:
  * ``yt-dlp[default]`` - bundles the challenge solver scripts (yt-dlp-ejs)
  * a JavaScript runtime - ``pip install deno`` is the easiest, Node/Bun also work
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from .ffmpeg import find_ffmpeg

MAX_DURATION_S = 20 * 60

_URL_RE = re.compile(r"^(https?://|www\.|youtu\.?be|m\.youtube|music\.youtube)", re.IGNORECASE)


class DownloadCancelled(Exception):
    pass


class DownloadFailed(Exception):
    pass


@dataclass
class DownloadResult:
    path: Path
    title: str
    artist: str
    video_id: str
    url: str
    duration: float
    thumbnail: Path | None
    extractor: str = "url"

    @property
    def key(self) -> str:
        """Stable id used to spot songs that were already imported."""
        return f"{self.extractor.lower()}:{self.video_id or self.url}"


class _SilentLogger:
    """Keeps yt-dlp from printing to the console; errors still raise."""

    def debug(self, msg: str) -> None:
        pass

    info = warning = debug

    def error(self, msg: str) -> None:
        pass


def is_url(text: str) -> bool:
    return bool(_URL_RE.match(text.strip()))


def normalize_url(text: str) -> str:
    text = text.strip().strip("<>\"'")
    if not re.match(r"^https?://", text, re.IGNORECASE):
        text = "https://" + text
    return text


def js_runtimes() -> dict:
    """JavaScript runtimes yt-dlp may use for YouTube's player challenges."""
    runtimes: dict = {}
    try:
        import deno  # type: ignore  # `pip install deno` ships the binary

        path = deno.find_deno_bin()
        if path:
            runtimes["deno"] = {"path": str(path)}
    except Exception:
        pass
    if "deno" not in runtimes and shutil.which("deno"):
        runtimes["deno"] = {}
    for name, exe in (("node", "node"), ("bun", "bun")):
        if shutil.which(exe):
            runtimes[name] = {}
    return runtimes


def friendly_error(err: BaseException) -> str:
    text = str(err)
    low = text.lower()
    if "sign in to confirm" in low or "not a bot" in low:
        return "YouTube asked for a sign-in check. Try again later, or update yt-dlp: pip install -U \"yt-dlp[default]\""
    if "unsupported url" in low:
        return "That link isn't something yt-dlp can download."
    if "video unavailable" in low or "private video" in low:
        return "That video is unavailable (private, removed or region-locked)."
    if "challenge" in low or "javascript" in low or "js runtime" in low or "n challenge" in low:
        return "YouTube needs a JavaScript runtime. Run: pip install deno   (and pip install -U \"yt-dlp[default]\")"
    if any(s in low for s in ("getaddrinfo", "name or service", "timed out", "connection", "network is unreachable",
                              "403", "proxy")):
        return "Couldn't reach the site. Check your internet connection and try again."
    if "http error 404" in low or "not found" in low:
        return "Nothing was found at that link (404)."
    if "requested format is not available" in low:
        return "No downloadable audio found. Updating yt-dlp usually fixes this: pip install -U \"yt-dlp[default]\""
    first = text.strip().splitlines()[0] if text.strip() else type(err).__name__
    return re.sub(r"^ERROR:\s*", "", first)[:220]


def download_audio(url: str, out_dir: Path, progress=None, cancelled=None) -> DownloadResult:
    """Download the best audio stream of ``url`` into ``out_dir``."""
    try:
        import yt_dlp  # type: ignore
    except ImportError as exc:
        raise DownloadFailed("YouTube import needs yt-dlp. Run: pip install \"yt-dlp[default]\" deno") from exc

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    url = normalize_url(url)

    def hook(d: dict) -> None:
        if cancelled and cancelled():
            raise DownloadCancelled()
        if progress and d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            if total:
                progress(min(1.0, done / total))
        elif progress and d.get("status") == "finished":
            progress(1.0)

    def too_long(info, *, incomplete=False):
        duration = info.get("duration")
        if duration and duration > MAX_DURATION_S:
            return f"Video is longer than {MAX_DURATION_S // 60} minutes"
        return None

    opts = {
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": {"default": str(out_dir / "source.%(ext)s")},
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "progress_hooks": [hook],
        "logger": _SilentLogger(),
        "match_filter": too_long,
        "writethumbnail": True,
        "socket_timeout": 20,
        "retries": 3,
        "postprocessors": [{"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"}],
    }
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        opts["ffmpeg_location"] = ffmpeg
    else:
        opts.pop("postprocessors")
    runtimes = js_runtimes()
    if runtimes:
        opts["js_runtimes"] = runtimes

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except DownloadCancelled:
        raise
    except Exception as exc:  # yt-dlp wraps everything in DownloadError
        if isinstance(getattr(exc, "exc_info", (None, None))[1], DownloadCancelled) or "DownloadCancelled" in repr(exc):
            raise DownloadCancelled() from exc
        raise DownloadFailed(friendly_error(exc)) from exc
    if info is None:
        raise DownloadFailed("Video was skipped (it may be longer than 20 minutes).")
    if info.get("entries"):
        info = next(e for e in info["entries"] if e)

    path = None
    for dl in info.get("requested_downloads") or []:
        if dl.get("filepath"):
            path = Path(dl["filepath"])
    if path is None or not path.exists():
        found = [p for p in out_dir.glob("source.*") if p.suffix.lower() not in (".jpg", ".png", ".webp", ".part")]
        if not found:
            raise DownloadFailed("Download finished but no audio file was produced.")
        path = found[0]
    thumb = next((p for p in (out_dir / "source.jpg", out_dir / "source.png", out_dir / "source.webp")
                  if p.exists()), None)
    artist = info.get("artist") or info.get("creator") or info.get("uploader") or info.get("channel") or ""
    artist = re.sub(r"\s*-\s*Topic$", "", str(artist))
    return DownloadResult(path=path, title=str(info.get("track") or info.get("title") or "YouTube audio"),
                          artist=artist, video_id=str(info.get("id") or ""), url=str(info.get("webpage_url") or url),
                          duration=float(info.get("duration") or 0.0), thumbnail=thumb,
                          extractor=str(info.get("extractor_key") or info.get("extractor") or "url"))


def download_video(url: str, out_dir: Path, max_height: int = 720, progress=None, cancelled=None) -> Path:
    """Download a video-only stream (no audio) up to ``max_height`` for the gameplay background.

    Prefers H.264/mp4 (cheapest to decode), then any codec, then a combined
    stream when the site has no separate video track.
    """
    try:
        import yt_dlp  # type: ignore
    except ImportError as exc:
        raise DownloadFailed("Video backgrounds need yt-dlp. Run: pip install \"yt-dlp[default]\"") from exc

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    h = int(max_height)

    def hook(d: dict) -> None:
        if cancelled and cancelled():
            raise DownloadCancelled()
        if progress and d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if total:
                progress(min(1.0, (d.get("downloaded_bytes") or 0) / total))

    opts = {
        "format": (f"bestvideo[height<={h}][vcodec^=avc1]/bestvideo[height<={h}][ext=mp4]/bestvideo[height<={h}]"
                   f"/best[height<={h}]/best"),
        "outtmpl": {"default": str(out_dir / "video.%(ext)s")},
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "progress_hooks": [hook],
        "logger": _SilentLogger(),
        "socket_timeout": 20,
        "retries": 3,
    }
    runtimes = js_runtimes()
    if runtimes:
        opts["js_runtimes"] = runtimes
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(normalize_url(url), download=True)
    except DownloadCancelled:
        raise
    except Exception as exc:
        if "DownloadCancelled" in repr(exc):
            raise DownloadCancelled() from exc
        raise DownloadFailed(friendly_error(exc)) from exc
    if info and info.get("entries"):
        info = next(e for e in info["entries"] if e)
    for dl in (info or {}).get("requested_downloads") or []:
        if dl.get("filepath") and Path(dl["filepath"]).exists():
            return Path(dl["filepath"])
    found = [p for p in out_dir.glob("video.*") if p.suffix.lower() != ".part"]
    if not found:
        raise DownloadFailed("No video stream was downloaded.")
    return found[0]
