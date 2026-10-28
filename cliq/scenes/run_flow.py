"""Moving through a run: start the next song, and the summary at the end."""

from __future__ import annotations

import pygame

from ..charting.profiles import load_profiles
from ..modes import MODES, get_mode
from ..render.fx import ease_out_back, ease_out_cubic
from ..render.widgets import Button, ButtonGroup, panel
from ..util import hex_to_rgb
from .base import Scene


def stage_chart(song, stage, settings):
    """(chart, chart stem) for a run stage, falling back to the closest keys difficulty."""
    mode = get_mode(stage.mode if stage.mode in MODES else "keys")
    if mode.id != "keys":
        return song.chart_for(mode.id, stage.difficulty, settings), mode.chart_stem(stage.difficulty)
    names = song.difficulties_for("keys")
    if not names:
        return None, stage.difficulty
    diff = stage.difficulty
    if diff not in names:
        order = {k: p.order for k, p in load_profiles().items()}
        want = order.get(diff, 1)
        diff = min(names, key=lambda n: abs(order.get(n, 100) - want))
    return song.load_chart(diff), diff


def stage_label(stage) -> str:
    profile = load_profiles().get(stage.difficulty)
    diff = profile.label if profile else stage.difficulty.title()
    return diff if stage.mode == "keys" else f"{get_mode(stage.mode).name} {diff}"


def launch_stage(app, run, replace: bool = False) -> bool:
    """Push (or swap in) gameplay for the run's current stage, skipping unplayable ones.

    Shows the run summary instead when nothing is left. Returns True if a song started.
    """
    from .gameplay import GameplayScene

    go = app.replace if replace else app.push
    while not run.finished:
        stage = run.current
        song = app.library.get(stage.song_id)
        if song is None:
            run.skip("song was deleted")
        else:
            chart, stem = stage_chart(song, stage, app.settings)
            if chart is not None and chart.notes:
                run.start_stage()
                go(GameplayScene(app, song, chart, stem, run.modifiers_for(stage), run=run))
                return True
            run.skip("no chart to play")
        if not run.advance():
            break
    go(RunSummaryScene(app, run))
    return False


