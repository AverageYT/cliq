"""Example mods - copy this file, rename it, and make your own.

Every ``.py`` file in this folder is loaded when the game starts. Register
modifier classes with ``@register`` and they appear as toggles in song select.
These same hooks are how roguelike items/upgrades will plug in later.
"""

from cliq.gameplay.modifiers import Modifier, register


@register
class Heartbeat(Modifier):
    """Item idea: every 25 combo restores a little health."""

    id = "example_heartbeat"
    name = "Heartbeat"
    description = "Every 25 combo heals you a little (example mod)."
    category = "item"
    color = "#FF6FA8"

    def on_judgement(self, session, note, judgement, error):
        if not judgement.is_miss and session.combo and session.combo % 25 == 0:
            session.heal(0.08)


@register
class TurboScroll(Modifier):
    """Curse idea: notes scroll 50% faster (score bonus)."""

    id = "example_turbo"
    name = "Turbo Scroll"
    description = "Notes scroll 50% faster. Score x1.1 (example mod)."
    category = "challenge"
    color = "#FFB03D"
    score_multiplier = 1.1

    def apply_rules(self, rules):
        super().apply_rules(rules)
        rules.scroll_speed_scale *= 1.5
