"""画面基础测试：邻接墙、光照、图块、字体回退。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tile_types  # noqa: E402
from content_loader import load_content  # noqa: E402
from engine import Engine
from settings import Settings  # noqa: E402
from game_map import GameMap  # noqa: E402
from tileset_art import ART_REGISTRY, art_codepoint, inject_art_tiles  # noqa: E402
from font_fallback import collect_text, content_characters  # noqa: E402


def _small_map(engine) -> GameMap:
    gm = GameMap(engine, 10, 10)
    gm.tiles[...] = tile_types.WALL
    gm.tiles[3:7, 3:7] = tile_types.FLOOR
    gm.rebuild_wall_glyphs()
    return gm


def test_wall_autotiling_glyphs():
    content = load_content()
    engine = Engine(content, Settings())
    gm = _small_map(engine)

    # 房间上边墙格 (3,2)：上/左/右为墙、下为地板 → U+L+R = ┴
    assert gm.wall_glyphs[3, 2] == ord("┴")
    # 房间下边墙格 (3,7)：下/左/右为墙、上为地板 → D+L+R = ┬
    assert gm.wall_glyphs[3, 7] == ord("┬")
    # 房间左边墙格 (2,4)：上/下/左为墙、右为地板 → U+D+L = ┤
    assert gm.wall_glyphs[2, 4] == ord("┤")
    # 房间右边墙格 (7,4)：上/下/右为墙、左为地板 → U+D+R = ├
    assert gm.wall_glyphs[7, 4] == ord("├")
    # 外圈空旷墙四邻皆墙 → ┼
    assert gm.wall_glyphs[1, 1] == ord("┼")


def test_wall_glyph_shape_matches_tiles():
    content = load_content()
    engine = Engine(content, Settings())
    gm = _small_map(engine)
    assert gm.wall_glyphs.shape == (10, 10)
    assert gm.wall_glyphs.dtype == np.int32
    for codepoint in gm.wall_glyphs[~gm.tiles["walkable"]].tolist():
        assert chr(codepoint) in "#─│┌┐└┘├┤┬┴┼"


def test_lighting_factors_range():
    content = load_content()
    engine = Engine(content, Settings())
    gm = _small_map(engine)
    factors = gm.lighting_factors(5, 5, inner_radius=3, edge_falloff=0.45)
    assert factors.shape == (10, 10)
    assert 0.54 < factors.min() and factors.max() <= 1.0 + 1e-6
    assert factors[5, 5] == 1.0
    far = factors[0, 0]
    assert far < factors[5, 4]


def test_art_registry_shapes():
    for name, gen in ART_REGISTRY.items():
        mask = gen()
        assert mask.shape == (12, 12), f"{name} 基准设计应为 12x12"
        assert mask.any(), f"{name} 形状为空"


def test_art_codepoints_stable_and_distinct():
    codes = [art_codepoint(name) for name in ART_REGISTRY]
    assert len(set(codes)) == len(codes)
    assert all(c >= 0xE000 for c in codes)


def test_art_injection_mock():
    class FakeTileset(dict):
        def __setitem__(self, cp, tile):
            assert tile.shape == (24, 24, 4)
            assert tile.dtype == np.uint8
            super().__setitem__(cp, tile)

    fake = FakeTileset()
    inject_art_tiles(fake, tile_size=24)
    assert len(fake) == len(ART_REGISTRY)


def test_content_characters_and_collect_text():
    content = load_content()
    chars = content_characters(content)
    assert "狌" in chars
    assert "X" in chars  # en_US 实体名
    assert " " not in chars
    assert list(collect_text({"a": {"b": ["cd", "e"]}})) == list("cde")


def test_render_all_headless():
    import tcod

    import render

    content = load_content()
    engine = Engine(content, Settings())
    console = tcod.console.Console(40, 22, order="F")
    render.render_all(console, engine)
    ch = console.rgb[:26, :22]["ch"]
    assert (ch != 32).any()  # 地图区有内容
    side = console.rgb[26:, :]["ch"]
    assert (side != 32).any()  # 信息板有内容


def test_entity_art_field_wired():
    content = load_content()
    engine = Engine(content, Settings())
    gm = engine.gamemap
    for item in gm.items:
        assert item.art in (None, *ART_REGISTRY)
