"""Small "add a song" window that pops up from the bottom-left of song select.

Paste a link (or a file path, or drop a file), pick what plays behind the
notes, and keep browsing while it downloads: the import runs on a thread and
the window can be tucked away into a little progress chip.
"""

from __future__ import annotations

import pygame

from ..library.importer import BACKGROUND_LABELS, ImportJob
from ..render import vector as V
from ..render.fx import clamp01, ease_in_cubic, ease_out_back
from ..render.widgets import Button, FileDialog, Segmented, TextInput, draw_bar, get_clipboard, panel
from ..util import darken

W, H = 500, 268


class ImportPopup:
    def __init__(self, scene, on_done):
        self.scene = scene
        self.app = scene.app
        self.ui = scene.ui
        self.on_done = on_done
        s = scene.s
        theme = scene.theme
        self.w, self.h = s(W), s(H)
        self.anchor = (s(24), scene.size[1] - s(24))          # bottom-left corner on screen
        self.bg = panel((self.w, self.h), self.ui, alpha=240)
        self.layer = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
        pad = s(20)
        self.input = TextInput(self.ui, (pad, s(62), self.w - 2 * pad, s(48)), "YouTube link or audio file path...",
                               on_submit=lambda t: self.start(t), size=19)
        self.choice = Segmented(self.ui, (pad, s(144), self.w - 2 * pad, s(36)),
                                [(k, v) for k, v in BACKGROUND_LABELS.items()], self.app.settings.import_background,
                                on_change=self._set_background, size=15)
        bh, by = s(46), self.h - s(46) - s(18)
        self.paste_btn = Button(self.ui, (pad, by, s(110), bh), "Paste", self.paste, color=theme.c("panel_light"),
                                size=21)
        self.browse_btn = Button(self.ui, (pad + s(120), by, s(130), bh), "Browse", self.browse,
                                 color=theme.c("accent3"), size=21)
        self.add_btn = Button(self.ui, (self.w - pad - s(150), by, s(150), bh), "Add song",
                              lambda: self.start(self.input.text), color=theme.c("accent"), size=22, sublabel=None)
        self.cancel_btn = Button(self.ui, (self.w - pad - s(130), by, s(130), bh), "Cancel", self.cancel,
                                 color=theme.c("bad"), size=21)
        self.hide_btn = Button(self.ui, (pad, by, s(150), bh), "Keep browsing", self.close,
                               color=theme.c("panel_light"), size=18)
        self.buttons = [self.paste_btn, self.browse_btn, self.add_btn]
        self.busy_buttons = [self.hide_btn, self.cancel_btn]
        self.open = False
        self.t = 0.0           # 0 = hidden, 1 = fully open
        self.clock = 0.0
        self.job: ImportJob | None = None
        self.dialog: FileDialog | None = None
        self.error: str | None = None
        self.shown_progress = 0.0
        self.chip_rect = pygame.Rect(0, 0, 0, 0)

    # ------------------------------------------------------------ state
    @property
    def busy(self) -> bool:
        return self.job is not None and not self.job.done

    @property
    def visible(self) -> bool:
        return self.t > 0.0

    def toggle(self) -> None:
        self.close() if self.open else self.show()

    def show(self) -> None:
        if not self.open:
            self.open = True
            self.input.focused = not self.busy
            self.app.sfx("ui_select")
            pygame.key.start_text_input()

    def close(self) -> None:
        if self.open:
            self.open = False
            self.input.focused = False
            self.app.sfx("ui_back")
            pygame.key.stop_text_input()

    def _set_background(self, value: str) -> None:
        self.app.settings.import_background = value
        self.app.settings.save()

    # ------------------------------------------------------------ actions
    def paste(self) -> None:
        text = get_clipboard().strip()
        if text:
            self.input.set_text(text)
            self.input.focused = True
        else:
            self.app.toasts.show("Clipboard is empty")

    def browse(self) -> None:
        if self.dialog is None:
            self.dialog = FileDialog()

    def start(self, source: str) -> None:
        source = (source or "").strip()
        if not source:
            self.error = "Paste a link or pick a file first."
            self.app.sfx("ui_error")
            return
        if self.busy:
            return
        self.error = None
        self.shown_progress = 0.0
        self.input.set_text(source)
        self.input.focused = False
        self.job = ImportJob(source, self.app.library, lanes=self.app.settings.lane_count,
                             background=self.app.settings.import_background)
        self.job.start()
        self.show()

    def cancel(self) -> None:
        if self.busy:
            self.job.cancel()

    # ------------------------------------------------------------ events
    def _local(self, e):
        if hasattr(e, "pos"):
            x, y = self.origin()
            return pygame.event.Event(e.type, {**e.dict, "pos": (e.pos[0] - x, e.pos[1] - y)})
        return e

    def origin(self) -> tuple[int, int]:
        return self.anchor[0], self.anchor[1] - self.h

    def rect(self) -> pygame.Rect:
        return pygame.Rect(*self.origin(), self.w, self.h)

    def handle_event(self, e) -> bool:
        """True if the popup used the event (keyboard always, while open)."""
        if not self.open:
            if (e.type == pygame.MOUSEBUTTONDOWN and e.button == 1 and self.chip_rect.collidepoint(e.pos)
                    and self.busy):
                self.show()
                return True
            return False
        if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
            self.close()
            return True
        if e.type == pygame.KEYDOWN and e.key == pygame.K_TAB and not self.busy:
            self.choice.step(-1 if e.mod & pygame.KMOD_SHIFT else 1)
            return True
        local = self._local(e)
        inside = hasattr(e, "pos") and self.rect().collidepoint(e.pos)
        if self.busy:
            for b in self.busy_buttons:
                if b.handle_event(local):
                    return True
        else:
            if self.input.handle_event(local):
                return True
            if self.choice.handle_event(local):
                return True
            for b in self.buttons:
                if b.handle_event(local):
                    return True
            if e.type == pygame.KEYDOWN and e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.start(self.input.text)
                return True
        if e.type in (pygame.KEYDOWN, pygame.KEYUP, pygame.TEXTINPUT):
            return True
        return inside and e.type != pygame.MOUSEMOTION

    # ------------------------------------------------------------ frame
    def update(self, dt: float) -> None:
        self.clock += dt
        speed = 1 / 0.28 if self.open else 1 / 0.16
        self.t = clamp01(self.t + (dt * speed if self.open else -dt * speed))
        self.input.update(dt)
        for b in self.buttons + self.busy_buttons:
            b.update(dt)
        if self.dialog is not None and self.dialog.done:
            if self.dialog.result:
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
                    self.show()
                elif job.song is not None:
                    self.app.sfx("ui_select")
                    note = "Already in your library" if job.already_existed else "Song added"
                    self.app.toasts.show(f"{note}: {job.song.title}", self.scene.theme.c("good"), 4)
                    self.input.set_text("")
                    self.close()
                    self.on_done(job.song)

    def draw(self, surf) -> None:
        if not self.visible:
            if self.busy:
                self._draw_chip(surf)
            return
        layer = self.layer
        layer.fill((0, 0, 0, 0))
        layer.blit(self.bg, (0, 0))
        self._draw_contents(layer)
        k = ease_out_back(self.t) if self.open else ease_in_cubic(self.t)
        x, y = self.origin()
        if k >= 0.999:
            surf.blit(layer, (x, y))
            return
        # grow out of the bottom-left corner
        scale = max(0.05, 0.6 + 0.4 * k)
        img = pygame.transform.smoothscale(layer, (max(1, int(self.w * scale)), max(1, int(self.h * scale))))
        img.set_alpha(int(255 * clamp01(k * 1.6)))
        lift = (1 - k) * self.scene.s(40)
        surf.blit(img, img.get_rect(bottomleft=(self.anchor[0], self.anchor[1] + lift)))

    def _draw_contents(self, layer) -> None:
        scene = self.scene
        s, fonts, theme = scene.s, scene.fonts, scene.theme
        pad = s(20)
        fonts.draw(layer, "Add a song", (pad, s(14)), "display", 26, (255, 255, 255), outline=3)
        fonts.draw(layer, "Esc to close", (self.w - pad, s(24)), "ui", 15, theme.c("text_dim"), anchor="topright")
        if self.busy:
            job = self.job
            dots = "." * (int(self.clock * 3) % 4)
            fonts.draw(layer, f"{job.stage}{dots}", (pad, s(70)), "bold", 22, (255, 255, 255), outline=2)
            bar = pygame.Rect(pad + s(3), s(110), self.w - 2 * pad - s(6), s(24))
            draw_bar(layer, bar, self.shown_progress, theme.c("accent2"), self.ui)
            fonts.draw(layer, f"{int(self.shown_progress * 100)}%  -  {job.source}", (pad, s(146)), "ui", 15,
                       theme.c("text_dim"), max_width=W - 40)
            fonts.draw(layer, f"Background: {BACKGROUND_LABELS.get(job.background, job.background)}",
                       (pad, s(170)), "ui", 15, theme.c("text_dim"))
            for b in self.busy_buttons:
                b.draw(layer)
            return
        self.input.draw(layer)
        fonts.draw(layer, "Behind the notes", (pad, s(120)), "bold", 16, theme.c("text_dim"))
        fonts.draw(layer, "Tab to switch", (self.w - pad, s(121)), "ui", 14, theme.c("text_dim"), anchor="topright")
        self.choice.draw(layer)
        if self.dialog is not None:
            msg, color = "Waiting for the file picker...", (255, 255, 255)
        elif self.error:
            msg, color = self.error, theme.c("bad")
        else:
            msg, color = "Video needs a YouTube link or a video file.", theme.c("text_dim")
        fonts.draw(layer, msg, (pad, s(186)), "bold" if self.error else "ui", 15, color, max_width=W - 40)
        for b in self.buttons:
            b.draw(layer)

    def _draw_chip(self, surf) -> None:
        scene = self.scene
        s = scene.s
        pct = int(self.shown_progress * 100)
        txt = scene.fonts.render(f"Importing  {pct}%", "bold", 17, (255, 255, 255), outline=2)
        w, h = txt.get_width() + s(28), s(38)
        chip = V.rounded_rect((w, h), h / 2, darken(scene.theme.c("accent3"), 0.1), scene.theme.c("ink"),
                              outline=max(2, s(3)))
        fill = int((w - s(8)) * self.shown_progress)
        if fill > 0:
            pygame.draw.rect(chip, scene.theme.c("accent3"), (s(4), s(4), fill, h - s(8)), border_radius=h // 2)
        chip.blit(txt, txt.get_rect(center=(w / 2, h / 2)))
        self.chip_rect = chip.get_rect(bottomleft=self.anchor)
        surf.blit(chip, self.chip_rect)
