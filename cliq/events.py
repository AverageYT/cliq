"""A tiny publish/subscribe bus.

Gameplay emits events such as ``note_hit`` or ``combo_break``; modifiers, UI
effects and (later) roguelike items subscribe to them without the gameplay code
needing to know they exist.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable

Handler = Callable[..., Any]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[tuple[int, Handler]]] = defaultdict(list)

    def on(self, name: str, handler: Handler, priority: int = 0) -> Handler:
        """Subscribe ``handler``; higher ``priority`` runs first."""
        handlers = self._handlers[name]
        handlers.append((priority, handler))
        handlers.sort(key=lambda item: -item[0])
        return handler

    def off(self, name: str, handler: Handler) -> None:
        self._handlers[name] = [(p, h) for p, h in self._handlers[name] if h is not handler]

    def emit(self, name: str, **payload: Any) -> None:
        for _, handler in list(self._handlers.get(name, ())):
            handler(**payload)

    def clear(self) -> None:
        self._handlers.clear()
