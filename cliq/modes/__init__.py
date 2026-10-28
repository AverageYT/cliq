"""Game modes. Add your own by subclassing ``GameMode`` and calling ``register_mode``
(from a file in ``mods/`` too) - it then shows up in song select."""

from __future__ import annotations

from .base import GameMode, ModeView
from .keys import KeysMode
from .path import PathMode
from .shield import ShieldMode
from .taiko import TaikoMode

MODES: dict[str, GameMode] = {}


def register_mode(mode: GameMode) -> GameMode:
    MODES[mode.id] = mode
    return mode


def get_mode(mode_id: str | None) -> GameMode:
    return MODES.get(mode_id or "keys") or MODES["keys"]


def mode_ids() -> list[str]:
    return list(MODES)


def split_stem(stem: str) -> tuple[str, str]:
    """Chart file stem -> (mode id, difficulty). Keys charts have no prefix."""
    prefix, _, rest = stem.partition("-")
    if rest and prefix in MODES and prefix != "keys":
        return prefix, rest
    return "keys", stem


for _mode in (KeysMode(), TaikoMode(), ShieldMode(), PathMode()):
    register_mode(_mode)

__all__ = ["GameMode", "ModeView", "MODES", "register_mode", "get_mode", "mode_ids", "split_stem"]
