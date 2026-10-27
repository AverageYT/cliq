"""Procedural audio: hit/UI sounds, metronome clicks and the bundled demo song.

Everything is synthesised with numpy at startup, so the repository ships no
binary audio. Drop WAV/OGG files named like the keys in ``SFX_BUILDERS`` into
``assets/sfx/`` to replace any of the generated sounds.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

SR = 44100


# --------------------------------------------------------------------------- basics
def _t(dur: float, sr: int = SR) -> np.ndarray:
    return np.arange(max(1, int(round(dur * sr)))) / sr


def midi_hz(m: float) -> float:
    return 440.0 * 2.0 ** ((m - 69.0) / 12.0)


def band_noise(n: int, lo: float, hi: float, sr: int = SR, rng: np.random.Generator | None = None) -> np.ndarray:
    """White noise band-limited with an FFT mask (fast and dependency free)."""
    rng = rng or np.random.default_rng(7)
    x = rng.standard_normal(n)
    spec = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    # soft edges avoid ringing
    mask = np.clip((freqs - lo * 0.8) / (lo * 0.2 + 1e-9), 0, 1) * np.clip((hi * 1.2 - freqs) / (hi * 0.2), 0, 1)
    y = np.fft.irfft(spec * mask, n)
    return y / (np.abs(y).max() + 1e-9)


def _fade(x: np.ndarray, attack: float = 0.002, release: float = 0.01, sr: int = SR) -> np.ndarray:
    a = min(len(x), max(1, int(attack * sr)))
    r = min(len(x), max(1, int(release * sr)))
    x = x.copy()
    x[:a] *= np.linspace(0, 1, a)
    x[-r:] *= np.linspace(1, 0, r)
    return x


def additive(freq: float, dur: float, harmonics: int = 8, tilt: float = 1.0, odd_only: bool = False,
             decay: float | None = None, harmonic_decay: float = 0.0, sr: int = SR, vibrato: float = 0.0) -> np.ndarray:
    """Band-limited additive oscillator (saw/square-ish) with optional per-harmonic decay."""
    t = _t(dur, sr)
    out = np.zeros_like(t)
    phase_mod = 0.0
    if vibrato:
        depth = np.clip((t - 0.15) / 0.2, 0, 1) * vibrato
        phase_mod = np.cumsum(2 ** (depth * np.sin(2 * np.pi * 5.5 * t) / 12.0) - 1.0) / sr
    for h in range(1, harmonics + 1):
        if odd_only and h % 2 == 0:
            continue
        f = freq * h
        if f > sr * 0.45:
            break
        amp = 1.0 / (h ** tilt)
        part = np.sin(2 * np.pi * f * (t + phase_mod))
        if harmonic_decay:
            part *= np.exp(-t * harmonic_decay * h)
        out += amp * part
    if decay:
        out *= np.exp(-t / decay)
    return out / (np.abs(out).max() + 1e-9)


# --------------------------------------------------------------------------- drums
def kick(sr: int = SR) -> np.ndarray:
    t = _t(0.42, sr)
    freq = 46 + 115 * np.exp(-t / 0.04)
    body = np.sin(2 * np.pi * np.cumsum(freq) / sr) * np.exp(-t / 0.2)
    click = band_noise(len(t), 1500, 9000, sr) * np.exp(-t / 0.004) * 0.3
    return _fade(body + click, attack=0.0005, release=0.03, sr=sr)


def clap(sr: int = SR, seed: int = 3) -> np.ndarray:
    t = _t(0.3, sr)
    noise = band_noise(len(t), 900, 5200, sr, np.random.default_rng(seed))
    env = np.exp(-t / 0.11) * 0.7
    for start in (0.0, 0.011, 0.022):
        env += np.where(t >= start, np.exp(-(t - start) / 0.006), 0)
    return _fade(noise * env / env.max(), attack=0.0005, release=0.02, sr=sr)


def hat(open_: bool = False, sr: int = SR, seed: int = 5) -> np.ndarray:
    t = _t(0.35 if open_ else 0.08, sr)
    noise = band_noise(len(t), 7000, 16000, sr, np.random.default_rng(seed))
    return _fade(noise * np.exp(-t / (0.12 if open_ else 0.018)), attack=0.0003, sr=sr)


def crash(sr: int = SR) -> np.ndarray:
    t = _t(2.2, sr)
    noise = band_noise(len(t), 2500, 16000, sr, np.random.default_rng(11))
    return _fade(noise * np.exp(-t / 0.7), attack=0.0005, release=0.2, sr=sr)


def click(freq: float = 1700.0, sr: int = SR) -> np.ndarray:
    """Sharp metronome click with an instant attack (used for calibration)."""
    t = _t(0.06, sr)
    tone = np.sin(2 * np.pi * freq * t) * np.exp(-t / 0.012)
    tick = band_noise(len(t), 3000, 12000, sr) * np.exp(-t / 0.002) * 0.5
    return _fade(tone + tick, attack=0.0002, release=0.01, sr=sr)


# --------------------------------------------------------------------------- tonal voices
def bass_note(freq: float, dur: float, sr: int = SR) -> np.ndarray:
    x = additive(freq, dur, harmonics=10, tilt=1.15, harmonic_decay=1.5, sr=sr)
    x += 0.8 * np.sin(2 * np.pi * freq * _t(dur, sr))
    t = _t(dur, sr)
    x *= 0.55 + 0.45 * np.exp(-t / 0.12)
    return _fade(x / np.abs(x).max(), attack=0.003, release=0.03, sr=sr)


def pluck(freq: float, dur: float = 0.35, sr: int = SR) -> np.ndarray:
    x = additive(freq, dur, harmonics=12, tilt=1.0, harmonic_decay=4.0, decay=0.16, sr=sr)
    return _fade(x, attack=0.001, release=0.03, sr=sr)


def lead(freq: float, dur: float, sr: int = SR) -> np.ndarray:
    x = additive(freq, dur, harmonics=9, tilt=1.0, odd_only=True, vibrato=0.25, sr=sr)
    return _fade(x, attack=0.008, release=0.06, sr=sr)


def pad(freqs: list[float], dur: float, sr: int = SR) -> np.ndarray:
    x = np.zeros(len(_t(dur, sr)))
    for f in freqs:
        for detune in (-0.004, 0.004):
            x += additive(f * (1 + detune), dur, harmonics=6, tilt=1.4, sr=sr)
    return _fade(x / np.abs(x).max(), attack=0.35, release=0.4, sr=sr)


# --------------------------------------------------------------------------- demo song
DEMO_BPM = 128.0
DEMO_FIRST_BEAT = 0.6  # seconds of silence before beat 0 (exercises offset detection)
DEMO_TITLE = "Cliq Starter"
DEMO_ARTIST = "Cliq Synth Band"

_CHORDS = [  # A minor: Am F C G (midi notes)
    (57, 60, 64), (53, 57, 60), (48, 52, 55), (55, 59, 62),
]
_MELODY = [  # (beat in bar, midi, length in beats), one bar per chord
    [(0, 69, 0.5), (0.5, 72, 0.5), (1, 76, 1.0), (2, 74, 0.5), (2.5, 72, 0.5), (3, 69, 1.0)],
    [(0, 72, 1.5), (1.5, 69, 0.5), (2, 65, 1.0), (3, 69, 1.0)],
    [(0, 67, 0.5), (0.5, 72, 0.5), (1, 76, 1.5), (2.5, 74, 0.5), (3, 72, 1.0)],
    [(0, 71, 1.0), (1, 74, 1.0), (2, 79, 1.5), (3.5, 76, 0.5)],
]


def render_demo_song(sr: int = SR) -> tuple[np.ndarray, dict]:
    """Render the bundled demo track. Returns (stereo float32 [n, 2], info)."""
    beat = 60.0 / DEMO_BPM
    bar = beat * 4
    n_bars = 33
    total = DEMO_FIRST_BEAT + n_bars * bar + 2.5
    out = np.zeros((int(total * sr), 2), dtype=np.float64)
    cache: dict = {}

    def voice(key, builder):
        if key not in cache:
            cache[key] = builder()
        return cache[key]

    def add(buf: np.ndarray, at: float, gain: float, pan: float = 0.0) -> None:
        i = int(round(at * sr))
        if i >= len(out):
            return
        seg = buf[: len(out) - i] * gain
        out[i:i + len(seg), 0] += seg * (1 - max(0.0, pan))
        out[i:i + len(seg), 1] += seg * (1 + min(0.0, pan))

    def t_of(bar_i: int, beat_in_bar: float) -> float:
        return DEMO_FIRST_BEAT + bar_i * bar + beat_in_bar * beat

    k, c, hc, ho, cr = kick(sr), clap(sr), hat(False, sr), hat(True, sr), crash(sr)
    for b in range(n_bars):
        chord = _CHORDS[b % 4]
        intro, verse, chorus = b < 4, 4 <= b < 12, 12 <= b < 20
        breakdown, drop, outro = 20 <= b < 24, 24 <= b < 32, b == 32
        drums = not breakdown
        if outro:
            add(k, t_of(b, 0), 0.9)
            add(cr, t_of(b, 0), 0.25)
            add(voice(("pad", chord, 4), lambda: pad([midi_hz(m) for m in chord], bar * 1.2, sr)), t_of(b, 0), 0.12)
            continue
        if drums:
            for q in range(4):
                add(k, t_of(b, q), 0.9)
            for e in range(8):
                add(hc, t_of(b, e * 0.5), 0.16 if e % 2 else 0.1, pan=0.25)
        if (verse or chorus or drop) and drums:
            add(c, t_of(b, 1), 0.5)
            add(c, t_of(b, 3), 0.5)
        if chorus or drop:
            for q in range(4):
                add(ho, t_of(b, q + 0.5), 0.09, pan=-0.2)
        if b in (12, 24):
            add(cr, t_of(b, 0), 0.25)
        if intro or breakdown:
            add(voice(("pad", chord), lambda: pad([midi_hz(m) for m in chord], bar, sr)), t_of(b, 0), 0.14)
        if verse or chorus or drop:
            root = chord[0] - 12
            for e in range(8):
                m = root + (12 if e in (2, 6) else 0)
                add(voice(("bass", m), lambda m=m: bass_note(midi_hz(m), beat * 0.48, sr)), t_of(b, e * 0.5), 0.34)
        if chorus or drop:
            arp = [chord[0] + 12, chord[1] + 12, chord[2] + 12, chord[0] + 24]
            pattern = [0, 1, 2, 3, 2, 1, 0, 1, 2, 3, 2, 1, 2, 3, 2, 1]
            for s, idx in enumerate(pattern):
                m = arp[idx]
                add(voice(("pluck", m), lambda m=m: pluck(midi_hz(m), 0.3, sr)), t_of(b, s * 0.25), 0.13,
                    pan=0.3 if s % 2 else -0.3)
        if chorus or breakdown or drop:
            for start, m, length in _MELODY[b % 4]:
                add(voice(("lead", m, length), lambda m=m, length=length: lead(midi_hz(m), beat * length * 0.95, sr)),
                    t_of(b, start), 0.2)
        if b == 23:  # snare build into the drop
            for s in range(16):
                add(c, t_of(b, s * 0.25), 0.18 + 0.3 * s / 15)

    out = np.tanh(out * 1.1)
    out /= np.abs(out).max() + 1e-9
    out *= 0.9
    info = {"bpm": DEMO_BPM, "offset": DEMO_FIRST_BEAT, "duration": total, "title": DEMO_TITLE,
            "artist": DEMO_ARTIST}
    return out.astype(np.float32), info


def render_click_track(bpm: float = 120.0, n_beats: int = 64, lead_in: float = 0.5, sr: int = SR) -> tuple[np.ndarray, list[float]]:
    """Metronome track used by the offset calibration screen."""
    beat = 60.0 / bpm
    total = lead_in + n_beats * beat + 1.0
    out = np.zeros(int(total * sr), dtype=np.float64)
    hi, lo = click(1900.0, sr), click(1250.0, sr)
    times = []
    for i in range(n_beats):
        t = lead_in + i * beat
        times.append(t)
        buf = hi if i % 4 == 0 else lo
        j = int(round(t * sr))
        out[j:j + len(buf)] += buf * (0.9 if i % 4 == 0 else 0.7)
    stereo = np.stack([out, out], axis=1).astype(np.float32)
    return stereo, times


# --------------------------------------------------------------------------- sound effects
def _sfx_hit(sr: int = SR) -> np.ndarray:
    t = _t(0.07, sr)
    tone = np.sin(2 * np.pi * 1550 * t) * np.exp(-t / 0.022)
    body = np.sin(2 * np.pi * 420 * t) * np.exp(-t / 0.018) * 0.5
    snap = band_noise(len(t), 2500, 9000, sr) * np.exp(-t / 0.005) * 0.45
    return _fade(tone + body + snap, attack=0.0003, release=0.01, sr=sr)


def _chirp(f0: float, f1: float, dur: float, sr: int = SR, square: bool = False) -> np.ndarray:
    t = _t(dur, sr)
    f = np.geomspace(f0, f1, len(t))
    phase = 2 * np.pi * np.cumsum(f) / sr
    x = np.sign(np.sin(phase)) * 0.5 if square else np.sin(phase) + 0.25 * np.sin(2 * phase)
    return _fade(x * np.exp(-t / (dur * 0.6)), attack=0.002, release=0.02, sr=sr)


def _sfx_select(sr: int = SR) -> np.ndarray:
    a = pluck(midi_hz(76), 0.18, sr)
    b = pluck(midi_hz(83), 0.22, sr)
    out = np.zeros(len(a) // 2 + len(b))
    out[: len(a)] += a
    out[len(a) // 2:] += b
    return out / np.abs(out).max()


SFX_BUILDERS = {
    "hit": _sfx_hit,
    "tick": lambda sr=SR: click(1250.0, sr),
    "tick_accent": lambda sr=SR: click(1900.0, sr),
    "ui_move": lambda sr=SR: _chirp(900, 1150, 0.05, sr) * 0.5,
    "ui_select": _sfx_select,
    "ui_back": lambda sr=SR: _chirp(700, 460, 0.12, sr),
    "ui_error": lambda sr=SR: _chirp(220, 160, 0.18, sr, square=True) * 0.6,
    "fail": lambda sr=SR: _chirp(500, 90, 0.7, sr, square=True) * 0.6,
    "combo": lambda sr=SR: _chirp(660, 1320, 0.15, sr),
}


# --------------------------------------------------------------------------- io
def to_int16(x: np.ndarray, channels: int = 2) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    if x.ndim == 1:
        x = np.repeat(x[:, None], channels, axis=1)
    elif x.shape[1] != channels:
        x = np.repeat(x.mean(axis=1, keepdims=True), channels, axis=1)
    return np.ascontiguousarray((np.clip(x, -1, 1) * 32767).astype(np.int16))


def write_wav(path: Path, x: np.ndarray, sr: int = SR) -> None:
    pcm = to_int16(x, 2)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())
