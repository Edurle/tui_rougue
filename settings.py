"""显示设置：画面大小（字号+格数）与信息板宽度（列数）两档独立调节 + 界面语言。

受 tcod 单窗口统一字格约束，"画面"档同时决定字号与总格数（窗口像素
基本不变，格数与字号成反比）；"信息板"档决定信息板占的列数（地图相应
让列，列数随小字号档位加宽以容纳更多内容）。语言 None = 跟随系统检测。
全部持久化到 settings.json。
"""

from __future__ import annotations

import json
from pathlib import Path

SETTINGS_FILE = Path("settings.json")

WINDOW_PIXELS = (1280, 768)
SIZE_ORDER = ("large", "medium", "small")

# 画面档：字格边长 px（窗口像素 1280x768 下的等比档位；统一小字多格）
MAP_PRESETS = {"large": 20, "medium": 16, "small": 12}
# 信息板档：占列数（含分隔线；小字号下列数加宽，物理宽度大体相当）
SIDEBAR_PRESETS = {"large": 22, "medium": 28, "small": 38}

MIN_MAP_COLS = 16


def sidebar_layout(total_rows: int) -> dict:
    """信息板四段行预算：紧凑档（≤26 行）技能两列压缩，保日志 ≥5 行。

    段落顺序：属性 → 技能页眉 → 技能区 → 装备区 → 分隔线 → 日志。
    """
    if total_rows <= 26:
        return {
            "compact": True,
            "mp_row": 3,
            "mp_bar": False,  # 真气数值行内嵌短条
            "level_row": 4,
            "floor_row": 5,
            "hint_row": 7,  # 提示两行：6（旧）7（新）
            "skill_header": 8,
            "skill_first": 9,
            "skill_count": 4,
            "skill_two_cols": True,
            "equip_first": 13,
            "divider": 18,
        }
    return {
        "compact": False,
        "mp_row": 3,
        "mp_bar": True,
        "level_row": 5,
        "floor_row": 6,
        "hint_row": 7,
        "skill_header": 8,
        "skill_first": 9,
        "skill_count": 8,
        "skill_two_cols": False,
        "equip_first": 17,
        "divider": 22,
    }


class Settings:
    def __init__(self, map_size: str = "large", sidebar_size: str = "large", lang: str | None = None) -> None:
        self.map_size = map_size
        self.sidebar_size = sidebar_size
        self.lang = lang  # None = 跟随系统语言检测

    # ---- 档位切换 ----

    def cycle_map(self, delta: int = 1) -> None:
        self.map_size = SIZE_ORDER[(SIZE_ORDER.index(self.map_size) + delta) % len(SIZE_ORDER)]

    def cycle_sidebar(self, delta: int = 1) -> None:
        self.sidebar_size = SIZE_ORDER[(SIZE_ORDER.index(self.sidebar_size) + delta) % len(SIZE_ORDER)]

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
        return sidebar_layout(self.total_rows)["divider"]

    @property
    def log_height(self) -> int:
        return self.total_rows - self.divider_row - 1

    # ---- 持久化 ----

    def save(self) -> None:
        SETTINGS_FILE.write_text(
            json.dumps(
                {
                    "map_size": self.map_size,
                    "sidebar_size": self.sidebar_size,
                    "lang": self.lang,
                },
                ensure_ascii=False,
                indent=2,
            ),
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
        lang = data.get("lang")
        return cls(
            map_size=map_size if map_size in SIZE_ORDER else "large",
            sidebar_size=sidebar_size if sidebar_size in SIZE_ORDER else "large",
            lang=lang,
        )
