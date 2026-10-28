"""Results: grade, score, judgement breakdown and a timing histogram that can
fix your audio offset in one click."""

from __future__ import annotations

import numpy as np
import pygame

from ..gameplay.rules import load_rules
from ..render.fx import ease_out_back, ease_out_cubic, ease_out_elastic
from ..render.widgets import Button, ButtonGroup, draw_bar, panel
from ..util import darken, lighten
from .base import Scene


class ResultsScene(Scene):
    def __init__(self, app, song, chart, difficulty: str, summary: dict, modifier_ids, mods, errors=(), run=None):
        super().__init__(app)
        self.run = run
        self.song = song
        self.chart = chart
        self.difficulty = difficulty
        self.summary = summary
        self.modifier_ids = list(modifier_ids)
        self.mods = mods
        self.errors_ms = np.array(errors, dtype=float) * 1000.0
        self.rules = load_rules()
        self.t = 0.0
        self.new_best = False
        w, h = self.size
        theme = self.theme
        self.left = pygame.Rect(self.s(40), self.s(110), self.s(470), self.s(500))
        self.right = pygame.Rect(self.s(536), self.s(110), w - self.s(576), self.s(500))
        self.left_img = panel(self.left.size, self.ui)
        self.right_img = panel(self.right.size, self.ui)
        bh = self.s(62)
        self.retry_btn = Button(self.ui, (w - self.s(40) - self.s(460), h - self.s(92), self.s(210), bh), "Retry",
                                self.retry, color=theme.c("accent3"), sublabel="R")
        self.next_btn = Button(self.ui, (w - self.s(40) - self.s(236), h - self.s(92), self.s(236), bh), "Continue",
                               self.done, color=theme.c("accent"), sublabel="Enter")
        self.buttons = [self.next_btn, self.retry_btn]
        mean = float(self.errors_ms.mean()) if len(self.errors_ms) else 0.0
        self.suggest = round(mean) if len(self.errors_ms) >= 30 and abs(mean) >= 10 and not summary["failed"] else 0
        self.offset_btn = None
        if self.suggest:
            self.offset_btn = Button(self.ui, (self.s(40), h - self.s(92), self.s(420), bh),
                                     f"Fix offset ({self.suggest:+d} ms)", self.apply_offset,
                                     color=theme.c("accent4"), size=26, sublabel="O")
            self.buttons.append(self.offset_btn)
        self.group = ButtonGroup(self.buttons, horizontal=True)

    def enter(self) -> None:
        ranked = all(getattr(m, "ranked", True) for m in self.mods)
        if ranked and not self.summary["failed"]:
            self.new_best = self.app.scores.record(self.song.id, self.difficulty, self.summary)
        self.app.sfx("ui_select")
        self.app.menu_music.play(self.song)

    # ------------------------------------------------------------ actions
    def retry(self) -> None:
        from .gameplay import GameplayScene

        self.app.replace(GameplayScene(self.app, self.song, self.chart, self.difficulty, self.modifier_ids,
                                       run=self.run))

    def done(self) -> None:
        self.app.pop(select=self.song.id)

    def apply_offset(self) -> None:
        settings = self.app.settings
        settings.audio_offset_ms = float(max(-300, min(300, settings.audio_offset_ms + self.suggest)))
        settings.save()
        self.app.toasts.show(f"Audio offset is now {settings.audio_offset_ms:+.0f} ms", self.theme.c("good"))
        if self.offset_btn is not None:
            self.offset_btn.visible = False
            self.offset_btn.enabled = False
        self.suggest = 0

    def handle_event(self, e) -> None:
        if e.type == pygame.KEYDOWN:
            if e.key in (pygame.K_ESCAPE, pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                self.done()
                return
            if e.key == pygame.K_r:
                self.retry()
                return
            if e.key == pygame.K_o and self.suggest:
                self.apply_offset()
                return
        self.group.handle_event(e)

    def update(self, dt: float) -> None:
        self.t += dt
        self.group.update(dt)

    # ------------------------------------------------------------ drawing
    def draw(self, surf) -> None:
        self.app.background.draw(surf)
        w, h = self.size
        theme = self.theme
        s = self.summary
        self.fonts.draw(surf, self.song.title, (self.s(40), self.s(22)), "display", 40, (255, 255, 255), outline=5,
                        shadow=5, max_width=820)
        sub = f"{self.song.artist}  -  {self.difficulty.title()}"
        if self.mods:
            sub += "  -  " + ", ".join(m.name for m in self.mods)
        self.fonts.draw(surf, sub, (self.s(42), self.s(72)), "bold", 20, theme.c("text_dim"), outline=2,
                        max_width=1000)

        # ---- left: grade + score
        surf.blit(self.left_img, self.left)
        grade = s["grade"]
        gcolor = theme.c("bad") if s["failed"] else dict((g, c) for g, _, c in self.rules.grades).get(grade, (255,) * 3)
        scale = ease_out_elastic(min(1.0, self.t / 0.9))
        img = self.fonts.render(grade, "display", 170, gcolor, outline=10, shadow=12)
        if scale < 0.995:
            img = pygame.transform.smoothscale(img, (max(1, int(img.get_width() * scale)),
                                                     max(1, int(img.get_height() * scale))))
        surf.blit(img, img.get_rect(center=(self.left.centerx, self.left.y + self.s(130))))
        badges = []
        if s["failed"]:
            badges.append(("FAILED", theme.c("bad")))
        elif s.get("full_combo"):
            badges.append(("FULL COMBO!", theme.c("accent2")))
        if self.new_best:
            badges.append(("NEW BEST!", theme.c("accent4")))
        for i, (label, color) in enumerate(badges):
            pop = ease_out_back(min(1.0, max(0.0, (self.t - 0.6 - i * 0.15) / 0.25)))
            if pop > 0:
                b = self.fonts.render(label, "display", 30, color, outline=4, shadow=4)
                if pop < 0.995:
                    b = pygame.transform.smoothscale(b, (max(1, int(b.get_width() * pop)), max(1, int(b.get_height() * pop))))
                surf.blit(b, b.get_rect(center=(self.left.centerx, self.left.y + self.s(250) + i * self.s(40))))
        count = ease_out_cubic(min(1.0, self.t / 1.2))
        self.fonts.draw(surf, f"{int(s['score'] * count):,}", (self.left.centerx, self.left.y + self.s(350)),
                        "display", 56, (255, 255, 255), anchor="center", outline=5, shadow=6)
        line = f"{s['accuracy'] * 100 * count:.2f}%   -   max combo {s['max_combo']}"
        self.fonts.draw(surf, line, (self.left.centerx, self.left.y + self.s(410)), "bold", 24, (255, 255, 255),
                        anchor="center", outline=3)
        self.fonts.draw(surf, f"{s['notes']} notes", (self.left.centerx, self.left.y + self.s(450)), "ui", 19,
                        theme.c("text_dim"), anchor="center", outline=2)

        # ---- right: breakdown + timing
        surf.blit(self.right_img, self.right)
        r = self.right
        counts = s["counts"]
        rows = [(j.label, counts.get(j.id, 0), j.color) for j in self.rules.judgements]
        rows.append((self.rules.miss.label, counts.get("miss", 0), self.rules.miss.color))
        rows.append(("HOLDS", f"{counts.get('hold_ok', 0)} / {counts.get('hold_ok', 0) + counts.get('hold_drop', 0)}",
                     theme.c("accent3")))
        total = max(1, sum(v for _, v, _ in rows[:-1]))
        y = r.y + self.s(28)
        for i, (label, value, color) in enumerate(rows):
            grow = ease_out_cubic(min(1.0, max(0.0, (self.t - 0.15 * i) / 0.5)))
            self.fonts.draw(surf, label, (r.x + self.s(28), y), "display", 26, color, outline=3)
            self.fonts.draw(surf, str(value), (r.x + self.s(300), y), "display", 26, (255, 255, 255),
                            anchor="topright", outline=3)
            if isinstance(value, int):
                bar = pygame.Rect(r.x + self.s(320), y + self.s(8), r.width - self.s(350), self.s(16))
                draw_bar(surf, bar, grow * value / total, color, self.ui)
            y += self.s(42)
        self._draw_histogram(surf, pygame.Rect(r.x + self.s(28), r.y + self.s(330), r.width - self.s(56), self.s(110)))
        for b in self.buttons:
            b.draw(surf)

    def _draw_histogram(self, surf, rect: pygame.Rect) -> None:
        theme = self.theme
        max_ms = self.rules.max_window * 1000.0
        pygame.draw.rect(surf, darken(theme.c("panel"), 0.25), rect, border_radius=self.s(10))
        errs = self.errors_ms
        if len(errs) == 0:
            self.fonts.draw(surf, "No hits to show", rect.center, "bold", 20, theme.c("text_dim"), anchor="center")
            return
        bins = 34
        hist, edges = np.histogram(np.clip(errs, -max_ms, max_ms), bins=bins, range=(-max_ms, max_ms))
        peak = max(1, hist.max())
        bw = rect.width / bins
        for i, v in enumerate(hist):
            if v == 0:
                continue
            center = (edges[i] + edges[i + 1]) / 2
            judgement = self.rules.judge(center / 1000.0)
            color = judgement.color if judgement else theme.c("bad")
            bh = (rect.height - self.s(10)) * v / peak
            pygame.draw.rect(surf, color, (rect.x + i * bw + 1, rect.bottom - bh - self.s(4), bw - 2, bh),
                             border_radius=self.s(3))
        pygame.draw.line(surf, (255, 255, 255), (rect.centerx, rect.y + self.s(4)), (rect.centerx, rect.bottom - 4), 2)
        mean, std = float(errs.mean()), float(errs.std())
        mx = rect.centerx + mean / max_ms * rect.width / 2
        pygame.draw.line(surf, theme.c("accent2"), (mx, rect.y), (mx, rect.bottom), max(2, self.s(3)))
        self.fonts.draw(surf, "early", (rect.x + self.s(6), rect.y + self.s(4)), "bold", 16, theme.c("text_dim"))
        self.fonts.draw(surf, "late", (rect.right - self.s(6), rect.y + self.s(4)), "bold", 16, theme.c("text_dim"),
                        anchor="topright")
        tendency = "on time" if abs(mean) < 5 else ("late" if mean > 0 else "early")
        text = f"Average {mean:+.1f} ms ({tendency})  -  spread +/-{std:.1f} ms"
        self.fonts.draw(surf, text, (rect.centerx, rect.bottom + self.s(12)), "bold", 20, lighten(theme.c("accent2"), 0.2),
                        anchor="midtop", outline=2)
