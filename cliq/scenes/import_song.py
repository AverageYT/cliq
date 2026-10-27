"""Add a song from a YouTube link or an audio file (browse or drag & drop)."""

from __future__ import annotations

import pygame

from ..library.importer import ImportJob
from ..render.widgets import Button, FileDialog, TextInput, draw_bar, get_clipboard, panel
from .base import Scene


class ImportScene(Scene):
    text_input = True

    def __init__(self, app):
        super().__init__(app)
        w, h = self.size
        theme = self.theme
        cw = self.s(540)
        gap = self.s(36)
        x1 = w // 2 - cw - gap // 2
        x2 = w // 2 + gap // 2
        top = self.s(140)
        ch = self.s(330)
        self.card1 = pygame.Rect(x1, top, cw, ch)
        self.card2 = pygame.Rect(x2, top, cw, ch)
        self.card_img = panel((cw, ch), self.ui)
        pad = self.s(28)
        self.url = TextInput(self.ui, (x1 + pad, top + self.s(150), cw - 2 * pad, self.s(56)),
                             "Paste a YouTube link...", on_submit=lambda t: self.start(t))
        self.url.focused = True
        self.path = TextInput(self.ui, (x2 + pad, top + self.s(150), cw - 2 * pad, self.s(56)),
                              "...or type a file path", on_submit=lambda t: self.start(t))
        bh = self.s(60)
        self.paste_btn = Button(self.ui, (x1 + pad, top + ch - bh - pad, self.s(170), bh), "Paste", self.paste,
                                color=theme.c("panel_light"), size=26)
        self.go_btn = Button(self.ui, (x1 + cw - pad - self.s(270), top + ch - bh - pad, self.s(270), bh),
                             "Download", lambda: self.start(self.url.text), color=theme.c("accent"), size=28)
        self.browse_btn = Button(self.ui, (x2 + pad, top + ch - bh - pad, self.s(230), bh), "Browse...", self.browse,
                                 color=theme.c("accent3"), size=28)
        self.file_go = Button(self.ui, (x2 + cw - pad - self.s(200), top + ch - bh - pad, self.s(200), bh), "Import",
                              lambda: self.start(self.path.text), color=theme.c("accent"), size=28)
        self.back_btn = Button(self.ui, (self.s(36), h - self.s(96), self.s(160), self.s(56)), "Back", self.back,
                               color=theme.c("panel_light"), size=26)
        self.buttons = [self.paste_btn, self.go_btn, self.browse_btn, self.file_go, self.back_btn]
        self.cancel_btn = Button(self.ui, (w // 2 - self.s(110), self.s(520), self.s(220), self.s(58)), "Cancel",
                                 self.cancel, color=theme.c("bad"), size=26)
        self.job: ImportJob | None = None
        self.dialog: FileDialog | None = None
        self.error: str | None = None
        self.shown_progress = 0.0
        self.t = 0.0
        self.big_panel = panel((self.s(760), self.s(330)), self.ui)

    # ------------------------------------------------------------ actions
    def paste(self) -> None:
        text = get_clipboard().strip()
        if text:
            self.url.set_text(text)
            self.url.focused, self.path.focused = True, False
        else:
            self.app.toasts.show("Clipboard is empty")

    def browse(self) -> None:
        if self.dialog is None:
            self.dialog = FileDialog()

    def start(self, source: str) -> None:
        source = (source or "").strip()
        if not source:
            self.error = "Paste a YouTube link or pick a file first."
            self.app.sfx("ui_error")
            return
        if self.job is not None and not self.job.done:
            return
        self.error = None
        self.shown_progress = 0.0
        self.app.menu_music.stop()
        self.job = ImportJob(source, self.app.library, lanes=self.app.settings.lane_count)
        self.job.start()

    def cancel(self) -> None:
        if self.job is not None and not self.job.done:
            self.job.cancel()

    def back(self) -> None:
        if self.job is not None and not self.job.done:
            self.cancel()
            return
        self.app.sfx("ui_back")
        self.app.pop()

    # ------------------------------------------------------------ events
    @property
    def busy(self) -> bool:
        return self.job is not None and not self.job.done

    def handle_event(self, e) -> None:
        if e.type == pygame.DROPFILE:
            self.path.set_text(e.file)
            self.start(e.file)
            return
        if self.busy:
            if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
                self.cancel()
            self.cancel_btn.handle_event(e)
            return
        if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE and not (self.url.focused or self.path.focused):
            self.back()
            return
        if e.type == pygame.KEYDOWN and e.key == pygame.K_TAB:
            self.url.focused, self.path.focused = not self.url.focused, self.url.focused
            return
        if self.url.handle_event(e) or self.path.handle_event(e):
            if e.type == pygame.MOUSEBUTTONDOWN:
                (self.path if self.url.focused else self.url).focused = False
            return
        if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
            self.back()
            return
        for b in self.buttons:
            if b.handle_event(e):
                return

    def update(self, dt: float) -> None:
        self.t += dt
        self.url.update(dt)
        self.path.update(dt)
        for b in self.buttons + [self.cancel_btn]:
            b.update(dt)
        if self.dialog is not None and self.dialog.done:
            if self.dialog.result:
                self.path.set_text(self.dialog.result)
                self.start(self.dialog.result)
            elif self.dialog.error:
                self.error = self.dialog.error
            self.dialog = None
        if self.job is not None:
            self.shown_progress += (self.job.progress - self.shown_progress) * min(1.0, dt * 6)
            if self.job.done:
                job, self.job = self.job, None
                if job.error:
                    self.error = job.error
                    self.app.sfx("ui_error")
                elif job.song is not None:
                    self.app.sfx("ui_select")
                    note = "Already in your library" if job.already_existed else "Song added - charts are ready!"
                    self.app.toasts.show(f"{note}: {job.song.title}", self.theme.c("good"), 4)
                    self._finish(job.song.id)

    def _finish(self, song_id: str) -> None:
        from .song_select import SongSelectScene

        below = self.app.stack[-2] if len(self.app.stack) > 1 else None
        if isinstance(below, SongSelectScene):
            self.app.pop(select=song_id)
        else:
            self.app.replace(SongSelectScene(self.app, select=song_id))

    # ------------------------------------------------------------ drawing
    def draw(self, surf) -> None:
        self.app.background.draw(surf)
        w, h = self.size
        theme = self.theme
        self.title(surf, "Add a song", 70, 56)
        if self.busy:
            self._draw_progress(surf)
            return
        for rect, heading, sub in ((self.card1, "From YouTube", "Any video link works - we grab the audio."),
                                   (self.card2, "From your computer", "mp3, ogg, wav, flac, m4a, opus...")):
            surf.blit(self.card_img, rect)
            self.fonts.draw(surf, heading, (rect.x + self.s(28), rect.y + self.s(26)), "display", 34,
                            (255, 255, 255), outline=4, shadow=4)
            self.fonts.draw(surf, sub, (rect.x + self.s(30), rect.y + self.s(84)), "bold", 19, theme.c("text_dim"),
                            outline=2)
        self.url.draw(surf)
        self.path.draw(surf)
        self.fonts.draw(surf, "Tip: you can also drop a file anywhere on this window",
                        (self.card2.x + self.s(30), self.card2.y + self.s(214)), "ui", 16, theme.c("text_dim"),
                        outline=2)
        for b in self.buttons:
            b.draw(surf)
        if self.dialog is not None:
            self.fonts.draw(surf, "Waiting for the file picker...", (w // 2, self.card1.bottom + self.s(46)), "bold",
                            22, (255, 255, 255), anchor="center", outline=3)
        if self.error:
            self.fonts.draw(surf, self.error, (w // 2, self.card1.bottom + self.s(46)), "bold", 22,
                            theme.c("bad"), anchor="center", outline=3, max_width=1150)
        lines = ("We find the BPM and beat, then chart Easy to Expert for you.",
                 "Tweak any chart or map your own in the editor (E in song select).")
        for i, line in enumerate(lines):
            self.fonts.draw(surf, line, (w // 2 + self.s(90), h - self.s(84) + i * self.s(28)), "ui", 19,
                            (255, 255, 255), anchor="center", outline=2)

    def _draw_progress(self, surf) -> None:
        w, h = self.size
        theme = self.theme
        r = self.big_panel.get_rect(center=(w // 2, self.s(380)))
        surf.blit(self.big_panel, r)
        stage = self.job.stage if self.job else ""
        dots = "." * (int(self.t * 3) % 4)
        self.fonts.draw(surf, f"{stage}{dots}", (w // 2, r.y + self.s(70)), "display", 38, (255, 255, 255),
                        anchor="center", outline=4, shadow=5)
        bar = pygame.Rect(0, 0, self.s(600), self.s(34))
        bar.center = (w // 2, r.y + self.s(150))
        draw_bar(surf, bar, self.shown_progress, theme.c("accent2"), self.ui)
        self.fonts.draw(surf, f"{int(self.shown_progress * 100)}%", (w // 2, r.y + self.s(205)), "bold", 24,
                        (255, 255, 255), anchor="center", outline=3)
        src = self.job.source if self.job else ""
        self.fonts.draw(surf, src, (w // 2, r.y + self.s(250)), "ui", 17, theme.c("text_dim"), anchor="center",
                        outline=2, max_width=700)
        self.cancel_btn.draw(surf)