class RunSummaryScene(Scene):
    """End of a playlist (and, later, a roguelike run): every song's result plus totals."""

    def __init__(self, app, run):
        super().__init__(app)
        self.run = run
        self.t = 0.0
        w, h = self.size
        theme = self.theme
        self.list_rect = pygame.Rect(self.s(40), self.s(110), self.s(820), h - self.s(110) - self.s(120))
        self.side = pygame.Rect(self.s(884), self.s(110), w - self.s(924), self.list_rect.height)
        self.list_img = panel(self.list_rect.size, self.ui)
        self.side_img = panel(self.side.size, self.ui)
        bh = self.s(62)
        self.again_btn = Button(self.ui, (w - self.s(40) - self.s(500), h - self.s(92), self.s(240), bh),
                                "Play again", self.again, color=theme.c("accent3"), sublabel="R")
        self.done_btn = Button(self.ui, (w - self.s(40) - self.s(240), h - self.s(92), self.s(240), bh), "Done",
                               self.done, color=theme.c("accent"), sublabel="Enter")
        self.group = ButtonGroup([self.done_btn, self.again_btn], horizontal=True)
        self.titles = {}
        for stage in run.stages:
            song = app.library.get(stage.song_id)
            self.titles[stage.song_id] = song.title if song else "(deleted song)"

    def enter(self) -> None:
        self.app.sfx("ui_select")

    def done(self) -> None:
        self.app.pop()

    def again(self) -> None:
        if hasattr(self.run, "again"):
            launch_stage(self.app, self.run.again(), replace=True)

    def handle_event(self, e) -> None:
        if e.type == pygame.KEYDOWN:
            if e.key in (pygame.K_ESCAPE, pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                self.done()
                return
            if e.key == pygame.K_r:
                self.again()
                return
        self.group.handle_event(e)

    def update(self, dt: float) -> None:
        self.t += dt
        self.group.update(dt)

    def draw(self, surf) -> None:
        self.app.background.draw(surf)
        theme = self.theme
        run = self.run
        title = f"{run.name}  -  complete!" if not any(s.result and s.result.get("failed") for s in run.stages) \
            else f"{run.name}  -  finished"
        self.fonts.draw(surf, title, (self.s(40), self.s(22)), "display", 42, (255, 255, 255), outline=5, shadow=5,
                        max_width=1100)
        sub = "Shuffled playlist" if getattr(run, "shuffled", False) else "Playlist"
        self.fonts.draw(surf, f"{sub}  -  {len(run.stages)} songs", (self.s(42), self.s(74)), "bold", 20,
                        theme.c("text_dim"), outline=2)
        surf.blit(self.list_img, self.list_rect)
        r = self.list_rect
        row_h = self.s(46)
        rows = max(1, (r.height - self.s(30)) // row_h)
        y = r.y + self.s(16)
        for i, stage in enumerate(run.stages[:rows]):
            k = ease_out_cubic(min(1.0, max(0.0, (self.t - 0.06 * i) / 0.35)))
            x = r.x + self.s(22) + int((1 - k) * self.s(40))
            res = stage.result
            dim = stage.skipped or not res
            color = theme.c("text_dim") if dim else (255, 255, 255)
            self.fonts.draw(surf, f"{i + 1}.", (x, y + self.s(8)), "bold", 20, theme.c("text_dim"), outline=2)
            self.fonts.draw(surf, self.titles[stage.song_id], (x + self.s(40), y + self.s(6)), "bold", 22, color,
                            outline=2, max_width=330)
            mode_color = hex_to_rgb(get_mode(stage.mode).color) if stage.mode in MODES else theme.c("accent2")
            self.fonts.draw(surf, stage_label(stage), (x + self.s(390), y + self.s(9)), "bold", 18, mode_color,
                            outline=2)
            if stage.skipped:
                info, gcolor, grade = f"skipped: {stage.skipped}", theme.c("text_dim"), ""
            elif res is None:
                info, gcolor, grade = "not played", theme.c("text_dim"), ""
            else:
                grade = "F" if res.get("failed") else res.get("grade", "?")
                gcolor = theme.c("bad") if res.get("failed") else theme.c("accent2")
                info = f"{res.get('accuracy', 0) * 100:.2f}%   {res.get('score', 0):,}"
            self.fonts.draw(surf, info, (r.right - self.s(80), y + self.s(9)), "bold", 18, color, anchor="topright",
                            outline=2)
            if grade:
                self.fonts.draw(surf, grade, (r.right - self.s(28), y + self.s(2)), "display", 28, gcolor,
                                anchor="topright", outline=3)
            y += row_h
        if len(run.stages) > rows:
            self.fonts.draw(surf, f"...and {len(run.stages) - rows} more", (r.centerx, r.bottom - self.s(26)), "ui",
                            17, theme.c("text_dim"), anchor="center", outline=2)

        surf.blit(self.side_img, self.side)
        tot = run.totals()
        s = self.side
        pop = ease_out_back(min(1.0, self.t / 0.6))
        big = self.fonts.render(f"{int(tot['score'] * min(1.0, self.t / 1.2)):,}", "display", 44, (255, 255, 255),
                                outline=5, shadow=5)
        if pop < 0.995:
            big = pygame.transform.smoothscale(big, (max(1, int(big.get_width() * pop)),
                                                     max(1, int(big.get_height() * pop))))
        self.fonts.draw(surf, "Total score", (s.centerx, s.y + self.s(30)), "bold", 20, theme.c("text_dim"),
                        anchor="center", outline=2)
        surf.blit(big, big.get_rect(center=(s.centerx, s.y + self.s(84))))
        stats = [("Accuracy", f"{tot['accuracy'] * 100:.2f}%"), ("Cleared", f"{tot['cleared']} / {len(run.stages)}"),
                 ("Full combos", str(tot["full_combos"])), ("Misses", str(tot["misses"]))]
        y = s.y + self.s(150)
        for label, value in stats:
            self.fonts.draw(surf, label, (s.x + self.s(26), y), "bold", 21, theme.c("text_dim"), outline=2)
            self.fonts.draw(surf, value, (s.right - self.s(26), y), "display", 24, (255, 255, 255), anchor="topright",
                            outline=3)
            y += self.s(46)
        self.group.draw(surf)
