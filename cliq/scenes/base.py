"""Scene base class. The app keeps a stack of scenes; the top one is live."""

from __future__ import annotations

import pygame


class Scene:
    key_repeat: tuple[int, int] | None = (320, 40)   # None = no key repeat (gameplay)
    text_input = False                                # enable IME/TEXTINPUT events
    menu_music = True                                 # keep the song preview playing

    def __init__(self, app):
        self.app = app
        self.ui = app.ui
        self.fonts = app.fonts
        self.theme = app.theme

    # lifecycle ----------------------------------------------------------
    def enter(self) -> None:
        """Became the active scene (pushed or replaced in)."""

    def leave(self) -> None:
        """Removed from the stack."""

    def pause(self) -> None:
        """Another scene was pushed on top."""

    def resume(self, **result) -> None:
        """The scene above was popped; ``result`` is what it returned."""

    # frame --------------------------------------------------------------
    def handle_event(self, e: pygame.event.Event) -> None:
        pass

    def update(self, dt: float) -> None:
        pass

    def draw(self, surf: pygame.Surface) -> None:
        pass

    # helpers -------------------------------------------------------------
    def s(self, v: float) -> int:
        return self.ui.s(v)

    @property
    def size(self) -> tuple[int, int]:
        return self.app.size

    def title(self, surf, text: str, y: float = 48, size: int = 54, color=(255, 255, 255)) -> None:
        self.fonts.draw(surf, text, (self.size[0] // 2, self.s(y)), "display", size, color, anchor="center",
                        outline=5, shadow=6)
