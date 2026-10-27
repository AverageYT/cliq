"""Colours and lane styling, loaded from ``data/theme.json``."""

from __future__ import annotations

from functools import lru_cache

from .. import paths
from ..util import hex_to_rgb, load_json

DEFAULT_DIRECTIONS = {4: ["left", "down", "up", "right"]}


class Theme:
    def __init__(self, data: dict | None = None):
        data = data if data is not None else (load_json(paths.DATA_DIR / "theme.json", {}) or {})
        self.fonts: dict[str, str] = dict(data.get("fonts", {}))
        self.colors = {k: hex_to_rgb(v) for k, v in data.get("colors", {}).items()}
        self.lane_colors = {k: hex_to_rgb(v) for k, v in data.get("lane_colors", {}).items()}
        self.directions = {int(k): list(v) for k, v in data.get("lane_directions", {}).items()}
        self.shape_colors = [hex_to_rgb(c) for c in data.get("shapes", [])] or [(255, 255, 255)]

    def c(self, name: str, fallback=(255, 255, 255)) -> tuple[int, int, int]:
        return self.colors.get(name, fallback)

    def lane_direction(self, lanes: int, lane: int) -> str:
        dirs = self.directions.get(lanes) or DEFAULT_DIRECTIONS.get(lanes)
        if not dirs or len(dirs) != lanes:
            cycle = ["left", "down", "up", "right"]
            dirs = [cycle[i % 4] for i in range(lanes)]
            if lanes % 2:
                dirs[lanes // 2] = "center"
        return dirs[lane]

    def lane_color(self, lanes: int, lane: int) -> tuple[int, int, int]:
        return self.lane_colors.get(self.lane_direction(lanes, lane), (255, 255, 255))


@lru_cache(maxsize=1)
def get_theme() -> Theme:
    return Theme()
