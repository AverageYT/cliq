"""Modifiers - everything that changes a run.

Today they are the toggles in song select ("Mirror", "Hidden", ...). In the
roguelike phase they become items, upgrades and curses: the same hooks can
change rules, rewrite the chart, react to every judgement and draw on screen.

Hooks (all optional):
    apply_rules(rules)                 widen/tighten windows, scale health, multiply score...
    transform_chart(chart, rng)        mirror, shuffle, add or remove notes...
    on_session_start(session)
    on_judgement(session, note, judgement, error)   every hit or miss
    on_update(session, t)              every frame
    prevent_combo_break(session, note) -> bool       e.g. shields
    note_alpha(progress) -> 0..1       progress 0 = at receptor, 1 = just appeared
    hud_text() -> str | None           little status line (charges left...)

To add your own, drop a ``.py`` file in the ``mods/`` folder (see
``mods/example_mods.py``) - it is loaded at startup.
"""

from __future__ import annotations

import importlib.util
import random
import traceback
from pathlib import Path

from ..charting.chart import Chart
from .rules import Rules, load_rules

REGISTRY: dict[str, type["Modifier"]] = {}


def register(cls: type["Modifier"]) -> type["Modifier"]:
    REGISTRY[cls.id] = cls
    return cls


class Modifier:
    id = "base"
    name = "Base"
    description = ""
    category = "fun"           # "assist" | "challenge" | "fun" | "item"
    color = "#FFFFFF"
    ranked = True              # False = scores are not saved (e.g. autoplay)
    score_multiplier = 1.0
    incompatible: tuple[str, ...] = ()

    def __init__(self, **params):
        self.params = params

    def apply_rules(self, rules: Rules) -> None:
        rules.score_multiplier *= self.score_multiplier

    def transform_chart(self, chart: Chart, rng: random.Random) -> Chart:
        return chart

    def on_session_start(self, session) -> None:
        pass

    def on_judgement(self, session, note, judgement, error) -> None:
        pass

    def on_update(self, session, t: float) -> None:
        pass

    def prevent_combo_break(self, session, note) -> bool:
        return False

    def note_alpha(self, progress: float) -> float:
        return 1.0

    def hud_text(self) -> str | None:
        return None


# --------------------------------------------------------------------------- built-ins
@register
class Autoplay(Modifier):
    id, name, category, color, ranked = "autoplay", "Autoplay", "assist", "#3DDCFF", False
    description = "Watch a perfect run. Great for checking a chart's sync."

    def apply_rules(self, rules: Rules) -> None:
        rules.autoplay = True


@register
class Mirror(Modifier):
    id, name, category, color = "mirror", "Mirror", "fun", "#C46BFF"
    description = "Flip the lanes left-to-right."

    def transform_chart(self, chart: Chart, rng: random.Random) -> Chart:
        for n in chart.notes:
            n.lane = chart.lanes - 1 - n.lane
        return chart.sort()


@register
class Shuffle(Modifier):
    id, name, category, color = "shuffle", "Shuffle", "fun", "#FF8A3D"
    description = "Lanes are swapped around at random."

    def transform_chart(self, chart: Chart, rng: random.Random) -> Chart:
        order = list(range(chart.lanes))
        while chart.lanes > 1 and order == list(range(chart.lanes)):
            rng.shuffle(order)
        for n in chart.notes:
            n.lane = order[n.lane]
        return chart.sort()


@register
class Hidden(Modifier):
    id, name, category, color, score_multiplier = "hidden", "Hidden", "challenge", "#9B5CFF", 1.06
    description = "Notes fade out before they reach you."
    incompatible = ("sudden",)

    def note_alpha(self, progress: float) -> float:
        return max(0.0, min(1.0, (progress - 0.22) / 0.2))


