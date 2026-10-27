"""Audio offset calibration: tap along to a click track; the median timing
error is your system's audio + input latency."""

from __future__ import annotations

import statistics
import time

import pygame

from .. import paths
from ..audio import synth
from ..audio.conductor import Conductor
from ..audio.ffmpeg import encode_pcm
from ..render.fx import pulse
from ..render.widgets import panel
from ..util import darken, lighten
from .base import Scene

BPM = 120.0
BEATS = 64
LEAD_IN = 0.5
WARMUP_BEATS = 4


def click_track_path():
    for ext in (".ogg", ".wav"):
        p = paths.CACHE_DIR / f"calibration-{int(BPM)}{ext}"
        if p.exists():
            return p
    stereo, _ = synth.render_click_track(BPM, BEATS, LEAD_IN)
    paths.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return encode_pcm(stereo, paths.CACHE_DIR / f"calibration-{int(BPM)}")


class CalibrationScene(Scene):
    key_repeat = None
    menu_music = False

    def __init__(self, app):
        super().__init__(app)
        self.beat_len = 60.0 / BPM
        self.beats = [LEAD_IN + i * self.beat_len for i in range(BEATS)]
        self.errors: list[float] = []
        self.conductor = Conductor(app.audio, offset_ms=0.0)
        self.panel_img = panel((self.s(820), self.s(470)), self.ui)
        self.flash = 9.0

    def enter(self) -> None:
        self.conductor.load(click_track_path(), duration=LEAD_IN + BEATS * self.beat_len + 1.0)
        self.app.audio.set_music_volume(self.app.settings.music_volume)
        self.conductor.play(-1.0)

    def leave(self) -> None:
        self.conductor.stop()

    @property
    def median_ms(self) -> float | None:
        return statistics.median(self.errors) * 1000.0 if len(self.errors) >= 3 else None

    def apply(self) -> None:
        if len(self.errors) < 8:
            self.app.toasts.show("Tap at least 8 times first", self.theme.c("bad"))
            return
        value = round(self.median_ms)
        self.app.settings.audio_offset_ms = float(max(-300, min(300, value)))
        self.app.settings.save()
        self.app.toasts.show(f"Audio offset set to {value:+d} ms", self.theme.c("good"))
        self.app.pop()

    def handle_event(self, e) -> None:
        if e.type != pygame.KEYDOWN:
            if e.type == pygame.MOUSEBUTTONDOWN:
                self._tap()
            return
        if e.key == pygame.K_ESCAPE:
            self.app.pop()
        elif e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self.apply()
        elif e.key == pygame.K_BACKSPACE:
            self.errors.clear()
            self.conductor.play(-1.0)
        else:
            self._tap()

    def _tap(self) -> None:
        t = self.conductor.time_at(time.perf_counter())
        i = min(range(len(self.beats)), key=lambda j: abs(self.beats[j] - t))
        err = t - self.beats[i]
        self.flash = 0.0
        if i >= WARMUP_BEATS and abs(err) < self.beat_len * 0.45:
            self.errors.append(err)
            self.errors = self.errors[-40:]

    def update(self, dt: float) -> None:
        self.conductor.update()
        self.flash += dt
        if self.conductor.state == "ended":
            self.conductor.play(-0.5)
        self.app.background.update(dt, (self.conductor.time - LEAD_IN) / self.beat_len)

    def draw(self, surf) -> None:
        self.app.background.draw(surf)
        theme = self.theme
        w, h = self.size
        self.title(surf, "Calibrate audio offset", 60, 50)
        r = self.panel_img.get_rect(center=(w // 2, self.s(380)))
        surf.blit(self.panel_img, r)
        t = self.conductor.time
        beat = (t - LEAD_IN) / self.beat_len
        lines = ["Tap any key (or click) exactly on every click you HEAR.",
                 "Don't watch the circle - listen. Enter saves, Backspace restarts, Esc cancels."]
        for i, line in enumerate(lines):
            self.fonts.draw(surf, line, (w // 2, r.y + self.s(32) + i * self.s(30)), "bold", 21,
                            (255, 255, 255) if i == 0 else theme.c("text_dim"), anchor="midtop", outline=2)
        # metronome blob
        p = pulse(beat % 1.0, 8.0) if beat >= 0 else 0.0
        radius = self.s(58) * (1.0 + 0.22 * p)
        cx, cy = w // 2, r.y + self.s(190)
        accent = int(round(beat)) % 4 == 0
        color = theme.c("accent2") if accent else theme.c("accent3")
        pygame.draw.circle(surf, theme.c("ink"), (cx, cy), radius + self.s(5))
        pygame.draw.circle(surf, lighten(color, 0.4 * p), (cx, cy), radius)
        pygame.draw.circle(surf, lighten(color, 0.6), (cx - radius * 0.35, cy - radius * 0.35), radius * 0.18)
        if self.flash < 0.15:
            pygame.draw.circle(surf, (255, 255, 255), (cx, cy), radius + self.s(14) * (1 - self.flash / 0.15),
                               max(2, self.s(4)))
        # error strip
        strip = pygame.Rect(0, 0, self.s(620), self.s(28))
        strip.center = (w // 2, r.y + self.s(320))
        pygame.draw.rect(surf, theme.c("ink"), strip.inflate(self.s(6), self.s(6)), border_radius=self.s(12))
        pygame.draw.rect(surf, darken(theme.c("panel"), 0.2), strip, border_radius=self.s(10))
        span = 150.0
        pygame.draw.line(surf, (255, 255, 255), (strip.centerx, strip.y - self.s(6)),
                         (strip.centerx, strip.bottom + self.s(6)), 2)
        for i, err in enumerate(self.errors):
            x = strip.centerx + max(-1.0, min(1.0, err * 1000 / span)) * strip.width / 2
            newest = i == len(self.errors) - 1
            col = theme.c("accent2") if newest else lighten(theme.c("accent3"), 0.2)
            pygame.draw.rect(surf, col, (x - 1, strip.y + self.s(3), max(2, self.s(4 if newest else 3)),
                                         strip.height - self.s(6)))
        self.fonts.draw(surf, "early", (strip.x, strip.bottom + self.s(8)), "bold", 16, theme.c("text_dim"))
        self.fonts.draw(surf, "late", (strip.right, strip.bottom + self.s(8)), "bold", 16, theme.c("text_dim"),
                        anchor="topright")
        med = self.median_ms
        if med is None:
            text = f"Taps counted: {len(self.errors)}"
        else:
            spread = statistics.pstdev(self.errors) * 1000.0
            text = f"Taps {len(self.errors)}  -  your offset {med:+.0f} ms  -  consistency +/-{spread:.0f} ms"
        self.fonts.draw(surf, text, (w // 2, r.bottom - self.s(54)), "display", 26, (255, 255, 255),
                        anchor="center", outline=3, shadow=3)
        current = self.app.settings.audio_offset_ms
        self.fonts.draw(surf, f"Current setting: {current:+.0f} ms", (w // 2, r.bottom + self.s(28)), "bold", 19,
                        theme.c("text_dim"), anchor="center", outline=2)
