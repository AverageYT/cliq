"""Mapping editor: build or fix a chart by playing along.

Main idea: press Play and tap the lane keys in time with the music. Taps become
notes, long presses become holds, everything snaps to the beat grid (choose the
snap with Left/Right). While paused you can click to add/remove notes, drag to
draw holds, and fine-tune the grid (BPM, offset, bar lines, tap tempo).
"""

from __future__ import annotations

import bisect
import time

import pygame

from ..audio.conductor import Conductor
from ..charting.autochart import generate_chart
from ..charting.beatgrid import BeatGrid
from ..charting.chart import Chart, Note
from ..charting.profiles import load_profiles
from ..render.background import Background
from ..render.playfield import Playfield
from ..render.widgets import Button, draw_bar, panel
from ..util import darken, format_time, lighten
from .base import Scene
from .gameplay import lane_key_map

SNAPS = [1, 2, 3, 4, 6, 8, 12, 16]           # grid lines per beat
SNAP_NAMES = {1: "1/4", 2: "1/8", 3: "1/12", 4: "1/16", 6: "1/24", 8: "1/32", 12: "1/48", 16: "1/64"}

HELP = [
    ("Space / Enter", "play / pause"),
    ("lane keys", "record notes while playing; toggle at playhead when paused"),
    ("hold a lane key", "record a hold note"),
    ("Left / Right", "snap finer / coarser"),
    ("Up / Down / wheel", "move one snap step (Ctrl+wheel zoom)"),
    ("PgUp / PgDn", "move one measure"),
    ("mouse", "click add/remove, drag = hold, right-click delete"),
    ("R", "record on/off"),
    ("M / N", "metronome / note ticks"),
    ("- / =", "BPM down/up (Shift x10, Ctrl x0.1)"),
    ("[ / ]", "grid earlier/later 5 ms (Shift 1 ms)"),
    ("T", "tap tempo (tap 8+ times on the beat)"),
    ("B", "bar line starts here"),
    ("Delete", "clear this measure (Shift: clear all)"),
    ("G", "auto-chart this difficulty again"),
    ("Ctrl+Z / Ctrl+Y", "undo / redo"),
    ("P / F5", "playtest from here"),
    ("Ctrl+S", "save"),
    ("H", "hide this help"),
]


