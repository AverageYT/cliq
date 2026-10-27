"""Audio output tuned for low latency.

* The mixer is opened with a small buffer (``settings.audio_buffer`` samples,
  512 = 11.6 ms by default) before ``pygame.init()``.
* Music streams through ``pygame.mixer.music`` (exact seeking in Ogg files and
  a sample-counted position we use to correct clock drift).
* Hit sounds are pre-loaded and fired on reserved channels so a key press is
  never kept waiting for a free channel.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pygame

from .. import paths
from .synth import SFX_BUILDERS

FREQ = 44100
SFX_CHANNELS = 6   # reserved for hit sounds / metronome


def pre_init(buffer: int) -> None:
    """Must run before pygame.init() so the mixer opens with our buffer size."""
    pygame.mixer.pre_init(FREQ, -16, 2, int(buffer))


class AudioEngine:
    def __init__(self, buffer: int = 512):
        self.buffer = int(buffer)
        self.available = False
        self.sounds: dict[str, pygame.mixer.Sound] = {}
        self.music_path: Path | None = None
        self._sfx_index = 0

    # ------------------------------------------------------------ setup
    def init(self) -> bool:
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(FREQ, -16, 2, self.buffer)
            pygame.mixer.set_num_channels(32)
            pygame.mixer.set_reserved(SFX_CHANNELS)
            self.available = True
        except pygame.error as exc:
            print(f"[cliq] audio unavailable, running silent: {exc}")
            self.available = False
        self._load_sfx()
        return self.available

    def reinit(self, buffer: int) -> None:
        """Re-open the device with a new buffer size (settings change)."""
        music = self.music_path
        if pygame.mixer.get_init():
            pygame.mixer.quit()
        self.buffer = int(buffer)
        self.sounds.clear()
        self.music_path = None
        self.init()
        if music:
            self.load_music(music)

    @property
    def latency_ms(self) -> float:
        return 1000.0 * self.buffer / FREQ

    def _load_sfx(self) -> None:
        if not self.available:
            return
        freq, size, channels = pygame.mixer.get_init()
        for name, builder in SFX_BUILDERS.items():
            sound = None
            for ext in (".wav", ".ogg", ".mp3"):
                custom = paths.SFX_DIR / f"{name}{ext}"
                if custom.exists():
                    try:
                        sound = pygame.mixer.Sound(str(custom))
                    except pygame.error:
                        sound = None
                    break
            if sound is None:
                sound = self._make_sound(builder(freq), size, channels)
            if sound is not None:
                self.sounds[name] = sound

    @staticmethod
    def _make_sound(x: np.ndarray, size: int, channels: int) -> pygame.mixer.Sound | None:
        x = np.asarray(x, dtype=np.float32)
        x = x / max(1e-9, float(np.abs(x).max())) * 0.9
        frames = np.repeat(x[:, None], channels, axis=1) if channels > 1 else x
        if size in (-16, 16):
            arr = (frames * 32767).astype(np.int16)
        elif size == 32:
            arr = frames.astype(np.float32)
        elif size in (8, -8):
            arr = ((frames * 127) + (128 if size == 8 else 0)).astype(np.uint8 if size == 8 else np.int8)
        else:
            return None
        try:
            return pygame.sndarray.make_sound(np.ascontiguousarray(arr))
        except (pygame.error, ValueError):
            return None

    # ------------------------------------------------------------ effects
    def play_sfx(self, name: str, volume: float = 1.0) -> None:
        if not self.available or volume <= 0:
            return
        sound = self.sounds.get(name)
        if sound is None:
            return
        # Round-robin over the reserved channels: no channel search on the hot path.
        channel = pygame.mixer.Channel(self._sfx_index)
        self._sfx_index = (self._sfx_index + 1) % SFX_CHANNELS
        channel.set_volume(max(0.0, min(1.0, volume)))
        channel.play(sound)

    # ------------------------------------------------------------ music
    def load_music(self, path: Path) -> bool:
        if not self.available:
            self.music_path = Path(path)
            return False
        try:
            pygame.mixer.music.load(str(path))
            self.music_path = Path(path)
            return True
        except pygame.error as exc:
            print(f"[cliq] couldn't load music {path}: {exc}")
            return False

    def play_music(self, start: float = 0.0, fade_ms: int = 0) -> None:
        if self.available and self.music_path:
            try:
                pygame.mixer.music.play(loops=0, start=max(0.0, float(start)), fade_ms=int(fade_ms))
            except pygame.error:
                pygame.mixer.music.play(loops=0)

    def pause_music(self) -> None:
        if self.available:
            pygame.mixer.music.pause()

    def stop_music(self) -> None:
        if self.available:
            pygame.mixer.music.stop()

    def fadeout_music(self, ms: int) -> None:
        if self.available:
            pygame.mixer.music.fadeout(int(ms))

    def set_music_volume(self, volume: float) -> None:
        if self.available:
            pygame.mixer.music.set_volume(max(0.0, min(1.0, volume)))

    def music_pos_ms(self) -> int:
        return pygame.mixer.music.get_pos() if self.available else -1

    def music_busy(self) -> bool:
        return bool(self.available and pygame.mixer.music.get_busy())
