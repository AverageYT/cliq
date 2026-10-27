"""Filesystem locations.

Everything the player creates (songs, settings, scores) lives next to the game by
default so it is easy to find and mod. Set the ``CLIQ_HOME`` environment variable
to keep user data somewhere else.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.get("CLIQ_HOME", ROOT)).expanduser().resolve()

DATA_DIR = ROOT / "data"
ASSETS_DIR = ROOT / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
SKINS_DIR = ASSETS_DIR / "skins"
SFX_DIR = ASSETS_DIR / "sfx"

SONGS_DIR = HOME / "songs"
MODS_DIR = HOME / "mods"
USER_DIR = HOME / "user"
CACHE_DIR = USER_DIR / "cache"
SETTINGS_FILE = USER_DIR / "settings.json"
SCORES_FILE = USER_DIR / "scores.json"


def ensure_dirs() -> None:
    for d in (SONGS_DIR, USER_DIR, CACHE_DIR, MODS_DIR):
        d.mkdir(parents=True, exist_ok=True)
