"""秘境系统测试：入口撒布、进出流转、层间移动、BOSS 封印、主题配色。"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from actions import TakeStairsAction  # noqa: E402
from content_loader import load_content  # noqa: E402
from engine import Engine  # noqa: E402
from settings import Settings  # noqa: E402


def make_engine() -> Engine:
    return Engine(load_content(), Settings())


def find_gate(engine, realm_id):
    for entity in engine.world.entities:
        if "realm_gate" in entity.tags and realm_id in entity.tags:
            return entity
    return None


def test_world_has_gates_for_all_realms():
    engine = make_engine()
    content = engine.content
    for realm_id in content.realms:
        gate = find_gate(engine, realm_id)
        assert gate is not None, f"{realm_id} 没有世界入口"
        assert engine.world.tiles["walkable"][gate.x, gate.y], "入口应在可走格上"


def test_enter_realm_and_return():
    engine = make_engine()
    gate = find_gate(engine, "yaoshan_gudong")
    engine.player.x, engine.player.y = gate.x, gate.y

    TakeStairsAction(engine.player, "down").perform(engine)  # > 踏入
    assert engine.gamemap is not engine.world
    assert engine.gamemap.map_type == "realm"
    assert engine.gamemap.realm_id == "yaoshan_gudong"
    assert engine.gamemap.realm_depth == 1
    assert engine.current_realm == "yaoshan_gudong"

    # 第 1 层上行 < = 回世界，落在入口坐标
    engine.player.x, engine.player.y = engine.gamemap.upstairs_xy
    TakeStairsAction(engine.player, "up").perform(engine)
    assert engine.gamemap is engine.world
    assert engine.current_realm is None
    assert (engine.player.x, engine.player.y) == (gate.x, gate.y)


def test_realm_floor_navigation_and_cache():
    engine = make_engine()
    gate = find_gate(engine, "yaoshan_gudong")  # depth=2
    engine.player.x, engine.player.y = gate.x, gate.y
    TakeStairsAction(engine.player, "down").perform(engine)
    floor1 = engine.gamemap

    engine.player.x, engine.player.y = floor1.downstairs_xy
    TakeStairsAction(engine.player, "down").perform(engine)  # 深入第 2 层（BOSS 层）
    assert engine.gamemap.realm_depth == 2
    assert engine.gamemap.downstairs_xy == (-1, -1)  # BOSS 层无下行
    assert any("boss" in getattr(a, "tags", []) for a in engine.gamemap.actors), "BOSS 层应有 BOSS"

    # 回第 1 层：缓存复用（同一地图对象）
    engine.player.x, engine.player.y = engine.gamemap.upstairs_xy
    TakeStairsAction(engine.player, "up").perform(engine)
    assert engine.gamemap is engine.realms["yaoshan_gudong"][1]
    assert engine.gamemap.realm_depth == 1


def test_boss_slain_seals_realm():
    import exceptions

    engine = make_engine()
    gate = find_gate(engine, "yaoshan_gudong")
    engine.player.x, engine.player.y = gate.x, gate.y
    TakeStairsAction(engine.player, "down").perform(engine)
    engine.player.x, engine.player.y = engine.gamemap.downstairs_xy
    TakeStairsAction(engine.player, "down").perform(engine)  # BOSS 层

    boss = next(a for a in engine.gamemap.actors if "boss" in a.tags)
    engine.player.fighter.power = 999  # 一击必杀
    engine.player.fighter.attack(boss.fighter)
    assert not boss.is_alive
    assert "yaoshan_gudong" in engine.realm_cleared
    assert "sealed" in find_gate(engine, "yaoshan_gudong").tags

    # 出秘境后再也进不去
    engine.exit_realm()
    engine.player.x, engine.player.y = gate.x, gate.y
    try:
        TakeStairsAction(engine.player, "down").perform(engine)
    except exceptions.Impossible as exc:
        assert "封印" in str(exc)
    else:
        raise AssertionError("封印后的秘境不应能进入")


def test_realm_boss_floor_has_reward_drop():
    engine = make_engine()
    gate = find_gate(engine, "yaoshan_gudong")
    engine.player.x, engine.player.y = gate.x, gate.y
    TakeStairsAction(engine.player, "down").perform(engine)
    engine.player.x, engine.player.y = engine.gamemap.downstairs_xy
    TakeStairsAction(engine.player, "down").perform(engine)

    boss = next(a for a in engine.gamemap.actors if "boss" in a.tags)
    items_before = {i.name for i in engine.gamemap.items}
    engine.player.fighter.power = 999
    engine.player.fighter.attack(boss.fighter)
    items_after = {i.name for i in engine.gamemap.items}
    assert items_after - items_before, "BOSS 陨落应保底掉落战利品"


def test_realm_theme_palette_differs():
    import tile_types
    import render

    content = load_content()
    base = render._terrain_luts(content.theme, None)
    for key in content.theme["realm_themes"]:
        luts = render._terrain_luts(content.theme, key)
        assert not (luts[1][tile_types.T_FLOOR] == base[1][tile_types.T_FLOOR]).all(), (
            f"秘境主题 {key} 的地面配色应区别于基础主题"
        )


def test_not_on_gate_gives_hint():
    import exceptions

    engine = make_engine()
    engine.player.x += 1  # 随便站一脚（可能不在门上）
    if engine.world.get_realm_gate_at(engine.player.x, engine.player.y) is None:
        try:
            TakeStairsAction(engine.player, "down").perform(engine)
        except exceptions.Impossible:
            pass
        else:
            raise AssertionError("不在秘境之门上按 > 应提示")