class EditorScene(Scene):
    key_repeat = (260, 40)
    menu_music = False

    def __init__(self, app, song, chart_name: str):
        super().__init__(app)
        settings = app.settings
        self.song = song
        self.chart_name = chart_name
        chart = song.load_chart(chart_name)
        if chart is None:
            chart = Chart(lanes=settings.lane_count, difficulty=chart_name, meta={"generator": "editor"})
        self.lanes = chart.lanes
        self.meta = dict(chart.meta)
        self.notes: list[Note] = sorted(chart.notes, key=lambda n: (n.time, n.lane))
        self._times: list[float] = [n.time for n in self.notes]
        self.grid = BeatGrid.from_dict(song.grid.to_dict())
        self.original_grid = song.grid
        self.analysis = song.load_analysis()
        w, h = self.size
        field_w = settings.lane_width * self.ui.scale * self.lanes
        center_x = min(w * 0.33, w * 0.6 - field_w / 2 - self.s(30))   # keep clear of the side panel
        self.playfield = Playfield(self.theme, settings, self.lanes, self.ui.scale, self.size, center_x=center_x)
        self.conductor = Conductor(app.audio, offset_ms=settings.audio_offset_ms)
        self.background = Background(self.size, self.theme, self.ui.scale, seed=3, dim=0.55)
        self.key_lanes = {k: v for k, v in lane_key_map(settings, self.lanes).items()
                          if k not in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN)}
        self.play_keys = {pygame.K_RETURN, pygame.K_KP_ENTER}
        if pygame.K_SPACE not in self.key_lanes:
            self.play_keys.add(pygame.K_SPACE)
        self.snap_index = SNAPS.index(settings.editor_snap) if settings.editor_snap in SNAPS else 3
        self.record = settings.editor_record
        self.metronome = settings.editor_metronome
        self.assist = settings.editor_assist_tick
        self.help = False
        self.undo_stack: list[tuple[list[Note], list[Note]]] = []
        self.redo_stack: list[tuple[list[Note], list[Note]]] = []
        self.dirty = False
        self.pending: dict[int, float] = {}
        self.lanes_down: set[int] = set()
        self.pressed = [False] * self.lanes
        self.taps: list[float] = []
        self.confirm: tuple[str, float] | None = None
        self.drag: dict | None = None
        self.hover: tuple[int, float] | None = None
        self._last_t = 0.0
        self._playtest_from = 0.0
        self.panel_rect = pygame.Rect(int(w * 0.6), self.s(24), w - int(w * 0.6) - self.s(24), h - self.s(48))
        self.panel_img = panel(self.panel_rect.size, self.ui)
        self.help_img = panel((self.s(760), self.s(600)), self.ui, alpha=255)
        self.help_dim = pygame.Surface(self.size, pygame.SRCALPHA)
        self.help_dim.fill((*darken(self.theme.c("ink"), 0.4), 150))
        self.timeline = pygame.Rect(self.panel_rect.x + self.s(24), self.panel_rect.bottom - self.s(58),
                                    self.panel_rect.width - self.s(48), self.s(22))
        self._build_buttons()

    # ------------------------------------------------------------ setup
    def _build_buttons(self) -> None:
        r = self.panel_rect
        theme = self.theme
        bw = (r.width - self.s(24) * 2 - self.s(12)) // 2
        bh = self.s(48)
        x1, x2 = r.x + self.s(24), r.x + self.s(24) + bw + self.s(12)
        y = r.y + self.s(318)
        specs = [
            ("Play / Pause", self.toggle_play, theme.c("accent"), x1, y),
            ("Playtest  P", self.playtest, theme.c("accent3"), x2, y),
            ("BPM x2", lambda: self.scale_bpm(2.0), theme.c("panel_light"), x1, y + bh + self.s(10)),
            ("BPM / 2", lambda: self.scale_bpm(0.5), theme.c("panel_light"), x2, y + bh + self.s(10)),
            ("Reset timing", self.reset_timing, theme.c("panel_light"), x1, y + 2 * (bh + self.s(10))),
            ("Auto-chart  G", self.autochart, theme.c("accent5"), x2, y + 2 * (bh + self.s(10))),
            ("Help  H", self.toggle_help, theme.c("panel_light"), x1, y + 3 * (bh + self.s(10))),
            ("Save  Ctrl+S", self.save, theme.c("accent4"), x2, y + 3 * (bh + self.s(10))),
        ]
        self.buttons = [Button(self.ui, (x, yy, bw, bh), label, cb, color=color, size=21, role="bold")
                        for label, cb, color, x, yy in specs]

    def enter(self) -> None:
        self.conductor.load(self.song.audio_path, duration=self.song.duration)
        self.app.audio.set_music_volume(self.app.settings.music_volume)
        start = max(0.0, (self.notes[0].time - 1.0) if self.notes else 0.0)
        self.conductor.seek(self.grid.snap(start, 1))
        self._last_t = self.conductor.time
        if not self.notes:
            self.help = True

    def leave(self) -> None:
        self.conductor.stop()
        s = self.app.settings
        s.editor_snap, s.editor_record = self.division, self.record
        s.editor_metronome, s.editor_assist_tick = self.metronome, self.assist
        s.save()

    def resume(self, **result) -> None:
        summary = result.get("playtest")
        self.song.grid = self.original_grid
        self.conductor.load(self.song.audio_path, duration=self.song.duration)
        self.conductor.seek(self._playtest_from)
        if summary:
            self.app.toasts.show(f"Playtest: {summary['accuracy'] * 100:.2f}%  -  {summary['counts'].get('miss', 0)} misses")

    # ------------------------------------------------------------ helpers
    @property
    def division(self) -> int:
        return SNAPS[self.snap_index]

    @property
    def now(self) -> float:
        return self.conductor.time

    def _reindex(self) -> None:
        self.notes.sort(key=lambda n: (n.time, n.lane))
        self._times = [n.time for n in self.notes]

    def _note_near(self, lane: int, t: float, tol: float) -> Note | None:
        lo = bisect.bisect_left(self._times, t - tol)
        hi = bisect.bisect_right(self._times, t + tol)
        best = None
        for n in self.notes[lo:hi]:
            if n.lane == lane and (best is None or abs(n.time - t) < abs(best.time - t)):
                best = n
        return best

    def _tol(self) -> float:
        return max(0.012, 0.45 * self.grid.beat_length_at(max(0.0, self.now)) / self.division)

    def apply(self, added: list[Note], removed: list[Note], undoable: bool = True) -> None:
        if not added and not removed:
            return
        ids = {id(n) for n in removed}
        self.notes = [n for n in self.notes if id(n) not in ids] + list(added)
        self._reindex()
        if undoable:
            self.undo_stack.append((list(added), list(removed)))
            self.undo_stack = self.undo_stack[-300:]
            self.redo_stack.clear()
        self.dirty = True

    def undo(self) -> None:
        if self.undo_stack:
            added, removed = self.undo_stack.pop()
            self.apply(removed, added, undoable=False)
            self.redo_stack.append((added, removed))
            self.app.toasts.show("Undo", seconds=0.8)

    def redo(self) -> None:
        if self.redo_stack:
            added, removed = self.redo_stack.pop()
            self.apply(added, removed, undoable=False)
            self.undo_stack.append((added, removed))
            self.app.toasts.show("Redo", seconds=0.8)

    def toggle_note(self, lane: int, t: float) -> None:
        existing = self._note_near(lane, t, self._tol())
        if existing is not None:
            self.apply([], [existing])
        else:
            self.apply([Note(round(t, 4), lane)], self._overlapping(lane, t, t))

    def _overlapping(self, lane: int, start: float, end: float) -> list[Note]:
        """Notes in ``lane`` that a new note spanning [start, end] would collide with."""
        tol = self._tol()
        return [n for n in self.notes if n.lane == lane and n.time <= end + tol and n.end >= start - tol]

    def _confirm(self, action: str, message: str) -> bool:
        now = time.perf_counter()
        if self.confirm and self.confirm[0] == action and now - self.confirm[1] < 3.0:
            self.confirm = None
            return True
        self.confirm = (action, now)
        self.app.toasts.show(message, self.theme.c("accent5"))
        return False

    # ------------------------------------------------------------ transport
    def toggle_play(self) -> None:
        if self.conductor.running:
            self.conductor.pause()
            self._flush_pending()
            self.conductor.seek(self.grid.snap(self.now, self.division))
        else:
            self._last_t = self.now
            self.conductor.play(self.now)

    def seek(self, t: float) -> None:
        t = max(-1.0, min(self.song.duration, t))
        self._flush_pending()
        self.conductor.seek(t)
        self._last_t = t

    def step(self, steps: int) -> None:
        self.seek(self.grid.step(self.now, self.division, steps))

    def playtest(self) -> None:
        from .gameplay import GameplayScene

        self._flush_pending()
        self.conductor.pause()
        self._playtest_from = self.now
        chart = Chart(lanes=self.lanes, difficulty=self.chart_name, notes=[Note(n.time, n.lane, n.duration, n.kind)
                                                                          for n in self.notes])
        if not chart.notes:
            self.app.toasts.show("Add some notes first", self.theme.c("bad"))
            return
        self.song.grid = self.grid
        self.app.push(GameplayScene(self.app, self.song, chart, self.chart_name, [], start_time=max(0.0, self.now),
                                    from_editor=True))

    # ------------------------------------------------------------ recording
    def _flush_pending(self) -> None:
        t = self.now
        for lane in list(self.pending):
            self._finish_record(lane, t)

    def _finish_record(self, lane: int, release_t: float) -> None:
        start = self.pending.pop(lane, None)
        if start is None:
            return
        beat = self.grid.beat_length_at(max(0.0, start))
        s = self.grid.snap(start, self.division)
        e = self.grid.snap(release_t, self.division)
        hold = (release_t - start) >= max(0.22, beat * 0.45) and e - s >= beat / self.division * 0.99
        if self._note_near(lane, s, self._tol()) is not None:
            return  # already there (overdubbing an existing chart)
        note = Note(round(s, 4), lane, round(e - s, 4) if hold else 0.0)
        self.apply([note], self._overlapping(lane, note.time, note.end))

    # ------------------------------------------------------------ grid edits
    def set_grid(self, grid: BeatGrid, message: str) -> None:
        self.grid = grid
        self.dirty = True
        self.app.toasts.show(message, seconds=1.4)

    def nudge_bpm(self, delta: float) -> None:
        bpm = max(20.0, min(400.0, self.grid.bpm + delta))
        self.set_grid(self.grid.with_bpm(bpm, anchor_time=self.grid.time_at(0)), f"BPM {bpm:.2f}")

    def scale_bpm(self, factor: float) -> None:
        self.set_grid(self.grid.with_bpm(self.grid.bpm * factor, anchor_time=self.grid.time_at(0)),
                      f"BPM {self.grid.bpm * factor:.2f}")

    def nudge_offset(self, ms: float) -> None:
        self.set_grid(self.grid.shifted(ms / 1000.0), f"Grid moved {ms:+.0f} ms")

    def set_bar(self) -> None:
        beat = round(self.grid.beat_at(self.now))
        g = BeatGrid.from_dict(self.grid.to_dict())
        g.downbeat = beat % g.beats_per_measure
        self.set_grid(g, "Bar line moved here")

    def reset_timing(self) -> None:
        if self.analysis is None:
            self.app.toasts.show("No saved analysis for this song", self.theme.c("bad"))
            return
        self.set_grid(self.analysis.grid(), f"Timing reset to detected {self.analysis.bpm:.2f} BPM")

    def tap(self) -> None:
        t = self.conductor.raw_time() - self.conductor.offset
        if self.taps and t - self.taps[-1] > 2.0:
            self.taps.clear()
        self.taps.append(t)
        if len(self.taps) >= 8:
            g = BeatGrid.from_taps(self.taps[-16:], downbeat=self.grid.downbeat)
            if g is not None:
                self.set_grid(g, f"Tap tempo: {g.bpm:.2f} BPM")
        else:
            self.app.toasts.show(f"Tap {8 - len(self.taps)} more...", seconds=0.8)

    def autochart(self) -> None:
        if self.analysis is None:
            self.app.toasts.show("No saved analysis for this song", self.theme.c("bad"))
            return
        if self.notes and not self._confirm("autochart", "Press G again to replace all notes with a fresh auto-chart"):
            return
        profiles = load_profiles()
        name = self.chart_name if self.chart_name in profiles else "normal"
        chart = generate_chart(self.analysis, name, lanes=self.lanes, grid=self.grid)
        self.apply(chart.notes, list(self.notes))
        self.app.toasts.show(f"Auto-charted ({len(chart.notes)} notes) - Ctrl+Z to undo", self.theme.c("good"))

    def clear_measure(self) -> None:
        start = self.grid.measure_step(self.now + 1e-4, -1)
        end = self.grid.measure_step(start + 1e-4, 1)
        doomed = [n for n in self.notes if start - 1e-4 <= n.time < end - 1e-4]
        self.apply([], doomed)
        self.app.toasts.show(f"Cleared {len(doomed)} notes", seconds=1.0)

    def clear_all(self) -> None:
        if self.notes and self._confirm("clear", "Press Shift+Delete again to clear ALL notes"):
            self.apply([], list(self.notes))

    def save(self) -> None:
        self._flush_pending()
        chart = Chart(lanes=self.lanes, difficulty=self.chart_name, notes=list(self.notes),
                      meta={**self.meta, "edited": True})
        self.song.save_chart(chart, self.chart_name)
        self.song.grid = self.grid
        self.original_grid = self.grid
        self.song.save()
        self.dirty = False
        self.app.toasts.show(f"Saved {self.chart_name} ({len(self.notes)} notes)", self.theme.c("good"))

    def toggle_help(self) -> None:
        self.help = not self.help

    def exit(self) -> None:
        if self.dirty and not self._confirm("exit", "Unsaved changes! Esc again to discard, Ctrl+S to save"):
            return
        self.app.pop()

    # ------------------------------------------------------------ events
    def handle_event(self, e) -> None:
        if e.type == pygame.KEYDOWN:
            self._key_down(e)
        elif e.type == pygame.KEYUP:
            lane = self.key_lanes.get(e.key)
            if lane is not None:
                self.lanes_down.discard(lane)
                self.pressed[lane] = False
                if lane in self.pending:
                    self._finish_record(lane, self.conductor.time_at(time.perf_counter()))
        elif e.type == pygame.MOUSEWHEEL:
            steps = e.y if self.playfield.down else -e.y
            mods = pygame.key.get_mods()
            if mods & (pygame.KMOD_CTRL | pygame.KMOD_META):
                self.playfield.speed = max(150.0, min(4000.0, self.playfield.speed * (1.12 if e.y > 0 else 1 / 1.12)))
            elif mods & pygame.KMOD_SHIFT:
                self.snap_index = max(0, min(len(SNAPS) - 1, self.snap_index + (1 if e.y > 0 else -1)))
            else:
                self.step(steps)
        elif e.type == pygame.MOUSEMOTION:
            self._mouse_move(e.pos)
            for b in self.buttons:
                b.handle_event(e)
        elif e.type == pygame.MOUSEBUTTONDOWN:
            if any(b.handle_event(e) for b in self.buttons):
                return
            if e.button == 1 and self.timeline.inflate(0, self.s(16)).collidepoint(e.pos):
                frac = (e.pos[0] - self.timeline.x) / self.timeline.width
                self.seek(self.grid.snap(frac * self.song.duration, 1))
                return
            self._mouse_down(e)
        elif e.type == pygame.MOUSEBUTTONUP:
            for b in self.buttons:
                b.handle_event(e)
            if e.button == 1 and self.drag is not None:
                self._mouse_up()
        elif e.type == pygame.WINDOWFOCUSLOST and self.conductor.running:
            self.toggle_play()

    def _key_down(self, e) -> None:
        mods = e.mod
        ctrl = mods & (pygame.KMOD_CTRL | pygame.KMOD_META)
        shift = mods & pygame.KMOD_SHIFT
        k = e.key
        lane = self.key_lanes.get(k)
        if lane is not None and not ctrl:
            if lane in self.lanes_down:
                return  # key repeat
            self.lanes_down.add(lane)
            self.pressed[lane] = True
            self.playfield.flash[lane] = 0.0
            if self.app.settings.hitsounds:
                self.app.audio.play_sfx("hit", self.app.settings.hitsound_volume * self.app.settings.sfx_volume)
            if self.conductor.running:
                if self.record:
                    self.pending[lane] = self.conductor.time_at(time.perf_counter())
            else:
                self.toggle_note(lane, self.grid.snap(self.now, self.division))
            return
        if k == pygame.K_ESCAPE:
            if self.help:
                self.help = False
            else:
                self.exit()
        elif k in self.play_keys:
            self.toggle_play()
        elif ctrl and k == pygame.K_s:
            self.save()
        elif ctrl and k == pygame.K_z:
            if shift:
                self.redo()
            else:
                self.undo()
        elif ctrl and k == pygame.K_y:
            self.redo()
        elif k == pygame.K_LEFT:
            self.snap_index = min(len(SNAPS) - 1, self.snap_index + 1)
        elif k == pygame.K_RIGHT:
            self.snap_index = max(0, self.snap_index - 1)
        elif k in (pygame.K_UP, pygame.K_DOWN):
            forward = (k == pygame.K_UP) == self.playfield.down
            self.step(1 if forward else -1)
        elif k == pygame.K_PAGEUP:
            self.seek(self.grid.measure_step(self.now, 1 if self.playfield.down else -1))
        elif k == pygame.K_PAGEDOWN:
            self.seek(self.grid.measure_step(self.now, -1 if self.playfield.down else 1))
        elif k == pygame.K_HOME:
            self.seek(0.0)
        elif k == pygame.K_END:
            self.seek(self.notes[-1].time if self.notes else self.song.duration - 1)
        elif k == pygame.K_r:
            self.record = not self.record
            self.app.toasts.show("Recording ON" if self.record else "Recording OFF", seconds=1.0)
        elif k == pygame.K_m:
            self.metronome = not self.metronome
            self.app.toasts.show("Metronome " + ("on" if self.metronome else "off"), seconds=1.0)
        elif k == pygame.K_n:
            self.assist = not self.assist
            self.app.toasts.show("Note ticks " + ("on" if self.assist else "off"), seconds=1.0)
        elif k in (pygame.K_MINUS, pygame.K_KP_MINUS, pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
            sign = -1 if k in (pygame.K_MINUS, pygame.K_KP_MINUS) else 1
            self.nudge_bpm(sign * (1.0 if shift else 0.01 if ctrl else 0.1))
        elif k in (pygame.K_LEFTBRACKET, pygame.K_RIGHTBRACKET):
            sign = -1 if k == pygame.K_LEFTBRACKET else 1
            self.nudge_offset(sign * (1 if shift else 5))
        elif k == pygame.K_t:
            self.tap()
        elif k == pygame.K_b:
            self.set_bar()
        elif k == pygame.K_g:
            self.autochart()
        elif k == pygame.K_DELETE:
            if shift:
                self.clear_all()
            else:
                self.clear_measure()
        elif k in (pygame.K_p, pygame.K_F5):
            self.playtest()
        elif k in (pygame.K_h, pygame.K_F1):
            self.toggle_help()

    def _mouse_pos_note(self, pos) -> tuple[int, float] | None:
        pf = self.playfield
        lane = pf.lane_at_x(pos[0])
        if lane is None:
            return None
        t = pf.time_at_y(pos[1], self.now)
        return lane, self.grid.snap(t, self.division)

    def _mouse_move(self, pos) -> None:
        self.hover = self._mouse_pos_note(pos)
        if self.drag is not None and self.hover is not None:
            self.drag["end"] = max(self.drag["start"], self.hover[1])

    def _mouse_down(self, e) -> None:
        spot = self._mouse_pos_note(e.pos)
        if spot is None:
            return
        lane, t = spot
        existing = self._note_near(lane, t, self._tol())
        if e.button == 3:
            hit = existing or next((n for n in self.notes if n.lane == lane and n.time <= t <= n.end), None)
            if hit is not None:
                self.apply([], [hit])
        elif e.button == 1:
            if existing is not None:
                self.apply([], [existing])
            else:
                self.drag = {"lane": lane, "start": t, "end": t}

    def _mouse_up(self) -> None:
        d, self.drag = self.drag, None
        if d is None:
            return
        length = d["end"] - d["start"]
        note = Note(round(d["start"], 4), d["lane"], round(length, 4) if length > 1e-3 else 0.0)
        self.apply([note], self._overlapping(note.lane, note.time, note.end))

    # ------------------------------------------------------------ update
    def update(self, dt: float) -> None:
        self.conductor.update()
        t = self.now
        if self.conductor.state == "ended":
            self.conductor.pause()
            self.seek(self.grid.snap(self.song.duration - 0.5, 1))
        if self.conductor.running and t > self._last_t:
            if self.assist:
                lo = bisect.bisect_right(self._times, self._last_t)
                hi = bisect.bisect_right(self._times, t)
                if hi > lo:
                    self.app.audio.play_sfx("tick", 0.55 * self.app.settings.sfx_volume)
            if self.metronome:
                b0, b1 = int(self.grid.beat_at(self._last_t) // 1), int(self.grid.beat_at(t) // 1)
                if b1 > b0:
                    accent = self.grid.is_measure_start(b1)
                    self.app.audio.play_sfx("tick_accent" if accent else "tick", 0.7 * self.app.settings.sfx_volume)
        self._last_t = t
        self.playfield.update(dt, self.pressed)
        self.background.update(dt, float(self.grid.beat_at(t)))
        for b in self.buttons:
            b.update(dt)

    # ------------------------------------------------------------ drawing
    def draw(self, surf) -> None:
        t = self.now
        pf = self.playfield
        theme = self.theme
        self.background.draw(surf)
        pf.draw_panel(surf)
        self._draw_onset_strip(surf, t)
        pf.draw_beams(surf, self.pressed)
        pf.draw_grid(surf, t, self.grid, self.division, strong=True)
        hover_note = None
        if self.hover is not None and not self.conductor.running:
            hover_note = self._note_near(self.hover[0], self.hover[1], self._tol())
        pf.draw_chart(surf, t, self.notes, self._times, self.pressed,
                      max((n.duration for n in self.notes), default=0.0),
                      highlight=(lambda n: n is hover_note) if hover_note else None)
        self._draw_ghosts(surf, t)
        pf.draw_effects(surf)
        # judgement line marker
        y = pf.receptor_y
        pygame.draw.line(surf, theme.c("accent2"), (pf.x0 - self.s(16), y), (pf.x0 - self.s(4), y), max(2, self.s(4)))
        pygame.draw.line(surf, theme.c("accent2"), (pf.x0 + pf.width + self.s(4), y),
                         (pf.x0 + pf.width + self.s(16), y), max(2, self.s(4)))
        self._draw_panel(surf, t)
        if self.help:
            self._draw_help(surf)

    def _draw_onset_strip(self, surf, t: float) -> None:
        a = self.analysis
        if a is None:
            return
        pf = self.playfield
        width = self.s(70)
        x_right = pf.x0 - self.s(24)
        if x_right - width < 0:
            return  # no room beside a very wide (6-7K) highway
        n = 160
        t0, t1 = t - pf.behind, t + pf.ahead
        pts = [(x_right, pf.y_at(t0 - t))]
        for i in range(n + 1):
            tt = t0 + (t1 - t0) * i / n
            idx = int(tt * a.fps)
            v = float(a.env[idx]) if 0 <= idx < len(a.env) else 0.0
            pts.append((x_right - min(1.0, v) * width, pf.y_at(tt - t)))
        pts.append((x_right, pf.y_at(t1 - t)))
        pygame.draw.polygon(surf, darken(self.theme.c("accent3"), 0.15), pts)
        pygame.draw.line(surf, self.theme.c("ink"), (x_right, 0), (x_right, self.size[1]), max(1, self.s(2)))

    def _draw_ghosts(self, surf, t: float) -> None:
        pf = self.playfield
        skin = pf.skin
        for lane, start in self.pending.items():
            s = self.grid.snap(start, self.division)
            img = skin.note[lane].copy()
            img.set_alpha(170)
            x = pf.lane_x(lane)
            if t - start > 0.22:
                y0, y1 = pf.y_at(s - t), pf.y_at(0)
                body = pygame.Rect(0, 0, skin.hold_width, abs(y1 - y0))
                body.midtop = (x, min(y0, y1))
                pygame.draw.rect(surf, lighten(skin.colors[lane], 0.3), body)
            surf.blit(img, img.get_rect(center=(x, pf.y_at(s - t))))
        if self.drag is not None:
            lane = self.drag["lane"]
            x = pf.lane_x(lane)
            y0, y1 = pf.y_at(self.drag["start"] - t), pf.y_at(self.drag["end"] - t)
            if abs(y1 - y0) > 2:
                body = pygame.Rect(0, 0, skin.hold_width, abs(y1 - y0))
                body.midtop = (x, min(y0, y1))
                pygame.draw.rect(surf, lighten(skin.colors[lane], 0.3), body)
            img = skin.note[lane]
            surf.blit(img, img.get_rect(center=(x, y0)))
        elif self.hover is not None and not self.conductor.running:
            lane, ht = self.hover
            if self._note_near(lane, ht, self._tol()) is None:
                img = skin.note[lane].copy()
                img.set_alpha(110)
                surf.blit(img, img.get_rect(center=(pf.lane_x(lane), pf.y_at(ht - t))))

    def _draw_panel(self, surf, t: float) -> None:
        r = self.panel_rect
        theme = self.theme
        surf.blit(self.panel_img, r)
        x = r.x + self.s(24)
        self.fonts.draw(surf, "Mapping", (x, r.y + self.s(16)), "display", 38, (255, 255, 255), outline=4, shadow=4)
        label = self.chart_name.title() + (" *" if self.dirty else "")
        self.fonts.draw(surf, label, (r.right - self.s(24), r.y + self.s(26)), "display", 26, theme.c("accent2"),
                        anchor="topright", outline=3)
        self.fonts.draw(surf, self.song.title, (x, r.y + self.s(66)), "bold", 20, theme.c("text_dim"), outline=2,
                        max_width=r.width / self.ui.scale - 60)
        beat = self.grid.beat_at(t)
        measure = int((beat - self.grid.downbeat) // self.grid.beats_per_measure) + 1
        in_measure = (beat - self.grid.downbeat) % self.grid.beats_per_measure + 1
        lines = [
            ("Time", f"{format_time(t)}.{int(abs(t) * 100) % 100:02d}  /  {format_time(self.song.duration)}"),
            ("Position", f"bar {measure}  beat {in_measure:.2f}"),
            ("Tempo", f"{self.grid.bpm:.2f} BPM" + ("  (variable)" if self.grid.variable else "")),
            ("Grid offset", f"{self.grid.time_at(0) * 1000:.0f} ms"),
            ("Snap", f"{SNAP_NAMES.get(self.division, self.division)}  ({self.division}/beat)"),
            ("Notes", f"{len(self.notes)}  ({sum(1 for n in self.notes if n.is_hold)} holds)  {self.lanes}K"),
        ]
        y = r.y + self.s(104)
        for name, value in lines:
            self.fonts.draw(surf, name, (x, y), "bold", 19, theme.c("text_dim"), outline=2)
            self.fonts.draw(surf, value, (x + self.s(130), y), "bold", 20, (255, 255, 255), outline=2)
            y += self.s(30)
        status = []
        if self.conductor.running and self.record:
            blink = int(time.perf_counter() * 2) % 2 == 0
            status.append(("REC" if blink else "   ", theme.c("bad")))
        elif self.record:
            status.append(("REC armed", theme.c("bad")))
        status.append(("Metronome" if self.metronome else "", theme.c("accent2")))
        status.append(("Note ticks" if self.assist else "", theme.c("accent3")))
        sx = x
        for text, color in status:
            if text:
                rect = self.fonts.draw(surf, text, (sx, r.y + self.s(286)), "display", 21, color, outline=3)
                sx = rect.right + self.s(18)
        for b in self.buttons:
            b.draw(surf)
        frac = max(0.0, min(1.0, t / max(1.0, self.song.duration)))
        draw_bar(surf, self.timeline, frac, theme.c("accent2"), self.ui)
        if self.song.duration > 0:
            for n in self.notes[:: max(1, len(self.notes) // 300)]:
                nx = self.timeline.x + self.timeline.width * n.time / self.song.duration
                pygame.draw.line(surf, theme.c("ink"), (nx, self.timeline.y + 3), (nx, self.timeline.bottom - 3), 1)
        keys = "/".join(k.upper() for k in self.app.settings.keys_for(self.lanes))
        play_key = "Space" if pygame.K_SPACE in self.play_keys else "Enter"
        hint = f"{play_key} play  -  {keys} record  -  H help"
        self.fonts.draw(surf, hint, (r.centerx, self.timeline.bottom + self.s(10)), "ui", 16, theme.c("text_dim"),
                        anchor="midtop", outline=2)

    def _draw_help(self, surf) -> None:
        w, h = self.size
        surf.blit(self.help_dim, (0, 0))
        r = self.help_img.get_rect(center=(w // 2, h // 2))
        surf.blit(self.help_img, r)
        self.fonts.draw(surf, "Mapping keys", (r.centerx, r.y + self.s(16)), "display", 34, (255, 255, 255),
                        anchor="midtop", outline=4, shadow=4)
        y = r.y + self.s(72)
        for key, what in HELP:
            self.fonts.draw(surf, key, (r.x + self.s(36), y), "bold", 18, self.theme.c("accent2"), outline=2)
            self.fonts.draw(surf, what, (r.x + self.s(230), y), "ui", 18, (255, 255, 255), outline=2)
            y += self.s(27)