@register
class Sudden(Modifier):
    id, name, category, color, score_multiplier = "sudden", "Sudden", "challenge", "#FF4FA3", 1.06
    description = "Notes pop in late."
    incompatible = ("hidden",)

    def note_alpha(self, progress: float) -> float:
        return max(0.0, min(1.0, (0.62 - progress) / 0.12))


@register
class SuddenDeath(Modifier):
    id, name, category, color, score_multiplier = "sudden_death", "Sudden Death", "challenge", "#FF4F6A", 1.1
    description = "One miss and it's over."

    def apply_rules(self, rules: Rules) -> None:
        super().apply_rules(rules)
        rules.sudden_death = True


@register
class Generous(Modifier):
    id, name, category, color, score_multiplier = "generous", "Generous", "assist", "#57F287", 0.8
    description = "Timing windows 40% wider."
    incompatible = ("precise",)

    def apply_rules(self, rules: Rules) -> None:
        super().apply_rules(rules)
        rules.window_scale *= 1.4


@register
class Precise(Modifier):
    id, name, category, color, score_multiplier = "precise", "Precise", "challenge", "#FFD23F", 1.2
    description = "Timing windows 25% tighter."
    incompatible = ("generous",)

    def apply_rules(self, rules: Rules) -> None:
        super().apply_rules(rules)
        rules.window_scale *= 0.75


@register
class GlassCannon(Modifier):
    id, name, category, color, score_multiplier = "glass", "Glass Cannon", "item", "#7CF0FF", 1.25
    description = "Score x1.25, but you lose health twice as fast."

    def apply_rules(self, rules: Rules) -> None:
        super().apply_rules(rules)
        rules.health_loss_scale *= 2.0


@register
class Regen(Modifier):
    id, name, category, color = "regen", "Regen", "item", "#7CFF6B"
    description = "Slowly heal over time (item demo)."

    def on_session_start(self, session) -> None:
        self._last = None

    def on_update(self, session, t: float) -> None:
        if self._last is not None and t > self._last:
            session.heal(0.012 * (t - self._last))
        self._last = t


@register
class ComboShield(Modifier):
    id, name, category, color = "shield", "Combo Shield", "item", "#4FC8FF"
    description = "The first 3 combo breaks are forgiven (item demo)."

    def on_session_start(self, session) -> None:
        self.charges = int(self.params.get("charges", 3))

    def prevent_combo_break(self, session, note) -> bool:
        if self.charges > 0 and session.combo > 0:
            self.charges -= 1
            return True
        return False

    def hud_text(self) -> str | None:
        return f"Shields: {self.charges}"


# --------------------------------------------------------------------------- helpers
def create_modifiers(ids) -> list[Modifier]:
    mods, seen = [], set()
    for mid in ids or ():
        cls = REGISTRY.get(mid)
        if cls is None or mid in seen:
            continue
        if any(other in seen for other in cls.incompatible):
            continue
        seen.add(mid)
        mods.append(cls())
    return mods


def prepare_play(chart: Chart, modifier_ids, ghost_tapping: bool = True, no_fail: bool = False,
                 seed: int = 0) -> tuple[Chart, Rules, list[Modifier]]:
    """Build the (chart copy, rules, modifiers) triple for one play."""
    rules = load_rules()
    rules.ghost_tapping = ghost_tapping
    rules.no_fail = no_fail
    mods = create_modifiers(modifier_ids)
    for m in mods:
        m.apply_rules(rules)
    rng = random.Random(seed)
    play_chart = chart.copy()
    for m in mods:
        play_chart = m.transform_chart(play_chart, rng)
    return play_chart, rules, mods


def load_mod_files(folder: Path) -> list[str]:
    """Import every ``*.py`` in ``folder``. Returns error messages (never raises)."""
    errors = []
    folder = Path(folder)
    if not folder.is_dir():
        return errors
    for path in sorted(folder.glob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"cliq_mod_{path.stem}", path)
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)
        except Exception:
            errors.append(f"{path.name}: {traceback.format_exc(limit=1).strip().splitlines()[-1]}")
    return errors
