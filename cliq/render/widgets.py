"""Chunky cartoon UI widgets: buttons, pills, text fields, toasts.

All sizes are given at 720p and multiplied by ``ui.scale``.
"""

from __future__ import annotations

import subprocess
import sys
import threading

import pygame

from ..util import darken, lighten
from . import vector as V
from .fx import ease_out_back


class UI:
    """Shared context for widgets (fonts, theme, scale, sounds)."""

    def __init__(self, fonts, theme, scale: float, sound=None):
        self.fonts = fonts
        self.theme = theme
        self.scale = scale
        self.sound = sound or (lambda name: None)

    def s(self, v: float) -> int:
        return int(round(v * self.scale))


# --------------------------------------------------------------------------- clipboard / files
def get_clipboard() -> str:
    try:
        if hasattr(pygame.scrap, "get_text"):
            return pygame.scrap.get_text() or ""
        if not pygame.scrap.get_init():
            pygame.scrap.init()
        raw = pygame.scrap.get(pygame.SCRAP_TEXT)
        if raw:
            return raw.decode("utf-8", "ignore").rstrip("\x00")
    except Exception:
        pass
    try:  # last resort: ask tkinter in a separate process
        out = subprocess.run([sys.executable, "-c",
                              "import tkinter as t;r=t.Tk();r.withdraw();print(r.clipboard_get(),end='')"],
                             capture_output=True, text=True, timeout=3)
        return out.stdout
    except Exception:
        return ""


class FileDialog:
    """Native 'open file' dialog run in a helper process (keeps pygame's window responsive)."""

    SCRIPT = (
        "import sys, tkinter as t\n"
        "from tkinter import filedialog as f\n"
        "r = t.Tk(); r.withdraw(); r.attributes('-topmost', True)\n"
        "p = f.askopenfilename(title='Choose a song', filetypes=[('Audio', '*.mp3 *.ogg *.wav *.flac *.m4a "
        "*.aac *.opus *.wma *.webm *.mp4'), ('All files', '*.*')])\n"
        "sys.stdout.write(p or '')\n"
    )

    def __init__(self):
        self.result: str | None = None
        self.error: str | None = None
        self.done = False
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        try:
            out = subprocess.run([sys.executable, "-c", self.SCRIPT], capture_output=True, text=True, timeout=600)
            if out.returncode != 0:
                self.error = "No file picker available here - drag the file onto the window instead."
            else:
                self.result = out.stdout.strip() or None
        except Exception:
            self.error = "No file picker available here - drag the file onto the window instead."
        self.done = True


