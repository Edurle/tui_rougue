"""显示设置：画面大小（字号+格数）与信息板宽度（列数）两档独立调节。

受 tcod 单窗口统一字格约束，"画面"档同时决定字号与总格数（窗口像素
基本不变，格数与字号成反比）；"信息板"档决定信息板占的列数（地图相应
让列）。当前默认 large/large（最大）。选择持久化到 settings.json。
"""

from __future__ import annotations

import json
from pathlib import Path

SETTINGS_FILE = Path("settings.json")

WINDOW_PIXELS = (1920, 1056)
SIZE_ORDER = ("large", "medium", "small")

# 画面档：字格边长 px
MAP_PRESETS = {"large": 48, "medium": 36, "small": 28}
# 信息板档：占列数（含分隔线）
SIDEBAR_PRESETS = {"large": 14, "medium": 18, "small": 22}

MIN_MAP_COLS = 16


class Settings:
    def __init__(self, map_size: str = "large", sidebar_size: str = "large") -> None:
        self.map_size = map_size
        self.sidebar_size = sidebar_size

    # ---- 档位切换 ----

    def cycle_map(self) -> None:
        self.map_size = SIZE_ORDER[(SIZE_ORDER.index(self.map_size) + 1) % len(SIZE_ORDER)]

    def cycle_sidebar(self) -> None:
        self.sidebar_size = SIZE_ORDER[(SIZE_ORDER.index(self.sidebar_size) + 1) % len(SIZE_ORDER)]

    # ---- 派生几何 ----

    @property
    def tile_size(self) -> int:
        return MAP_PRESETS[self.map_size]

    @property
    def total_cols(self) -> int:
        return WINDOW_PIXELS[0] // self.tile_size

    @property
    def total_rows(self) -> int:
        return WINDOW_PIXELS[1] // self.tile_size

    @property
    def divider_col(self) -> int:
        side = SIDEBAR_PRESETS[self.sidebar_size]
        return max(MIN_MAP_COLS, self.total_cols - side)

    @property
    def map_cols(self) -> int:
        return self.divider_col

    @property
    def map_rows(self) -> int:
        return self.total_rows

    @property
    def content_x(self) -> int:
        return self.divider_col + 1

    @property
    def content_w(self) -> int:
        return self.total_cols - self.divider_col - 1

    @property
    def divider_row(self) -> int:
        return 12 if self.total_rows > 26 else 11

    @property
    def log_height(self) -> int:
        return self.total_rows - self.divider_row - 1

    # ---- 持久化 ----

    def save(self) -> None:
        SETTINGS_FILE.write_text(
            json.dumps({"map_size": self.map_size, "sidebar_size": self.sidebar_size}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls) -> "Settings":
        data = {}
        if SETTINGS_FILE.exists():
            try:
                data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
        map_size = data.get("map_size", "large")
        sidebar_size = data.get("sidebar_size", "large")
        return cls(
            map_size=map_size if map_size in SIZE_ORDER else "large",
            sidebar_size=sidebar_size if sidebar_size in SIZE_ORDER else "large",
        )
