"""Player settings, stored as JSON in ``user/settings.json``.

Add a new setting by adding a field to :class:`Settings` (with a default) and,
if it should appear in the in-game menu, an entry in :data:`SETTINGS_MENU`.
Unknown or missing keys in the JSON file are ignored/filled in, so old settings
files keep working as the game grows.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any

from . import paths
from .util import load_json, save_json

# Default key layouts per lane count. Key names use pygame.key.name() spelling.
DEFAULT_KEYBINDS: dict[str, list[str]] = {
    "4": ["d", "f", "k", "l"],
    "5": ["d", "f", "space", "k", "l"],
    "6": ["s", "d", "f", "j", "k", "l"],
    "7": ["s", "d", "f", "space", "j", "k", "l"],
}

SCROLL_DIRECTIONS = ("down", "up")
NOTE_SKINS = ("arrows", "circles", "bars")
DIFFICULTIES = ("easy", "normal", "hard", "expert")


@dataclass
class Settings:
    # --- controls
    keybinds: dict[str, list[str]] = field(default_factory=lambda: {k: list(v) for k, v in DEFAULT_KEYBINDS.items()})

    # --- gameplay
    scroll_direction: str = "down"
    scroll_speed: float = 1.6
    lane_count: int = 4
    note_skin: str = "arrows"
    lane_width: int = 104
    default_difficulty: str = "normal"
    ghost_tapping: bool = True
    anti_spam: bool = True
    no_fail: bool = False
    show_hit_error: bool = True
    show_beat_lines: bool = True
    background_dim: float = 0.3
    countdown: bool = True

    # --- audio
    music_volume: float = 0.8
    sfx_volume: float = 0.7
    hitsounds: bool = True
    hitsound_volume: float = 0.35
    audio_offset_ms: float = 0.0
    audio_buffer: int = 512
    song_preview: bool = True

    # --- display
    resolution: list[int] = field(default_factory=lambda: [1280, 720])   # classic window backend only
    render_quality: str = "auto"
    fullscreen: bool = False
    vsync: bool = False
    fps_cap: int = 480
    show_fps: bool = False

    # --- mapping editor
    editor_snap: int = 4
    editor_metronome: bool = False
    editor_assist_tick: bool = True
    editor_record: bool = True

    # --- run state (not shown in the menu)
    enabled_modifiers: list[str] = field(default_factory=list)
    last_song: str | None = None
    last_difficulty: str | None = None

    # ------------------------------------------------------------------ io
    @classmethod
    def load(cls) -> "Settings":
        raw = load_json(paths.SETTINGS_FILE, {}) or {}
        settings = cls()
        known = {f.name: f for f in dataclasses.fields(cls)}
        for key, value in raw.items():
            if key not in known:
                continue
            default = getattr(settings, key)
            if key == "keybinds" and isinstance(value, dict):
                merged = dict(default)
                merged.update({str(k): list(v) for k, v in value.items() if isinstance(v, list)})
                value = merged
            elif isinstance(default, bool):
                value = bool(value)
            elif isinstance(default, int) and not isinstance(default, bool):
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    continue
            elif isinstance(default, float):
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    continue
            setattr(settings, key, value)
        settings._sanitize()
        return settings

    def save(self) -> None:
        paths.USER_DIR.mkdir(parents=True, exist_ok=True)
        save_json(paths.SETTINGS_FILE, dataclasses.asdict(self))

    def _sanitize(self) -> None:
        if self.scroll_direction not in SCROLL_DIRECTIONS:
            self.scroll_direction = "down"
        if self.note_skin not in NOTE_SKINS:
            self.note_skin = "arrows"
        if self.default_difficulty not in DIFFICULTIES:
            self.default_difficulty = "normal"
        self.lane_count = max(4, min(7, int(self.lane_count)))
        if self.render_quality not in ("auto", "720p", "900p", "1080p", "1440p", "native"):
            self.render_quality = "auto"
        if not (isinstance(self.resolution, list) and len(self.resolution) == 2):
            self.resolution = [1280, 720]

    # ------------------------------------------------------------- helpers
    def keys_for(self, lanes: int) -> list[str]:
        keys = self.keybinds.get(str(lanes)) or DEFAULT_KEYBINDS.get(str(lanes))
        if not keys or len(keys) != lanes:
            keys = DEFAULT_KEYBINDS.get(str(lanes), DEFAULT_KEYBINDS["4"])
        return list(keys)

    def set_key(self, lanes: int, lane: int, key_name: str) -> None:
        keys = self.keys_for(lanes)
        # Swap if the key is already used by another lane so bindings stay unique.
        if key_name in keys:
            other = keys.index(key_name)
            keys[other] = keys[lane]
        keys[lane] = key_name
        self.keybinds[str(lanes)] = keys

    def get(self, key: str) -> Any:
        return getattr(self, key)

    def set(self, key: str, value: Any) -> None:
        setattr(self, key, value)


@dataclass(frozen=True)
class SettingSpec:
    """Describes how a setting appears in the settings menu."""

    key: str
    label: str
    kind: str  # "toggle" | "choice" | "number" | "action"
    section: str
    choices: tuple = ()
    lo: float = 0.0
    hi: float = 1.0
    step: float = 0.1
    fmt: str = "{:.1f}"
    help: str = ""


SETTINGS_MENU: list[SettingSpec] = [
    SettingSpec("scroll_direction", "Scroll direction", "choice", "Gameplay", choices=SCROLL_DIRECTIONS,
                help="Downscroll: notes fall to receptors at the bottom. Upscroll: they rise to the top."),
    SettingSpec("scroll_speed", "Scroll speed", "number", "Gameplay", lo=0.5, hi=5.0, step=0.1,
                help="How fast notes travel. Higher = more space between notes."),
    SettingSpec("note_skin", "Note style", "choice", "Gameplay", choices=NOTE_SKINS),
    SettingSpec("lane_width", "Lane width", "number", "Gameplay", lo=70, hi=150, step=2, fmt="{:.0f}px"),
    SettingSpec("lane_count", "Keys for new charts", "number", "Gameplay", lo=4, hi=7, step=1, fmt="{:.0f}K",
                help="Lane count used when auto-charting newly imported songs."),
    SettingSpec("default_difficulty", "Default difficulty", "choice", "Gameplay", choices=DIFFICULTIES),
    SettingSpec("ghost_tapping", "Ghost tapping", "toggle", "Gameplay",
                help="On: pressing with no note nearby is never punished."),
    SettingSpec("anti_spam", "Anti-spam", "toggle", "Gameplay",
                help="A press with no note nearby makes you miss the next note in that lane."),
    SettingSpec("no_fail", "No fail", "toggle", "Gameplay", help="Keep playing when health runs out."),
    SettingSpec("show_hit_error", "Timing bar", "toggle", "Gameplay", help="Shows how early/late each hit was."),
    SettingSpec("show_beat_lines", "Beat lines", "toggle", "Gameplay"),
    SettingSpec("countdown", "Countdown", "toggle", "Gameplay"),
    SettingSpec("background_dim", "Background dim", "number", "Gameplay", lo=0.0, hi=0.9, step=0.05,
                fmt="{:.0%}"),
    SettingSpec("keybinds", "Key bindings", "keys", "Controls"),
    SettingSpec("music_volume", "Music volume", "number", "Audio", lo=0.0, hi=1.0, step=0.05, fmt="{:.0%}"),
    SettingSpec("sfx_volume", "Effects volume", "number", "Audio", lo=0.0, hi=1.0, step=0.05, fmt="{:.0%}"),
    SettingSpec("hitsounds", "Hit sounds", "toggle", "Audio"),
    SettingSpec("hitsound_volume", "Hit sound volume", "number", "Audio", lo=0.0, hi=1.0, step=0.05,
                fmt="{:.0%}"),
    SettingSpec("audio_offset_ms", "Audio offset", "number", "Audio", lo=-300, hi=300, step=1, fmt="{:+.0f} ms",
                help="Positive if you hit late. Use Calibrate to measure it automatically."),
    SettingSpec("calibrate", "Calibrate offset...", "action", "Audio"),
    SettingSpec("audio_buffer", "Audio buffer", "choice", "Audio", choices=(256, 512, 1024, 2048),
                help="Smaller = less latency. Raise it if you hear crackling."),
    SettingSpec("song_preview", "Song previews", "toggle", "Audio"),
    SettingSpec("fullscreen", "Fullscreen", "toggle", "Display"),
    SettingSpec("render_quality", "Render quality", "choice", "Display",
                choices=("auto", "720p", "900p", "1080p", "1440p", "native"),
                help="Sharper at higher settings, but costs more CPU per frame. Restart to apply."),
    SettingSpec("vsync", "VSync", "toggle", "Display", help="Off gives the lowest input latency. Restart to apply."),
    SettingSpec("fps_cap", "FPS cap", "choice", "Display", choices=(144, 240, 360, 480, 1000)),
    SettingSpec("show_fps", "Show FPS", "toggle", "Display"),
]
