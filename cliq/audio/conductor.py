"""The song clock.

Everything that moves with the music asks the conductor for the time. It
combines two clocks:

* ``time.perf_counter()`` - smooth and precise; anchored when playback starts.
* the mixer's sample-counted music position - the true audio clock.

The audio clock is only used to *correct drift* (sound cards run very
slightly fast or slow; over a long song that adds up). Its constant offset is
measured over the first frames and ignored, so the picture never jumps.
``audio_offset`` (player calibration) then shifts the whole chart.
"""

from __future__ import annotations

import math
import time
from statistics import median

from .engine import AudioEngine


class Conductor:
    DRIFT_TAU = 1.5          # seconds; how gently drift is corrected
    MAX_SLEW = 0.002         # max correction per second of play (real sound cards drift < 0.0001)
    HARD_RESYNC = 0.12       # a jump this big that persists...
    HARD_RESYNC_AFTER = 0.5  # ...for this long (device change, long stall) snaps to the audio clock
    MAX_PLAUSIBLE = 1.0      # bigger "jumps" mean the reported position is nonsense
    BASELINE_SAMPLES = 24

    def __init__(self, audio: AudioEngine, offset_ms: float = 0.0, sync_to_audio: bool = True):
        self.audio = audio
        self.offset = offset_ms / 1000.0
        self.sync_to_audio = sync_to_audio
        self.state = "stopped"      # stopped | waiting | playing | paused | ended
        self.duration = 0.0
        self._t0 = time.perf_counter()
        self._held = 0.0            # raw time while stopped/paused
        self._audio_start = 0.0     # raw time at which the music was started
        self._errors: list[float] = []
        self._baseline: float | None = None
        self._stuck = 0.0
        self._saturated = 0.0
        self._resyncs = 0
        self._last = time.perf_counter()
        self.drift_correction = 0.0  # total seconds corrected (debug overlay)

    # ------------------------------------------------------------ control
    def load(self, path, duration: float = 0.0) -> bool:
        self.stop()
        self.duration = duration
        return self.audio.load_music(path)

    def play(self, song_time: float = 0.0) -> None:
        """Start at ``song_time`` (seconds, may be negative for a lead-in)."""
        self._start_raw(song_time + self.offset)

    def _start_raw(self, raw: float) -> None:
        self.audio.stop_music()
        self._t0 = time.perf_counter() - raw
        self._baseline, self._errors = None, []
        if raw >= 0:
            self._begin_audio(raw)
        else:
            self.state = "waiting"

    def _begin_audio(self, raw: float) -> None:
        self.audio.play_music(start=raw)
        self._audio_start = raw
        self._t0 = time.perf_counter() - raw
        self.state = "playing"

    def pause(self) -> None:
        if self.state in ("playing", "waiting"):
            self._held = time.perf_counter() - self._t0
            self.audio.pause_music()
            self.state = "paused"

    def resume(self) -> None:
        if self.state == "paused":
            self._start_raw(self._held)

    def toggle(self) -> None:
        if self.state in ("playing", "waiting"):
            self.pause()
        elif self.state == "paused":
            self.resume()
        else:
            self.play(self.time)

    def seek(self, song_time: float) -> None:
        raw = song_time + self.offset
        if self.state in ("playing", "waiting"):
            self._start_raw(raw)
        else:
            self._held = raw
            if self.state == "ended":
                self.state = "paused"

    def stop(self) -> None:
        self.audio.stop_music()
        self._held = 0.0
        self.state = "stopped"

    @property
    def running(self) -> bool:
        return self.state in ("playing", "waiting")

    # ------------------------------------------------------------ time
    def raw_time(self, now: float | None = None) -> float:
        if self.state in ("playing", "waiting"):
            return (now if now is not None else time.perf_counter()) - self._t0
        return self._held

    @property
    def time(self) -> float:
        """Current chart time in seconds (calibration offset applied)."""
        return self.raw_time() - self.offset

    def time_at(self, perf: float) -> float:
        """Chart time for a ``perf_counter()`` timestamp (used to stamp key presses)."""
        return self.raw_time(perf) - self.offset

    def update(self) -> None:
        now = time.perf_counter()
        dt, self._last = now - self._last, now
        if self.state == "waiting":
            raw = now - self._t0
            if raw >= 0:
                self._begin_audio(raw)
            return
        if self.state != "playing":
            return
        raw = now - self._t0
        if self.duration and raw > self.duration + 0.25 and not self.audio.music_busy():
            self._held = raw
            self.state = "ended"
            return
        if not (self.sync_to_audio and self.audio.available and self.audio.music_busy()):
            return
        pos = self.audio.music_pos_ms()
        if pos <= 0:
            return
        error = (self._audio_start + pos / 1000.0) - raw
        if self._baseline is None:
            self._errors.append(error)
            if len(self._errors) >= self.BASELINE_SAMPLES:
                self._baseline = median(self._errors)
            return
        drift = error - self._baseline
        if abs(drift) > self.MAX_PLAUSIBLE:
            self.sync_to_audio = False
            return
        if abs(drift) > self.HARD_RESYNC:
            self._stuck += dt
            if self._stuck < self.HARD_RESYNC_AFTER:
                return
            self._resyncs += 1
            if self._resyncs > 2:
                # Repeated big jumps mean this driver's position runs at the wrong rate
                # (e.g. SDL's dummy driver); trust the system clock from here on.
                self.sync_to_audio = False
                return
            correction = drift
        else:
            # Gentle, rate-limited slew: a misbehaving driver can't drag the chart around.
            correction = drift * (1.0 - math.exp(-dt / self.DRIFT_TAU))
            limit = self.MAX_SLEW * dt
            if abs(correction) >= limit:
                correction = math.copysign(limit, correction)
                self._saturated += dt
                if self._saturated > 2.0:
                    # Needs more correction than any real sound card ever would: the
                    # reported position runs at the wrong rate. Keep the system clock.
                    self.sync_to_audio = False
                    return
            else:
                self._saturated = 0.0
        self._stuck = 0.0
        self._t0 -= correction
        self.drift_correction += correction
