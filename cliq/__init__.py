"""Cliq - a moddable rhythm game (phase one: 4K note highway).

Package map (see README.md for the full architecture tour):

    analysis/   beat, BPM and onset detection (numpy only)
    charting/   chart data model, beat grid and the auto-charter
    audio/      low-latency mixer setup, song clock, ffmpeg + YouTube import helpers
    library/    song folders on disk, import jobs, high scores
    gameplay/   judgement, scoring, health and the modifier (item) system
    render/     procedural vector art, fonts, widgets and effects
    scenes/     menus, gameplay, results, mapping editor, settings, calibration
"""

__version__ = "0.1.0"
