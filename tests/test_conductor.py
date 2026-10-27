"""Song clock behaviour, driven by a fake clock and a fake audio device."""

import pytest

from cliq.audio import conductor as conductor_mod
from cliq.audio.conductor import Conductor


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class FakeAudio:
    """Music position advances at ``rate`` x real time, quantised like a mixer callback."""

    available = True

    def __init__(self, clock: FakeClock, rate: float = 1.0, lead_ms: float = 15.0):
        self.clock = clock
        self.rate = rate
        self.lead_ms = lead_ms
        self.started_at = None
        self.playing = False
        self.paused = False
        self.stalled_for = 0.0

    def load_music(self, path):
        return True

    def play_music(self, start=0.0, fade_ms=0):
        self.started_at = self.clock()
        self.playing, self.paused = True, False

    def pause_music(self):
        self.paused = True

    def stop_music(self):
        self.playing = False

    def music_busy(self):
        return self.playing and not self.paused

    def music_pos_ms(self):
        if not self.playing or self.started_at is None:
            return -1
        elapsed = (self.clock() - self.started_at - self.stalled_for) * self.rate
        buffered = (int(elapsed * 1000 / 11.6) + 1) * 11.6   # mixer callback granularity
        return int(buffered + self.lead_ms)


@pytest.fixture()
def clock(monkeypatch):
    c = FakeClock()
    monkeypatch.setattr(conductor_mod.time, "perf_counter", c)
    return c


def run(cond: Conductor, clock: FakeClock, seconds: float, fps: float = 240.0):
    for _ in range(int(seconds * fps)):
        clock.now += 1.0 / fps
        cond.update()


def test_offset_shifts_chart_time(clock):
    cond = Conductor(FakeAudio(clock), offset_ms=30)
    cond.play(0.0)
    run(cond, clock, 1.0)
    assert cond.time == pytest.approx(cond.raw_time() - 0.030)


def test_lead_in_starts_music_on_time(clock):
    audio = FakeAudio(clock)
    cond = Conductor(audio)
    cond.play(-1.0)
    assert cond.state == "waiting" and audio.started_at is None
    run(cond, clock, 0.9)
    assert audio.started_at is None
    run(cond, clock, 0.2)
    assert cond.state == "playing" and audio.started_at is not None
    assert cond.time == pytest.approx(0.1, abs=0.01)


def test_follows_real_sound_card_drift(clock):
    audio = FakeAudio(clock, rate=1.00005)        # 50 ppm fast: normal hardware
    cond = Conductor(audio)
    cond.play(0.0)
    run(cond, clock, 120.0)
    audio_time = (clock.now - audio.started_at) * audio.rate
    assert cond.sync_to_audio
    assert abs(cond.raw_time() - audio_time) < 0.003   # stays locked to what you hear


def test_ignores_driver_reporting_wrong_rate(clock):
    audio = FakeAudio(clock, rate=1.04)           # e.g. SDL dummy driver
    cond = Conductor(audio)
    cond.play(0.0)
    run(cond, clock, 30.0)
    assert not cond.sync_to_audio
    assert abs(cond.drift_correction) < 0.01      # no visible jumps on the way


def test_snaps_back_after_a_real_stall(clock):
    audio = FakeAudio(clock)
    cond = Conductor(audio)
    cond.play(0.0)
    run(cond, clock, 2.0)
    audio.stalled_for = 0.3                       # device hiccup: audio fell 300 ms behind
    run(cond, clock, 1.0)
    audio_time = clock.now - audio.started_at - audio.stalled_for
    assert abs(cond.raw_time() - audio_time) < 0.02
    assert cond.sync_to_audio


def test_pause_resume_keeps_position(clock):
    cond = Conductor(FakeAudio(clock))
    cond.play(5.0)
    run(cond, clock, 1.0)
    cond.pause()
    paused_at = cond.time
    clock.now += 3.0
    assert cond.time == pytest.approx(paused_at)
    cond.resume()
    run(cond, clock, 0.5)
    assert cond.time == pytest.approx(paused_at + 0.5, abs=0.01)


def test_time_at_stamps_input_precisely(clock):
    cond = Conductor(FakeAudio(clock), offset_ms=0)
    cond.play(0.0)
    run(cond, clock, 1.0)
    press = clock.now - 0.004                      # key pressed 4 ms before this frame
    assert cond.time_at(press) == pytest.approx(cond.time - 0.004)


def test_ignores_nonsense_position_jumps(clock):
    audio = FakeAudio(clock)
    cond = Conductor(audio)
    cond.play(47.7)
    run(cond, clock, 1.0)
    before = cond.raw_time()
    audio.stalled_for = -16.7                      # position suddenly claims to be 16.7 s ahead
    run(cond, clock, 2.0)
    assert cond.raw_time() == pytest.approx(before + 2.0, abs=0.01)
    assert not cond.sync_to_audio


def test_no_sync_while_music_is_not_playing(clock):
    audio = FakeAudio(clock)
    cond = Conductor(audio)
    cond.play(0.0)
    run(cond, clock, 1.0)
    audio.paused = True                            # e.g. faded out / stopped by someone else
    audio.stalled_for = -5.0
    run(cond, clock, 1.0)
    assert cond.drift_correction == pytest.approx(0.0, abs=0.003)