# --------------------------------------------------------------------------- widgets
class Button:
    def __init__(self, ui: UI, rect: pygame.Rect, label: str, on_click=None, color=None, text_color=(255, 255, 255),
                 size: int = 30, sublabel: str | None = None, enabled: bool = True, hotkey: str | None = None,
                 role: str = "display"):
        self.ui = ui
        self.rect = pygame.Rect(rect)
        self.label = label
        self.on_click = on_click
        self.color = color or ui.theme.c("accent")
        self.text_color = text_color
        self.size = size
        self.sublabel = sublabel
        self.enabled = enabled
        self.hotkey = hotkey
        self.role = role
        self.focused = False
        self.down = False
        self.lift = 0.0
        self.visible = True
        self._cache: dict = {}

    def _face(self, state: str) -> pygame.Surface:
        key = (state, self.rect.size, self.label, self.sublabel, self.color)
        img = self._cache.get(key)
        if img is None:
            ink = self.ui.theme.c("ink")
            base = self.color if self.enabled else (120, 112, 150)
            if state == "hover":
                base = lighten(base, 0.12)
            w, h = self.rect.size
            o = max(2, self.ui.s(3.5))
            img = V.rounded_rect((w, h), min(h * 0.42, self.ui.s(22)), base, ink, outline=o,
                                 shadow=self.ui.s(6), shadow_color=(*darken(ink, 0.3), 160),
                                 gradient=((*lighten(base, 0.18), 255), (*darken(base, 0.08), 255)))
            fonts = self.ui.fonts
            if self.sublabel:
                t1 = fonts.render(self.label, self.role, self.size, self.text_color, outline=3)
                t2 = fonts.render(self.sublabel, "ui", int(self.size * 0.55), lighten(base, 0.75))
                total = t1.get_height() + t2.get_height() - self.ui.s(4)
                y = (h - total) // 2
                img.blit(t1, ((w - t1.get_width()) // 2, y))
                img.blit(t2, ((w - t2.get_width()) // 2, y + t1.get_height() - self.ui.s(4)))
            else:
                t1 = fonts.render(self.label, self.role, self.size, self.text_color, outline=3)
                img.blit(t1, ((w - t1.get_width()) // 2, (h - t1.get_height()) // 2))
            self._cache[key] = img
        return img

    @property
    def hovered(self) -> bool:
        return self.focused

    def handle_event(self, e: pygame.event.Event) -> bool:
        if not self.visible or not self.enabled:
            return False
        if e.type == pygame.MOUSEMOTION:
            inside = self.rect.collidepoint(e.pos)
            if inside and not self.focused:
                self.ui.sound("ui_move")
            self.focused = inside
        elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1 and self.rect.collidepoint(e.pos):
            self.down = True
            return True
        elif e.type == pygame.MOUSEBUTTONUP and e.button == 1:
            was = self.down
            self.down = False
            if was and self.rect.collidepoint(e.pos):
                self.click()
                return True
        return False

    def click(self) -> None:
        if self.enabled and self.on_click:
            self.ui.sound("ui_select")
            self.on_click()

    def update(self, dt: float) -> None:
        target = 1.0 if self.focused and self.enabled else 0.0
        self.lift += (target - self.lift) * min(1.0, dt * 14)

    def draw(self, surf: pygame.Surface) -> None:
        if not self.visible:
            return
        img = self._face("hover" if self.focused else "normal")
        y = self.rect.y - self.lift * self.ui.s(4) + (self.ui.s(3) if self.down else 0)
        surf.blit(img, (self.rect.x, y))


class ButtonGroup:
    """Keyboard + mouse navigation over a list of buttons."""

    def __init__(self, buttons: list[Button], horizontal: bool = False, wrap: bool = True):
        self.buttons = buttons
        self.horizontal = horizontal
        self.wrap = wrap
        self.index = 0
        self.keyboard = False
        if buttons:
            buttons[0].focused = True

    def _visible(self) -> list[int]:
        return [i for i, b in enumerate(self.buttons) if b.visible and b.enabled]

    def move(self, delta: int) -> None:
        idx = self._visible()
        if not idx:
            return
        pos = idx.index(self.index) if self.index in idx else 0
        pos = (pos + delta) % len(idx) if self.wrap else max(0, min(len(idx) - 1, pos + delta))
        self.focus(idx[pos])
        self.buttons[0].ui.sound("ui_move")

    def focus(self, i: int) -> None:
        self.index = i
        for j, b in enumerate(self.buttons):
            b.focused = j == i

    def handle_event(self, e: pygame.event.Event) -> bool:
        if e.type == pygame.KEYDOWN:
            prev, nxt = (pygame.K_LEFT, pygame.K_RIGHT) if self.horizontal else (pygame.K_UP, pygame.K_DOWN)
            if e.key == prev:
                self.move(-1)
                return True
            if e.key == nxt:
                self.move(1)
                return True
            if e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                if 0 <= self.index < len(self.buttons):
                    self.buttons[self.index].click()
                return True
        for i, b in enumerate(self.buttons):
            if b.handle_event(e):
                return True
            if e.type == pygame.MOUSEMOTION and b.focused:
                self.index = i
                for j, other in enumerate(self.buttons):
                    if j != i:
                        other.focused = False
        return False

    def update(self, dt: float) -> None:
        for b in self.buttons:
            b.update(dt)

    def draw(self, surf: pygame.Surface) -> None:
        for b in self.buttons:
            b.draw(surf)


class Pill:
    """Small toggle chip (used for modifiers)."""

    def __init__(self, ui: UI, rect, label: str, color, active: bool = False, on_toggle=None, tooltip: str = ""):
        self.ui = ui
        self.rect = pygame.Rect(rect)
        self.label = label
        self.color = color
        self.active = active
        self.on_toggle = on_toggle
        self.tooltip = tooltip
        self.hover = False
        self._faces: dict = {}

    def _face(self, active: bool) -> pygame.Surface:
        img = self._faces.get(active)
        if img is None:
            ink = self.ui.theme.c("ink")
            fill = self.color if active else self.ui.theme.c("panel_light")
            img = V.rounded_rect(self.rect.size, self.rect.height / 2, fill, ink, outline=max(2, self.ui.s(2.5)))
            txt = self.ui.fonts.render(self.label, "bold", 16, ink if active else (225, 218, 255))
            img.blit(txt, txt.get_rect(center=(self.rect.width / 2, self.rect.height / 2)))
            self._faces[active] = img
        return img

    def handle_event(self, e) -> bool:
        if e.type == pygame.MOUSEMOTION:
            self.hover = self.rect.collidepoint(e.pos)
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1 and self.rect.collidepoint(e.pos):
            self.toggle()
            return True
        return False

    def toggle(self) -> None:
        self.active = not self.active
        self.ui.sound("ui_select" if self.active else "ui_back")
        if self.on_toggle:
            self.on_toggle(self.active)

    def draw(self, surf) -> None:
        img = self._face(self.active)
        surf.blit(img, (self.rect.x, self.rect.y - (self.ui.s(2) if self.hover else 0)))


class TextInput:
    def __init__(self, ui: UI, rect, placeholder: str = "", on_submit=None, size: int = 22):
        self.ui = ui
        self.rect = pygame.Rect(rect)
        self.placeholder = placeholder
        self.on_submit = on_submit
        self.size = size
        self.text = ""
        self.cursor = 0
        self.focused = False
        self.blink = 0.0
        self._bg: dict = {}

    def set_text(self, text: str) -> None:
        self.text = text.replace("\n", " ").replace("\r", "")
        self.cursor = len(self.text)

    def insert(self, s: str) -> None:
        s = s.replace("\n", " ").replace("\r", "")
        self.text = self.text[: self.cursor] + s + self.text[self.cursor:]
        self.cursor += len(s)
        self.blink = 0.0

    def handle_event(self, e) -> bool:
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            self.focused = self.rect.collidepoint(e.pos)
            return self.focused
        if not self.focused:
            return False
        if e.type == pygame.TEXTINPUT:
            self.insert(e.text)
            return True
        if e.type == pygame.KEYDOWN:
            ctrl = e.mod & (pygame.KMOD_CTRL | pygame.KMOD_META)
            if ctrl and e.key == pygame.K_v:
                self.insert(get_clipboard().strip())
            elif ctrl and e.key in (pygame.K_a, pygame.K_BACKSPACE):
                self.text, self.cursor = "", 0
            elif e.key == pygame.K_BACKSPACE and self.cursor > 0:
                self.text = self.text[: self.cursor - 1] + self.text[self.cursor:]
                self.cursor -= 1
            elif e.key == pygame.K_DELETE:
                self.text = self.text[: self.cursor] + self.text[self.cursor + 1:]
            elif e.key == pygame.K_LEFT:
                self.cursor = max(0, self.cursor - 1)
            elif e.key == pygame.K_RIGHT:
                self.cursor = min(len(self.text), self.cursor + 1)
            elif e.key == pygame.K_HOME:
                self.cursor = 0
            elif e.key == pygame.K_END:
                self.cursor = len(self.text)
            elif e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                if self.on_submit:
                    self.on_submit(self.text)
            elif e.key == pygame.K_ESCAPE:
                self.focused = False
                return True
            else:
                return e.key not in (pygame.K_UP, pygame.K_DOWN, pygame.K_TAB, pygame.K_F11)
            self.blink = 0.0
            return True
        return False

    def update(self, dt: float) -> None:
        self.blink += dt

    def draw(self, surf) -> None:
        ink = self.ui.theme.c("ink")
        key = (self.rect.size, self.focused)
        bg = self._bg.get(key)
        if bg is None:
            edge = self.ui.theme.c("accent3") if self.focused else ink
            bg = V.rounded_rect(self.rect.size, self.ui.s(14), (255, 255, 255), edge,
                                outline=max(2, self.ui.s(3.5 if self.focused else 3)))
            self._bg[key] = bg
        surf.blit(bg, self.rect)
        pad = self.ui.s(14)
        inner = self.rect.inflate(-2 * pad, 0)
        fonts = self.ui.fonts
        if not self.text:
            img = fonts.render(self.placeholder, "ui", self.size, (150, 140, 180))
            surf.blit(img, img.get_rect(midleft=(inner.x, self.rect.centery)))
            caret_x = inner.x
        else:
            font = fonts.font("ui", self.size)
            caret_px = font.size(self.text[: self.cursor])[0]
            scroll = max(0, caret_px - inner.width + self.ui.s(4))
            img = fonts.render(self.text, "ui", self.size, ink)
            prev = surf.get_clip()
            surf.set_clip(inner.clip(prev) if prev else inner)
            surf.blit(img, img.get_rect(midleft=(inner.x - scroll, self.rect.centery)))
            surf.set_clip(prev)
            caret_x = inner.x + caret_px - scroll
        if self.focused and (self.blink % 1.0) < 0.55:
            h = self.ui.s(self.size * 1.1)
            pygame.draw.rect(surf, ink, (caret_x, self.rect.centery - h // 2, max(2, self.ui.s(2.5)), h))


class Toasts:
    """Short messages that pop up at the bottom of the screen."""

    def __init__(self, ui: UI):
        self.ui = ui
        self.items: list[list] = []

    def show(self, text: str, color=None, seconds: float = 3.0) -> None:
        self.items.append([text, color or self.ui.theme.c("panel_light"), seconds, 0.0])
        self.items = self.items[-3:]

    def update(self, dt: float) -> None:
        for it in self.items:
            it[3] += dt
        self.items = [it for it in self.items if it[3] < it[2]]

    def draw(self, surf) -> None:
        w, h = surf.get_size()
        y = h - self.ui.s(40)
        for text, color, life, age in reversed(self.items):
            img = self.ui.fonts.render(text, "bold", 22, (255, 255, 255), outline=3, max_width=1100)
            pad = self.ui.s(18)
            box = V.rounded_rect((img.get_width() + pad * 2, img.get_height() + self.ui.s(14)), self.ui.s(18),
                                 color, self.ui.theme.c("ink"), outline=max(2, self.ui.s(3)))
            t_in = ease_out_back(min(1.0, age * 5))
            t_out = min(1.0, max(0.0, (life - age) * 4))
            alpha = int(255 * min(t_in, 1.0) * t_out)
            box.blit(img, (pad, self.ui.s(7)))
            box.set_alpha(alpha)
            rect = box.get_rect(midbottom=(w // 2, y + (1 - t_in) * self.ui.s(30)))
            surf.blit(box, rect)
            y = rect.top - self.ui.s(8)


def draw_bar(surf, rect, fraction: float, color, ui: UI, back=None) -> None:
    rect = pygame.Rect(rect)
    ink = ui.theme.c("ink")
    r = rect.height // 2
    pygame.draw.rect(surf, ink, rect.inflate(ui.s(6), ui.s(6)), border_radius=r + ui.s(3))
    pygame.draw.rect(surf, back or ui.theme.c("panel"), rect, border_radius=r)
    fill = rect.copy()
    fill.width = int(rect.width * max(0.0, min(1.0, fraction)))
    if fill.width > 0:
        pygame.draw.rect(surf, color, fill, border_radius=r)
        hi = fill.inflate(-ui.s(6), -rect.height * 0.55)
        hi.top = fill.top + ui.s(2)
        if hi.width > 4:
            pygame.draw.rect(surf, lighten(color, 0.45), hi, border_radius=hi.height // 2)


def panel(size, ui: UI, color=None, alpha: int = 215, radius: float = 26) -> pygame.Surface:
    color = color or ui.theme.c("panel")
    return V.rounded_rect(size, ui.s(radius), (*color, alpha), ui.theme.c("ink"), outline=max(2, ui.s(3.5)),
                          shadow=ui.s(8), shadow_color=(*darken(ui.theme.c("ink"), 0.4), 120))
