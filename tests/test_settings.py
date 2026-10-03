"""显示设置系统测试：档位派生几何、循环、持久化、重建。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from content_loader import load_content  # noqa: E402
from engine import Engine  # noqa: E402
from settings import MAP_PRESETS, SIDEBAR_PRESETS, Settings  # noqa: E402


def test_large_is_default_and_matches_current_layout():
    s = Settings()
    assert (s.map_size, s.sidebar_size) == ("large", "large")
    assert s.tile_size == 32
    assert s.total_cols == 40 and s.total_rows == 24
    assert s.divider_col == 26
    assert s.content_x == 27 and s.content_w == 13
    assert s.map_cols == 26 and s.map_rows == 24
    assert s.divider_row == 18  # 紧凑档：技能两列 + 装备五槽
    assert s.log_height == 5  # 文档要求：日志 ≥5 行


def test_all_preset_combinations_derive_consistently():
    for map_size in MAP_PRESETS:
        for side_size in SIDEBAR_PRESETS:
            s = Settings(map_size, side_size)
            assert s.tile_size == MAP_PRESETS[map_size]
            assert s.map_cols + 1 + s.content_w == s.total_cols
            assert s.map_cols >= 16, f"{map_size}/{side_size} 地图过窄"
            assert s.content_w >= 13, f"{map_size}/{side_size} 信息板过窄"
            assert s.log_height >= 5, f"{map_size}/{side_size} 日志区不足 5 行"


def test_cycle_round_trip():
    s = Settings()
    s.cycle_map()
    assert s.map_size == "medium"
    s.cycle_map()
    assert s.map_size == "small"
    s.cycle_map()
    assert s.map_size == "large"
    s.cycle_sidebar()
    assert s.sidebar_size == "medium"


def test_save_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s = Settings("medium", "small")
    s.save()
    loaded = Settings.load()
    assert (loaded.map_size, loaded.sidebar_size) == ("medium", "small")


def test_load_invalid_falls_back_to_large(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("settings.json").write_text('{"map_size": "giant"}', encoding="utf-8")
    s = Settings.load()
    assert s.map_size in ("large", "medium", "small"), "未知档位应回退到合法值"
