"""Game mode interface.

A game mode is three things that share one song analysis and one beat grid:

* ``generate()`` - an auto-charter (usually ``plan_chart`` + mode-specific
  note types),
* ``session()``  - the rules: how presses become judgements (a ``PlaySession``
  subclass, so scoring, health, combo, modifiers and events all keep working),
* ``view()``     - a ``ModeView`` that draws the playfield and tells the shared
  HUD where to put the judgement, timing bar and health bar.

Everything else - song clock, input timestamps, pause, fail/clear, results,
scores, modifiers and playlists - is shared by the gameplay scene.
"""

from __future__ import annotations

import pygame

from ..charting.chart import Chart
from ..gameplay.session import PlaySession

ARROW_KEYS = [pygame.K_LEFT, pygame.K_DOWN, pygame.K_UP, pygame.K_RIGHT]


def keycodes(names) -> list[int | None]:
    out = []
    for name in names:
        try:
            out.append(pygame.key.key_code(name))
        except (ValueError, pygame.error):
            out.append(None)
    return out


class GameMode:
    id = "base"
    name = "Base"
    tagline = ""
    color = "#FFFFFF"
    editable = False            # the mapping editor can open these charts

    # ------------------------------------------------------------ charts
    def chart_stem(self, difficulty: str) -> str:
        return f"{self.id}-{difficulty}"

    def generate(self, analysis, difficulty: str, grid, settings, seed: int = 0) -> Chart:
        raise NotImplementedError

    # ------------------------------------------------------------ play
    def lanes(self, chart: Chart) -> int:
        return chart.lanes

    def key_map(self, settings, chart: Chart) -> dict[int, int]:
        """pygame key code -> lane passed to ``session.press``."""
        codes = keycodes(settings.keys_for(4))
        mapping = {c: lane for lane, c in enumerate(codes) if c is not None}
        for lane, key in enumerate(ARROW_KEYS):
            mapping.setdefault(key, lane)
        return mapping

    def key_hint(self, settings, chart: Chart) -> str:
        return " ".join(k.upper() for k in settings.keys_for(chart.lanes))

    def session(self, chart: Chart, rules, modifiers, bus, start_time: float) -> PlaySession:
        return PlaySession(chart, rules, modifiers, bus, start_time=start_time)

    def view(self, scene) -> "ModeView":
        raise NotImplementedError


class ModeView:
    """Draws one mode. Positions are in render pixels and read by the HUD."""

    def __init__(self, scene):
        self.scene = scene
        self.s = scene.s
        w, h = scene.size
        self.center_x = w / 2
        self.judge_y = h * 0.42
        self.countdown_y = h * 0.4
        self.error_y: float | None = h - scene.s(40)
        self.health_x = w - scene.s(60)
        self.info_limit = w * 0.3          # song title may not extend past this x
        self.ahead = 1.0                   # seconds of notes visible (anti-spam range)
        self.autoplay_y = scene.s(28)

    def update(self, dt: float, t: float) -> None:
        pass

    def draw(self, surf: pygame.Surface, t: float) -> None:
        pass

    def on_judgement(self, note, judgement, error) -> None:
        pass

    def on_hold_tick(self, lane: int) -> None:
        pass
