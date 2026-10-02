"""山川游历区域测试（空间化）：zone 布局、难度轴、名山地标、世界渲染。"""

from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from content_loader import ContentError, load_content  # noqa: E402
from settings import Settings  # noqa: E402
import worldgen  # noqa: E402


class _FakeEngine:
    """worldgen 只用到 engine.content。"""

    def __init__(self, content):
        self.content = content


def _make_world(content, seed=42):
    return worldgen.generate_world(_FakeEngine(content), random.Random(seed))


def test_region_zone_schema_valid():
    content = load_content("zh_CN")
    zones = {r["zone"]: r for r in content.regions}
    assert set(zones) == {"center", "south", "west", "north", "east", "outer"}
    # 难度由中心向外围递增
    assert zones["center"]["base_difficulty"] < zones["south"]["base_difficulty"]
    assert zones["east"]["base_difficulty"] < zones["outer"]["base_difficulty"]


def test_region_grid_geometry():
    """中心=中山经，四象限归四经，外围=大荒经。"""
    content = load_content("zh_CN")
    grid, regions = worldgen.region_grid(160, 100, content)
    by_zone = {r["zone"]: i for i, r in enumerate(regions)}
    assert grid.shape == (160, 100)
    assert int(grid[80, 50]) == by_zone["center"]  # 正中心
    assert int(grid[80, 85]) == by_zone["south"]  # 下=南
    assert int(grid[80, 15]) == by_zone["north"]  # 上=北
    assert int(grid[130, 50]) == by_zone["east"]  # 右=东
    assert int(grid[25, 50]) == by_zone["west"]  # 左=西
    assert int(grid[2, 2]) == by_zone["outer"]  # 角落=大荒
    assert int(grid[155, 50]) == by_zone["outer"]  # 极东缘=大荒


def test_missing_zone_rejected(tmp_path, monkeypatch):
    import json

    from content_loader import CONTENT_DIR, Content
    from paths import resource_path

    monkeypatch.chdir(tmp_path)
    src = resource_path(CONTENT_DIR)
    dest = tmp_path / "content"
    for f in src.rglob("*"):
        if f.is_file():
            rel = f.relative_to(src)
            (dest / rel.parent).mkdir(parents=True, exist_ok=True)
            (dest / rel).write_bytes(f.read_bytes())
    data = json.loads((dest / "regions.json").read_text(encoding="utf-8"))
    data["regions"] = [r for r in data["regions"] if r["zone"] != "west"]  # 抠掉西山经
    (dest / "regions.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    try:
        Content(dest)
    except ContentError as exc:
        assert "west" in str(exc)
    else:
        raise AssertionError("zone 缺失应被校验拒绝")


def test_spawn_table_covers_region_difficulties():
    content = load_content()
    for region in content.regions:
        d = region["base_difficulty"]
        assert content.monster_ids_for_difficulty(d), f"{region['id']} 难度 {d} 无可投放怪物"
        assert content.item_ids_for_difficulty(d), f"{region['id']} 难度 {d} 无可投放物品"


def test_world_landmarks_named_from_regions():
    content = load_content("zh_CN")
    world = _make_world(content)
    assert world.landmarks, "世界应有名山地标"
    names = [lm["name"] for lm in world.landmarks]
    all_mountains = [content._(m) for r in content.regions for m in r["mountains"]]
    for name in names:
        assert name in all_mountains, f"名山 {name} 不在 regions.json 山名表中"
    # 每区至少一座名山
    for region in content.regions:
        assert any(lm["region_id"] == region["id"] for lm in world.landmarks), (
            f"{region['id']} 没有名山地标"
        )


def test_world_terrain_and_spawn():
    import tile_types

    content = load_content("zh_CN")
    world = _make_world(content)
    t = world.terrain
    # 各类地形齐备（用户点名的元素：大地/山川/河流/湖泊/深渊）
    for tid in (tile_types.T_PLAIN, tile_types.T_MOUNTAIN, tile_types.T_RIVER, tile_types.T_WATER, tile_types.T_ABYSS):
        assert (t == tid).any(), f"地形 {tile_types.TERRAIN_DEFS[tid].key} 缺失"
    # 出生点可走且在中山经（中心区）
    sx, sy = world.spawn_xy
    assert world.tiles["walkable"][sx, sy]
    grid, regions = worldgen.region_grid(world.width, world.height, content)
    by_zone = {r["zone"]: i for i, r in enumerate(regions)}
    assert int(grid[sx, sy]) == by_zone["center"]
    # 有游荡异兽与散落物品
    assert len(world.actors) > 5
    assert len(world.items) > 2


def test_world_connectivity_from_spawn():
    content = load_content("zh_CN")
    world = _make_world(content, seed=7)
    reached = worldgen._flood_reachable(world.terrain, world.spawn_xy)
    walkable = world.tiles["walkable"]
    ratio = float(reached[walkable].mean())
    assert ratio > 0.85, f"世界整体可达率过低：{ratio:.3f}"


def test_contextual_hints_render_world():
    import tcod

    import render
    from engine import Engine

    content = load_content("zh_CN")
    engine = Engine(content, Settings())
    player = engine.player

    content.build_item("lingzhi", engine.gamemap, player.x, player.y)  # 脚下放灵芝
    console = tcod.console.Console(40, 24, order="F")
    render.render_all(console, engine)

    texts = []
    for y in (6, 7):
        line = "".join(chr(c) for c in console.rgb[27:40, y]["ch"] if c != 32)
        texts.append(line)
    joined = "".join(texts)
    assert "G" in joined and "拾取" in joined.replace(" ", "")

    engine.player.x += 1  # 离开物品格
    for existing in list(engine.gamemap.items):
        if abs(existing.x - engine.player.x) <= 1 and abs(existing.y - engine.player.y) <= 1:
            engine.gamemap.entities.discard(existing)
    render.render_all(console, engine)
    joined = "".join(
        "".join(chr(c) for c in console.rgb[27:40, y]["ch"] if c != 32) for y in (6, 7)
    )
    assert "拾取" not in joined.replace(" ", "")
    # 大世界没有山径提示
    assert "深入" not in joined.replace(" ", "")
