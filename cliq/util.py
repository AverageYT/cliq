"""Small helpers shared across the codebase."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import unicodedata
from pathlib import Path
from typing import Any


def clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def approach(current: float, target: float, rate: float, dt: float) -> float:
    """Frame-rate independent exponential smoothing toward ``target``."""
    return target + (current - target) * math.exp(-rate * dt)


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def mix(c1, c2, t: float) -> tuple[int, int, int]:
    """Blend two RGB colours."""
    return tuple(int(round(lerp(a, b, t))) for a, b in zip(c1[:3], c2[:3]))


def lighten(c, t: float) -> tuple[int, int, int]:
    return mix(c, (255, 255, 255), t)


def darken(c, t: float) -> tuple[int, int, int]:
    return mix(c, (0, 0, 0), t)


def slugify(text: str, max_len: int = 40) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return (text[:max_len].strip("-")) or "song"


def short_hash(text: str, n: int = 6) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:n]


def format_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def load_json(path: Path, default: Any = None) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def save_json(path: Path, data: Any, indent: int | None = 2) -> None:
    """Write JSON atomically so a crash never leaves a half-written file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=indent, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
