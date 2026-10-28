# Cliq

A bright, cartoony rhythm game built with pygame. This is **phase one** of a planned rhythm/roguelike hybrid.

You get a 4-key note highway in the style of rhythm-plus and Friday Night Funkin', plus three more game modes: **Taiko**, **Shield** (the Undyne fight from Undertale) and **Path**. Point it at a YouTube link or any audio file and it finds the BPM and the beat, then auto-charts Easy through Master for every mode so every note lands on the grid. The song's video (or its thumbnail) can play behind the notes. You can build or fix a chart in the **mapping editor** by playing along with the song, and group songs into **playlists** to play back to back.

| | |
|---|---|
| ![Title](docs/images/title.png) | ![Song select](docs/images/song-select.png) |
| ![Gameplay](docs/images/gameplay.png) | ![Mapping editor](docs/images/mapping-editor.png) |

## Quick start

Requires **Python 3.11 or newer** (yt-dlp and deno need it). On a Mac, the built-in `python3` is usually 3.9 - too old. Install a current Python from [python.org](https://www.python.org/downloads/) or with Homebrew (`brew install python@3.12`) first.

```bash
python3.12 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python run.py                      # or: python -m cliq
```

On first launch the game synthesises a demo track (*Cliq Starter*, 128 BPM) so you can play right away.

`requirements.txt` installs **pygame-ce**, a drop-in replacement for pygame (`import pygame`). Classic `pygame>=2.1` also works. If you already have classic pygame installed, uninstall it first: `pip uninstall pygame`.

## Playing

| Action | Keys |
|---|---|
| Lanes (4K) | **D F K L** (arrow keys also work) |
| Pause / resume | Esc |
| Restart | Ctrl+R in game, or R on the pause/results screen |
| Fullscreen | F11 |
| Screenshot | F12 (saved to `user/screenshots/`) |

In song select, pick a game mode with **Tab**, a difficulty with **Left/Right**, and press **Enter** to play. Toggle modifiers (Mirror, Hidden, Sudden Death, Autoplay...) with the mouse. Charts with 5, 6 or 7 lanes are supported. Every key layout is rebindable in **Settings → Controls**.

| Song select | |
|---|---|
| Up/Down, wheel, PgUp/PgDn | Browse songs |
| Tab / Shift+Tab | Game mode |
| Left / Right | Difficulty |
| Enter or double-click | Play |
| I | Add a song (popup, bottom left) |
| E | Mapping editor (Keys charts) |
| R | Re-chart this song for the current mode |
| B | Background: video / thumbnail / nothing |
| P / `+` | Playlists / add this song to your last playlist |
| Delete (twice) | Remove the song |

Hits are judged PERFECT / GREAT / GOOD / BAD / MISS. Hold notes must be held to their end.

**Difficulty.** Five tiers: Easy, Normal, Hard, Expert and Master. Normal is what used to be Expert, and the top two go well past it (16ths, triplets, big chords, long streams). Every auto-chart is split into quarters that get denser and harder, so the last quarter of a song is the climax.

**Health drain** scales with difficulty (0.8x on Easy up to 2x on Master). A chart can set its own drain in the editor.

**Anti-spam** (on by default, Settings → Gameplay): a press with no note close enough to be judged makes you miss the next note in that lane, so mashing doesn't pay. *Ghost tapping* still decides whether stray presses break your combo. Turn on *No fail* if you just want to practise.

### Game modes

Every mode is auto-charted from the same beat analysis, so any song works in any mode. A mode's charts are generated the first time you play them.

| Mode | How it plays |
|---|---|
| **Keys** | The classic 4-lane highway (D F K L, arrows also work). |
| **Taiko** | Notes slide in from the right to a drum. **F / K** (inner keys) hit the red *don* (kick); **D / L** (outer keys) hit the blue *ka* (rim). Big notes give a bonus if you hit them with both hands; yellow drumrolls want as many hits as you can fit. The charter follows the drums: kicks become don, snares and hats become ka. |
| **Shield** | Spears fly at a heart from four sides. Turn the shield to face each one before it lands (D/F/K/L = left/down/up/right, or the arrow keys). Yellow spears swing around at the last moment - block where they *end up*. |
| **Path** | Your ball rolls along a winding path. Notes are actions: a normal note is any key, a **critical** (star) needs all four keys at once, **mash** notes want you to hammer keys until the bar fills, and holds must be held. |

## Adding songs

Press **I** (or click *Add*) in song select: a small window pops up in the bottom-left corner and you can keep browsing while the song imports. *Add a song* on the title screen does the same full-screen.

* **YouTube (or any site yt-dlp supports):** paste the link (Ctrl+V or *Paste*) and press Enter.
* **Audio and video files:** mp3, ogg, wav, flac, m4a, opus, mp4, mkv, webm and more. Click *Browse*, drag the file onto the window, or type its path.
* **Command line:** `python -m cliq import "<link or file>"`. Add `--lanes 6` for a 6-key chart.

**Behind the notes** picks the gameplay background (Tab switches it in the popup):

| Option | What you get |
|---|---|
| Video 720p (default) | The video plays behind the notes, synced to the song. |
| Video 1080p | The same, sharper but a bigger download. |
| Thumbnail | The video thumbnail or album art, blurred and dimmed. |
| Nothing | The animated Cliq background. |

Video needs a YouTube link or a local video file. Change a song's background later with **B** in song select. *Video dim* and *Song backgrounds* are in Settings → Gameplay.

Each import downloads the audio (and video) if needed, converts it with ffmpeg, finds the beat, and writes charts for every difficulty. A 3-minute song takes a few seconds plus the download.

**YouTube requirements.** YouTube now needs two extras besides yt-dlp: `yt-dlp[default]` and a JavaScript runtime. The **`deno`** pip package is the easiest runtime, and both are in `requirements.txt`. Node or Bun on your PATH also work. If downloads start failing, update yt-dlp first: `pip install -U "yt-dlp[default]"`.

**ffmpeg.** A system ffmpeg is used if present; otherwise the binary bundled with `imageio-ffmpeg` is used.

### How the auto-sync works

All analysis code is plain numpy and lives in `cliq/analysis/`:

1. **Onsets.** A log-mel *spectral flux* envelope marks every attack. A measured bias correction makes onset times accurate to about 1 ms. Separate low, mid and high bands tell kicks, snares/vocals and hats apart.
2. **BPM.** Autocorrelation with a tempo prior gives a first guess. The tempo is then refined by finding the beat length that lines up every onset in the song at the same phase, accurate to about 0.01 BPM. The grid offset comes from the same fit.
3. **Tempo drift.** If the constant grid drifts out of sync anywhere (live drummers, tempo changes), the analyser switches to a dynamic-programming beat tracker and uses its beats as a variable grid.
4. **Downbeats.** Kick on 1, backbeat on 2 and 4, and new sections starting on a bar line decide where measures start.
5. **Charting.** Onsets snap to the grid. Notes are picked per measure by salience and metrical weight, up to a density budget for the difficulty, so quiet parts get fewer notes than choruses. Holds go on sustained melody notes. Lanes follow the melody's pitch contour, lean kicks left and hats right, avoid fast same-lane "jacks", and keep both hands busy.

The tests check the analyser against synthetic songs with known BPM, offset, swing/jitter and tempo drift (`tests/test_analysis.py`). On those, beat positions land within a few milliseconds.

## Playlists

Group songs together and play them back to back: **Playlists** on the title screen, or **P** in song select. Press **+** in song select to drop the highlighted song (with its mode and difficulty) into your last playlist.

| Playlists | |
|---|---|
| N / F2 / Delete | New / rename / delete playlist |
| A | Pick songs from your library |
| Right, then Up/Down | Edit the songs in a playlist |
| M, `[` `]` | Change a song's mode / difficulty |
| Alt+Up/Down | Reorder |
| Enter / S | Play in order / shuffled |

After each song, *Next song* moves on; the end screen totals score, accuracy, clears and full combos. Playlists are saved in `user/playlists.json`.

## Mapping mode (editor)

Open it from song select with **E** (Keys mode). Pick the difficulty first; choosing an empty slot starts a blank chart.

**Map by playing:** press **Space** (or **Enter**, if Space is one of your lane keys) to play. Tap your lane keys in time with the music. Taps become notes, long presses become holds, and everything snaps to the grid. Notes can overlap - a tap inside a hold, notes stacked a 1/32 apart - so only an exact duplicate (same lane, same grid spot) is skipped when you record over a chart.

| Keys | What they do |
|---|---|
| Left / Right | Snap finer / coarser (1/4 ... 1/64) |
| Up / Down / mouse wheel | Step one snap line (Ctrl+wheel zooms) |
| PgUp / PgDn, Home / End | Jump a measure / to the start or end |
| Lane keys while paused | Toggle a note at the playhead |
| Mouse | Click to add or remove a note, drag to draw a hold, right-click to delete |
| R / M / N | Recording on/off / metronome / note ticks (hear when notes pass the line) |
| `-` / `=` | BPM down/up by 0.1 (Shift: 1, Ctrl: 0.01) |
| `[` / `]` | Shift the grid 5 ms earlier/later (Shift: 1 ms) |
| T | Tap tempo (tap 8+ times on the beat) |
| B | Make the beat at the playhead a bar line |
| G | Re-run the auto-charter for this difficulty |
| Delete / Shift+Delete | Delete the selection, or clear this measure / clear all notes |
| Ctrl+A | Select all notes |
| Ctrl+click / Shift+drag | Add a note to the selection / box-select |
| Ctrl+C / Ctrl+X / Ctrl+V | Copy / cut / paste at the playhead (works across songs; kept in beats, so it fits any tempo) |
| Ctrl+D | Duplicate the selection right after itself |
| Alt+Up / Alt+Down | Move the selection one snap step |
| Ctrl+M | Mirror the selection's lanes |
| Esc | Clear the selection (press again to leave) |
| `,` / `.` | Health drain down/up for this chart (Shift+`,` back to the difficulty default) |
| Ctrl+Z / Ctrl+Y | Undo / redo |
| P or F5 | Playtest from the playhead |
| Ctrl+S | Save |

The left edge shows the song's onset strength, so you can see where the hits are. **BPM x2 / 2** fixes half-time or double-time detections, and *Reset timing* restores the detected grid.

## Latency

The game does the following on its own:

* Opens the mixer with a small buffer (512 samples = 11.6 ms; adjustable in Settings → Audio).
* Runs the loop at a high frame cap with VSync off by default. A frame takes a few milliseconds, so input is checked every few milliseconds.
* Timestamps key presses with a high-resolution clock when they are read, not at the next frame.
* Plays hit sounds instantly on reserved mixer channels.
* Runs a song clock that follows the sound card's sample position, gently correcting drift without visible jumps.
* Pauses Python's garbage collector while a song plays.

You can do the rest:

* **Calibrate once:** Settings → Audio → *Calibrate offset*. Tap along to the clicks and the median of your taps becomes your audio offset.
* After a song, the results screen shows your average timing. If you are consistently early or late, press **O** to fix the offset in one click.
* Prefer wired headphones; Bluetooth adds 100–250 ms. Keep VSync off. If you hear crackling, raise the audio buffer.

## Customising & modding

Everything is plain files.

| What | Where |
|---|---|
| Your settings | `user/settings.json` (or the in-game menu) |
| Playlists | `user/playlists.json` |
| Game modes | `cliq/modes/` - subclass `GameMode`, call `register_mode` (from a mod file too) |
| Timing windows, scores, health, grades | `data/judgement.json` |
| Auto-chart difficulty (density, subdivisions, chords, holds) | `data/difficulties.json` |
| Colours, fonts, lane colours/arrow directions per key count | `data/theme.json` |
| Note art | PNGs in `assets/skins/<arrows\|circles\|bars>/`, see [`assets/skins/README.md`](assets/skins/README.md) |
| Sounds | `assets/sfx/<name>.wav` (`hit`, `tick`, `ui_select`, ...) |
| Gameplay modifiers / items | any `.py` file in `mods/`, see [`mods/example_mods.py`](mods/example_mods.py) |
| Songs and charts | `songs/<song>/` (`song.json`, `audio.ogg`, `background.mp4`, `charts/*.json`; other modes are `charts/taiko-hard.json` etc.) |

A modifier can change the rules (timing windows, health, score multiplier, scroll speed), rewrite the chart (mirror, shuffle, add or remove notes), react to every hit or miss, block combo breaks, fade notes, and show HUD text. These are the hooks roguelike items will use. The two example mods (*Heartbeat*, *Turbo Scroll*) show up in song select automatically.

Set the `CLIQ_HOME` environment variable to keep songs and settings outside the project folder.

[`docs/architecture.md`](docs/architecture.md) has the code tour and the plan for phase two (roguelike runs, more game modes).

**Sharpness.** The game draws at your screen's real pixel density (Retina/4K included), at 1080p by default on big or high-DPI screens. *Render quality* in Settings → Display goes from 720p to native; higher is sharper but costs more CPU per frame. Restart to apply.

**Charts from older versions** were made with the old difficulty tiers. Press **R** in song select to re-chart a song with the new ones (hand-edited charts are kept).

## Development

```bash
pip install -r requirements.txt
python -m pytest            # analysis, charting, gameplay, song clock, import, headless UI flows
python -m cliq analyze song.mp3   # print detected BPM, offset and chart stats
```

The UI tests run headless (`SDL_VIDEODRIVER=dummy`, `SDL_AUDIODRIVER=dummy`).

## Credits

* Fonts: [Fredoka](https://github.com/hafontia/Fredoka-One) and [Lilita One](https://fonts.google.com/specimen/Lilita+One), SIL Open Font License (see `assets/fonts/`).
* All art and sounds are generated procedurally in code.
