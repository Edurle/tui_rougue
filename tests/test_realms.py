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


# ---- 大世界旅行（Shift+方向）----


def test_travel_walks_until_blocked():
    from actions import BumpAction

    engine = make_engine()
    # 把玩家挪到开阔平原并清出一条向东长廊（含廊内投放实体，防旅行提前停）
    import tile_types

    world = engine.world
    px, py = world.spawn_xy
    for x in range(px, px + 30):
        for y in range(py - 1, py + 2):
            world.terrain[x, y] = tile_types.T_PLAIN
    world.refresh_tile_flags()
    for entity in list(world.entities):
        if (
            entity is not engine.player
            and px - 2 <= entity.x < px + 32
            and py - 10 <= entity.y <= py + 10
        ):
            world.entities.discard(entity)
    engine.player.x, engine.player.y = px, py
    engine.update_fov()

    engine.traveling = (1, 0)
    steps = 0
    while engine.traveling is not None and steps < 100:
        engine.travel_step()
        steps += 1
    assert engine.player.x > px + 5, "开阔地上旅行应持续行走"
    assert engine.traveling is None


def test_travel_stops_on_new_threat():
    engine = make_engine()
    world = engine.world
    px, py = world.spawn_xy
    import tile_types

    for x in range(px, px + 20):
        for y in range(py - 1, py + 2):
            world.terrain[x, y] = tile_types.T_PLAIN
    world.refresh_tile_flags()
    engine.player.x, engine.player.y = px, py
    engine.update_fov()

    # 前方 6 格放一只敌兽
    engine.content.build_monster("xingxing", world, px + 6, py)
    world.update_fov(px, py)
    engine.traveling = (1, 0)
    for _ in range(50):
        engine.travel_step()
        if engine.traveling is None:
            break
    assert engine.traveling is None, "威胁进圈应停止旅行"
    assert engine.player.x < px + 6, "不应撞进敌兽怀里"
    joined = "".join(m.plain_text for m in engine.message_log.messages)
    assert "敌踪" in joined or "受阻" in joined or "击中" in joined  # 预警停 / 撞阻停 / 遭袭停


def test_region_first_enter_narrative():
    engine = make_engine()
    assert "zhongshanjing" in engine.visited_regions  # 出生即触发首入叙事
    joined = "".join(m.plain_text for m in engine.message_log.messages)
    assert "中山" in joined


# ---- 山海图卷（M：世界地图）----


def test_world_map_overlay_renders():
    import tcod

    import input_handlers as ih
    import render
    import tile_types

    engine = make_engine()
    # 挪到一座秘境之门旁看一眼（清出视野通道防森林遮挡），让门进入 known_gates
    gate = find_gate(engine, "yaoshan_gudong")
    engine.player.x, engine.player.y = gate.x + 2, gate.y
    for cx in range(gate.x, gate.x + 3):
        engine.gamemap.terrain[cx, gate.y] = tile_types.T_PLAIN
    engine.gamemap.refresh_tile_flags()
    engine.update_fov()
    assert (gate.x, gate.y) in engine.known_gates, "视野内的门应记入图卷"

    handler = ih.WorldMapEventHandler(engine)
    console = tcod.console.Console(engine.settings.total_cols, engine.settings.total_rows, order="F")
    handler.on_render(console)
    DIV = engine.settings.divider_col
    body = "".join(
        "".join(chr(int(c)) if c not in (0, 32) else " " for c in console.rgb[:DIV, y]["ch"])
        for y in range(engine.settings.total_rows)
    )
    assert "山海图卷" in body
    assert "@" in body, "图卷应标记玩家"
    assert "Ω" in body, "图卷应标记已知秘境之门"


def test_world_map_key_pipeline():
    import tcod
    from tcod.event import KeySym

    import input_handlers as ih

    engine = make_engine()
    handler = ih.MainGameEventHandler(engine)
    event = tcod.event.KeyDown(sym=KeySym.M, scancode=0, mod=tcod.event.Modifier.NONE, repeat=False)
    action = handler.dispatch(event)
    assert isinstance(action, ih.OpenWorldMapAction)

    map_handler = ih.WorldMapEventHandler(engine)
    assert isinstance(map_handler.dispatch(event), ih.CloseMenuAction)
