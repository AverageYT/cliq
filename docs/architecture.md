# Architecture

Cliq is split so that **music analysis**, **chart data**, **game rules** and **rendering** never depend on each other the wrong way. That split is what lets phase two add roguelike runs and new rhythm game modes without rewriting phase one.

```
                ┌──────────────┐   song.json / analysis.npz / charts/*.json
 YouTube/file ─▶│ library/     │──────────────────────────────────────────┐
                │  importer    │                                          │
                └──────┬───────┘                                          ▼
                       │ PCM                          ┌──────────────────────────────┐
                ┌──────▼───────┐   SongAnalysis       │ charting/                    │
                │ analysis/    │─────────────────────▶│  BeatGrid  Chart  autochart  │
                │  features    │  (beats, onsets with │  profiles (difficulties.json)│
                │  tempo       │   band + pitch info) └──────────────┬───────────────┘
                └──────────────┘                                     │ Chart
                                                                     ▼
 keys ─▶ scenes/gameplay ──press/release(t)──▶ gameplay/session (PlaySession) ──events──▶ EventBus
          │   ▲                               rules (judgement.json) + modifiers          │
          │   └──────── song time ──────── audio/conductor ◀── audio/engine (mixer)       │
          ▼                                                                               ▼
       render/playfield, skins, fx, widgets  ◀───────────── effects, HUD, sounds, items ──┘
```

## Packages

| Package | Responsibility | Notes |
|---|---|---|
| `analysis/` | `features.py`: STFT → log-mel spectral flux, band envelopes, onsets, pitch per onset. `tempo.py`: BPM, constant grid fit, drift check, DP beat tracker, downbeats. `analyzer.py`: `SongAnalysis` + `.npz` cache. | numpy only. Fully deterministic. |
| `charting/` | `BeatGrid` (beat ↔ seconds, constant or variable), `Chart`/`Note` + JSON format, difficulty profiles, `autochart.generate_chart()`. | The charter takes `**overrides` for any profile field (items can make a run denser, sparser, add triplets...). |
| `audio/` | `engine.py`: mixer setup and SFX. `conductor.py`: the song clock. `ffmpeg.py`, `youtube.py`: decoding/downloading. `synth.py`: procedural sounds and the demo song. | The conductor is the only source of song time. |
| `gameplay/` | `rules.py` (windows, scoring, health), `session.py` (`PlaySession`: judging, holds, combo, health, events), `modifiers.py` (registry, built-ins, mod loader). | **No pygame imports** in `session`/`rules`: unit-testable and reusable by other modes. |
| `library/` | Song folders, import jobs (threaded), scores. | |
| `render/` | Procedural vector sprites (`vector.py`), note skins, playfield, particles, background, widgets, fonts. | Everything is pre-rendered once and blitted per frame. |
| `scenes/` | Title, song select, import, gameplay, results, editor, settings, calibration. | Each scene is a small class on the app's scene stack. |

## The song clock (`audio/conductor.py`)

* Song time is taken from `perf_counter()`, anchored when playback starts, so it is smooth and has sub-millisecond resolution.
* The mixer's sample-counted music position is used **only to correct drift**:
  * Its constant offset is measured over the first frames and ignored, so nothing jumps.
  * Corrections are rate-limited.
  * Implausible readings (wrong-rate drivers, stopped music) switch syncing off rather than dragging the chart.
* The player's calibrated `audio_offset_ms` shifts the whole chart: `time = raw_time - offset`.
* `time_at(perf_counter())` converts an input timestamp to song time, which is how key presses are judged.

## Events (`EventBus`)

`PlaySession` emits these; payloads are keyword arguments. Effects, sounds, the HUD and modifiers subscribe without the session knowing about them.

| Event | Payload |
|---|---|
| `judgement` | `session, note, judgement, error` (fired for misses too; `judgement.is_miss`) |
| `hold_start`, `hold_complete`, `hold_drop` | `session, note` |
| `combo_break` | `session, combo` |
| `combo_milestone` | `session, combo` (every 50) |
| `combo_shielded` | `session, note, modifier` |
| `ghost_tap` | `session, lane, time` |
| `fail`, `finish` | `session` |
| `auto_press` | `session, lane` (autoplay) |

## Modifiers = future items

`gameplay/modifiers.py` defines the hooks. Built-ins cover assists (Autoplay, Generous), challenges (Hidden, Sudden, Sudden Death, Precise), chart transforms (Mirror, Shuffle) and item-style effects (Regen, Combo Shield, Glass Cannon). A roguelike run will keep a list of modifier instances that persist across songs. Their parameters (`Modifier(**params)`) hold upgrade levels and charges.

```python
from cliq.gameplay.modifiers import Modifier, register

@register
class Vampire(Modifier):
    id, name, category, color = "vampire", "Vampire", "item", "#C0304F"
    description = "Perfects heal, misses hurt double."

    def apply_rules(self, rules):
        rules.health_loss_scale *= 2

    def on_judgement(self, session, note, judgement, error):
        if judgement.id == "perfect":
            session.heal(0.01)
```

## Adding a game mode (phase two)

Undertale-style shielding, taiko and similar modes should reuse:

* `SongAnalysis`:
  * `beat_times` / `grid()` for the musical grid;
  * `onsets` with `low`/`mid`/`high` band strengths and `tone` (pitch), e.g. kicks → taiko "don", hats → "ka", melody → shield directions;
  * `rms` for intensity.
* `BeatGrid`, for quantising whatever the mode spawns.
* `Rules` + `PlaySession`, or a sibling session class, emitting the same events, so modifiers and HUD effects work unchanged.
* `Conductor` for timing, and `Playfield`-style renderers for drawing.

A mode then needs a pattern generator (like `autochart.py`) and a scene. Charts already carry a `kind` field per note ("tap" today) for mixing note types such as mines or shield arrows.

## Planned phase-two shape

```
Run (seed, health, currency, modifiers/items)
  └─ Map of nodes ─▶ Song node: pick song + mode, generate chart with run overrides
                    Shop node: buy/upgrade items (Modifier instances with params)
                    Event node: curses/blessings (more modifiers)
```

The pieces already exist: deterministic chart generation from a seed, profile overrides for difficulty scaling, modifier instances with state, and per-play summaries from `PlaySession.summary()` to award rewards.
