# Phase-one playtest plan

**Problem statement.** Evaluate whether first-time players can (1) get a song into Cliq, (2) play an auto-generated chart that *feels* in sync on their own setup, and (3) fix or make a chart by playing along. Do this before we build roguelike systems on top of these foundations.

Research here exists to de-risk phase two. Every question below maps to a decision we will make next.

## Research questions

| # | Question | Decision it informs |
|---|---|---|
| 1 | Do auto-charts feel on-beat and fun across genres (EDM, pop, rock/live drums, hip-hop, swing)? Where do they feel off? | Whether to invest in beat tracking or the charter before roguelike work |
| 2 | After calibration, is latency noticeable? How big are offsets across setups (speakers, wired, Bluetooth)? | Default offset/buffer values; whether we need a visual-offset setting |
| 3 | Can players import from YouTube or a file without help? Where do they get stuck? | Import UI wording and error messages |
| 4 | Can players map or fix 30 seconds of a chart by playing along? | Editor complexity (keep vs. simplify vs. add tools) |
| 5 | Which difficulty do newcomers pick and finish? | Density targets in `data/difficulties.json` |

## Method

* **Moderated usability test**, in person or over a screen share with game audio. 5 participants, 45 minutes each, think-aloud.
  * 5 users surface about 85% of usability issues, and the build is ready to hand over.
  * Observing behaviour matters more than opinions for timing ("it felt late" vs. what their hits actually did).
* **Built-in telemetry:**
  * Every play stores `accuracy`, `mean_offset_ms` and `std_offset_ms` in `user/scores.json`.
  * The results screen shows a timing histogram.
  * Collect each participant's `user/` folder after the session; this is the quantitative check on question 2.
* The facilitator should **not** be the person who built the feature under test. A second person takes notes.

## Participants

| Must have | Nice to have | Exclude |
|---|---|---|
| Plays games on a computer at least weekly | Mix of setups: speakers, wired headphones, Bluetooth | People who worked on Cliq |
| Has a song in mind they'd want to play | 2 rhythm-game regulars (FnF / osu! / rhythm-plus), 2 casual, 1 non-rhythm gamer | |

**Screener (behavioural, doesn't reveal the target):**
1. In the last month, which of these have you played? (list several genres, rhythm games among them)
2. What do you usually listen to music on while at your computer?
3. Roughly how many hours a week do you play games on a computer?

## Session script (45 min)

1. **Intro (3 min).** We're testing the game, not you; think aloud.
2. **Get-it test (2 min).** On the title screen: "What do you think this game is? What would you do first?"
3. **Tasks (30 min).** Measure each task. Ask the SEQ ("How easy was that?" 1–7) right after.

| Task | Scenario | Success criteria |
|---|---|---|
| T1 Calibrate | "Before playing, make sure the game is in time with your headphones/speakers." | Finds Settings → Calibrate and applies an offset without help |
| T2 First song | "Play the song that's already in the game on a difficulty that suits you." | Finishes a song; note which difficulty they chose and the result |
| T3 YouTube | "Add a song you like from YouTube and play it." | Song imported and played without assistance in under 3 min |
| T4 File | (give them an mp3) "Add this file and play it." | Uses Browse, drag & drop or paste without help |
| T5 Make it yours | "Change the keys to ones you prefer and make notes come from the bottom." | Rebinds keys and switches scroll direction |
| T6 Map | "This chart has a mistake in the chorus. Fix it so it matches the music, then try it." | Uses play-along or mouse editing and playtests; record what they reach for first |

4. **Sync probe (5 min).** For each song they played, ask: "Did the notes feel on the beat? Was any part off?" Have them point to the moment, and log the song time.
5. **Debrief (5 min).** Hardest part, easiest part, anything else? Then the SUS questionnaire.

## Measures & targets

| Metric | Target | Minimum |
|---|---|---|
| Task completion (T1–T6) | 90% | 80% |
| SEQ per task | ≥ 5.5 / 7 | 5.0 |
| SUS | ≥ 75 | 68 |
| Calibrated mean offset of plays (telemetry) | within ±10 ms | within ±20 ms |
| Players rating sync of auto-charts "on the beat" (4–5 / 5) | 4 of 5 | 3 of 5 |
| Newcomers who finish their first chosen song | 5 of 5 | 4 of 5 |

## Analysis

1. Within 24 hours, turn notes into one-observation-per-sticky (participant-coded): behaviours, quotes, timestamps of "off" moments.
2. Affinity-map into themes (e.g. "people expect Space to start mapping", "Bluetooth users all hit ~180 ms late").
3. Triage each issue by **severity × frequency**:
   * **Tier 1** (critical or high, seen in 2+ of 5 players): fix before phase two.
   * **Tier 2**: next iteration.
   * **Tier 3**: backlog.
4. For sync complaints, open the song in the editor at the reported timestamp:
   * If the grid is off, it's an analysis bug; add the song as a regression case.
   * If the grid is right but notes feel wrong, it's a charter issue (tune `difficulties.json` or the lane rules).
5. Share a one-page summary (themes, tiered issues, what changes next) with screenshots, not a long report.

## What we expect to learn (hypotheses to try to *disprove*)

* Auto-charts on constant-tempo music (EDM, pop) will feel in sync; live recordings will need the variable-tempo path or manual BPM fixes.
* Most players won't find calibration on their own. If so, prompt it on first launch.
* Play-along mapping will be preferred over mouse editing for adding notes; mouse editing will be preferred for fixing.
