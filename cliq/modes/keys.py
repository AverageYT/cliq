"""Keys: the rhythm-plus / FnF note highway (4-7 lanes)."""

from __future__ import annotations

import pygame

from ..charting.autochart import generate_chart
from ..gameplay.modifiers import Modifier
from ..render.playfield import Playfield
from .base import ARROW_KEYS, GameMode, ModeView, keycodes


class KeysMode(GameMode):
    id = "keys"
    name = "Keys"
    tagline = "Hit the notes as they reach the receptors"
    color = "#C46BFF"
    editable = True

    def chart_stem(self, difficulty: str) -> str:
        return difficulty   # keys charts keep their plain names (easy.json, ...)

    def generate(self, analysis, difficulty, grid, settings, seed=0):
        chart = generate_chart(analysis, difficulty, lanes=settings.lane_count, grid=grid, seed=seed)
        chart.mode = self.id
        return chart

    def key_map(self, settings, chart):
        codes = keycodes(settings.keys_for(chart.lanes))
        mapping = {c: lane for lane, c in enumerate(codes) if c is not None}
        if chart.lanes == 4:  # arrow keys always work too (FnF style)
            for lane, key in enumerate(ARROW_KEYS):
                mapping.setdefault(key, lane)
        return mapping

    def view(self, scene):
        return KeysView(scene)


class KeysView(ModeView):
    def __init__(self, scene):
        super().__init__(scene)
        settings = scene.app.settings
        self.pf = pf = Playfield(scene.theme, settings, scene.lanes, scene.ui.scale, scene.size,
                                 speed_scale=scene.rules.scroll_speed_scale)
        down = pf.down
        h = scene.size[1]
        self.center_x = pf.x0 + pf.width / 2
        self.judge_y = h * (0.42 if down else 0.58)
        self.countdown_y = h * 0.4
        gap = pf.lane_w * 0.5 + scene.s(24)
        self.error_y = pf.receptor_y + (gap if down else -gap)
        self.health_x = pf.x0 + pf.width + scene.s(38)
        self.info_limit = pf.x0 - scene.s(20)
        self.ahead = pf.ahead
        self.autoplay_y = scene.s(28) if down else h - scene.s(20)
        notes = scene.session.notes
        self.times = [n.time for n in notes]
        self.max_hold = max((n.end - n.time for n in notes), default=0.0)
        alpha_mods = [m for m in scene.mods if type(m).note_alpha is not Modifier.note_alpha]
        self.alpha_fn = (lambda p: min(m.note_alpha(p) for m in alpha_mods)) if alpha_mods else None

    def update(self, dt, t):
        self.pf.update(dt, self.scene.session.pressed)

    def draw(self, surf: pygame.Surface, t: float) -> None:
        pf, session = self.pf, self.scene.session
        pf.draw_panel(surf)
        pf.draw_beams(surf, session.pressed)
        if pf.show_beat_lines:
            pf.draw_grid(surf, t, self.scene.grid)
        pf.draw_chart(surf, t, session.notes, self.times, session.pressed, self.max_hold, self.alpha_fn)
        pf.draw_effects(surf)

    def on_judgement(self, note, judgement, error):
        if not judgement.is_miss:
            self.pf.on_hit(note.lane, judgement.id, judgement.color)

    def on_hold_tick(self, lane):
        self.pf.on_hold_tick(lane)
