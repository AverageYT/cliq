import os
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")


@pytest.fixture(scope="session")
def demo_analysis():
    """Analysis of the bundled synthetic demo song (known 128 BPM, first beat at 0.6 s)."""
    from cliq.analysis import features as F
    from cliq.analysis.analyzer import analyze_signal
    from cliq.audio import synth

    stereo, info = synth.render_demo_song()
    mono = stereo.mean(axis=1)
    idx = (np.arange(int(len(mono) * F.SR / synth.SR)) * synth.SR / F.SR).astype(int)
    return analyze_signal(mono[idx], F.SR), info


@pytest.fixture()
def cliq_home(tmp_path, monkeypatch):
    """Point all user data at a temp folder."""
    from cliq import paths

    monkeypatch.setattr(paths, "HOME", tmp_path)
    monkeypatch.setattr(paths, "SONGS_DIR", tmp_path / "songs")
    monkeypatch.setattr(paths, "USER_DIR", tmp_path / "user")
    monkeypatch.setattr(paths, "CACHE_DIR", tmp_path / "user" / "cache")
    monkeypatch.setattr(paths, "SETTINGS_FILE", tmp_path / "user" / "settings.json")
    monkeypatch.setattr(paths, "SCORES_FILE", tmp_path / "user" / "scores.json")
    paths.ensure_dirs()
    return tmp_path
