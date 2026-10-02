"""冒烟测试：内容数据校验 + 地图生成质量。

运行：.venv/Scripts/python.exe -m pytest tests/ -q
"""

from __future__ import annotations

import os
import random
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import procgen  # noqa: E402
from content_loader import Content, ContentError, load_content  # noqa: E402
from engine import Engine
from settings import Settings  # noqa: E402


def make_content() -> Content:
    return load_content()


def make_engine(content: Content) -> Engine:
    return Engine(content, Settings())


# ---- 内容数据 ----


def test_content_loads_and_validates():
    content = make_content()
    assert {"xingxing", "gudiao", "jiuweihu"} <= set(content.monsters)
    assert {"lingzhi", "wulei_fu"} <= set(content.items)
    assert content.strings["welcome"]


def test_spawn_tables_cover_floors():
    content = make_content()
    for floor in range(1, 11):
        assert content.monster_ids_for_floor(floor), f"第 {floor} 层无可投放怪物"
        assert content.item_ids_for_floor(floor), f"第 {floor} 层无可投放物品"


def test_unknown_component_type_fails_fast():
    content = make_content()
    bad = dict(content.items["lingzhi"])
    bad["consumable"] = {"type": "nonexistent"}
    content.items["lingzhi"] = bad
    try:
        content._validate()
    except ContentError as exc:
        assert "nonexistent" in str(exc)
    else:
        raise AssertionError("未知效果类型应当报错")


# ---- 地图生成 ----


def _bfs_reachable(gamemap, start):
    seen = {start}
    queue = deque([start])
    while queue:
        x, y = queue.popleft()
        for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            nx, ny = x + dx, y + dy
            if not gamemap.in_bounds(nx, ny):
                continue
            if not gamemap.tiles["walkable"][nx, ny]:
                continue
            if (nx, ny) in seen:
                continue
            seen.add((nx, ny))
            queue.append((nx, ny))
    return seen


def test_generated_maps_are_connected():
    content = make_content()
    for seed in range(30):
        engine = make_engine(content)
        engine.rng = random.Random(seed)
        gamemap = procgen.generate_dungeon(engine, floor_number=seed + 1, rng=engine.rng, width=26, height=22)
        start = (engine.player.x, engine.player.y)
        reachable = _bfs_reachable(gamemap, start)
        assert gamemap.downstairs_xy in reachable, f"seed={seed} 楼梯不可达"
        for entity in gamemap.entities:
            assert gamemap.tiles["walkable"][entity.x, entity.y], (
                f"seed={seed} 实体 {entity} 放在了墙上"
            )


def test_first_room_is_safe():
    """出生房间不应投放怪物（_populate_room 的 skip_first 机制）。"""
    import game_map as gm_module
    from procgen import Rect, _populate_room

    content = make_content()
    engine = make_engine(content)
    rng = random.Random(3)
    gamemap = gm_module.GameMap(engine, 26, 22)
    room = Rect(5, 5, 8, 8)
    for x, y in room.inner():
        gamemap.tiles[x, y] = __import__("tile_types").FLOOR
    # skip_first=True 模拟首房
    for _ in range(20):  # 反复投放，若机制失效 20 次内必然出现怪物
        _populate_room(gamemap, room, floor_number=1, content=content, rng=rng, skip_first=True)
    assert not gamemap.actors, "首房 skip_first=True 时不应出现任何怪物"


# ---- 回合逻辑 ----


def test_combat_and_death_flow():
    content = make_content()
    engine = make_engine(content)
    player = engine.player
    monster = content.build_monster("xingxing", engine.gamemap, player.x + 1, player.y)
    old_hp = monster.fighter.hp
    for _ in range(100):
        engine.handle_action(type("A", (), {"perform": lambda self, e: player.fighter.attack(monster.fighter)})())
        if not monster.is_alive:
            break
    assert not monster.is_alive
    assert monster.char == "%"
    assert player.level.current_xp > 0
    assert old_hp  # sanity


def test_stairs_descend_increments_floor():
    content = make_content()
    engine = make_engine(content)
    sx, sy = engine.gamemap.downstairs_xy
    engine.player.x, engine.player.y = sx, sy
    from actions import TakeStairsAction

    TakeStairsAction(engine.player).perform(engine)
    assert engine.gamemap.floor_number == 2


def test_pickup_and_use_heal():
    content = make_content()
    engine = make_engine(content)
    player = engine.player
    item = content.build_item("lingzhi", engine.gamemap, player.x, player.y)
    player.fighter.hp = player.fighter.max_hp - 10
    from actions import ItemAction, PickupAction

    PickupAction(player).perform(engine)
    assert item in player.inventory.items
    hp_before = player.fighter.hp
    ItemAction(player, item).perform(engine)
    assert player.fighter.hp > hp_before
    assert item not in player.inventory.items
