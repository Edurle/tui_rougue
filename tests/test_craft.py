"""天工开物测试：材料堆叠/采集/掉落/配方执行/炼制界面。"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from actions import PickupAction  # noqa: E402
from content_loader import load_content  # noqa: E402
from engine import Engine  # noqa: E402
from settings import Settings  # noqa: E402


def make_engine() -> Engine:
    return Engine(load_content(), Settings())


def give_material(engine, material_id, count):
    """直接给行囊塞材料（测试用）。"""
    item = engine.content.build_item(material_id, engine.gamemap, 0, 0)
    engine.gamemap.entities.discard(item)
    item.gamemap = None
    item.stack = count
    engine.player.inventory.add(item)
    return item


def find_node(engine, node_id):
    for entity in engine.world.entities:
        if "resource_node" in entity.tags and node_id in entity.tags:
            return entity
    return None


# ---- 材料体系 ----


def test_materials_stack_in_inventory():
    engine = make_engine()
    give_material(engine, "mat_spirit_herb", 3)
    give_material(engine, "mat_spirit_herb", 4)
    mats = [i for i in engine.player.inventory.items if i.is_material]
    assert len(mats) == 1 and mats[0].stack == 7, "同类材料应堆叠合并"


def test_gather_node_yields_material():
    engine = make_engine()
    node = find_node(engine, "herb")
    engine.player.x, engine.player.y = node.x, node.y
    PickupAction(engine.player).perform(engine)
    mats = [i for i in engine.player.inventory.items if i.is_material]
    assert mats and mats[0].stack >= 1, "采集后材料应入囊"
    assert engine.world.get_resource_node_at(node.x, node.y) is None, "资源点应消失"
    joined = "".join(m.plain_text for m in engine.message_log.messages)
    assert "采下" in joined


def test_monster_drops_material_by_tags():
    import tile_types

    engine = make_engine()
    engine.content.craft_drops["beast"]["chance"] = 1.0  # 必掉
    gm = engine.gamemap
    px, py = engine.player.x, engine.player.y
    gm.terrain[px + 1, py] = tile_types.T_PLAIN
    gm.refresh_tile_flags()
    beast = engine.content.build_monster("xingxing", gm, px + 1, py)
    engine.player.fighter.power = 99
    engine.player.fighter.attack(beast.fighter)
    mats = [i for i in gm.items if i.is_material]
    assert any("兽骨" in m.name for m in mats), "beast 应掉兽骨"


def test_world_has_nodes_and_ground_materials():
    engine = make_engine()
    nodes = [e for e in engine.world.entities if "resource_node" in e.tags]
    assert sum(1 for e in nodes if "herb" in e.tags) >= 15, "世界灵草丛配额"
    assert sum(1 for e in nodes if "ore" in e.tags) >= 10, "世界矿脉配额"
    ground = [e for e in engine.world.items if e.is_material]
    assert len(ground) >= 5, "地面应有散落材料"


# ---- 配方执行 ----


def test_craft_rejuvenation_pill():
    import craft

    engine = make_engine()
    give_material(engine, "mat_spirit_herb", 3)
    give_material(engine, "mat_cinnabar", 1)
    recipe = next(r for r in engine.content.recipes if r["id"] == "alchemy_rejuvenation")
    craft.execute_recipe(engine, recipe)
    assert any("回春丹" in i.name for i in engine.player.inventory.items)
    remaining = engine.player.inventory.count_material("mat_spirit_herb", engine.content)
    assert remaining == 0, "材料应被扣减"
    joined = "".join(m.plain_text for m in engine.message_log.messages)
    assert "炉火纯青" in joined


def test_craft_insufficient_materials_rejected():
    import craft
    import exceptions

    engine = make_engine()
    give_material(engine, "mat_spirit_herb", 1)  # 缺 2
    recipe = next(r for r in engine.content.recipes if r["id"] == "alchemy_rejuvenation")
    try:
        craft.execute_recipe(engine, recipe)
    except exceptions.Impossible:
        pass
    else:
        raise AssertionError("材料不足应被拒绝")
    assert engine.player.inventory.count_material("mat_spirit_herb", engine.content) == 1, "不应扣料"


def test_all_recipes_kind_coverage():
    import craft

    content = load_content()
    kinds = {r["kind"] for r in content.recipes}
    assert kinds == {"alchemy", "forge", "talisman"}, f"三系应齐备：{kinds}"
    for kind in craft.CRAFT_KINDS:
        assert craft.recipes_of_kind(content, kind), f"{kind} 应有配方"


# ---- C 键界面 ----


def test_craft_key_pipeline_and_render():
    import tcod
    from tcod.event import KeySym

    import input_handlers as ih
    import render

    engine = make_engine()
    handler = ih.MainGameEventHandler(engine)
    event = tcod.event.KeyDown(sym=KeySym.C, scancode=0, mod=tcod.event.Modifier.NONE, repeat=False)
    action = handler.dispatch(event)
    assert isinstance(action, ih.OpenCraftAction)

    craft_handler = ih.CraftEventHandler(engine)
    console = tcod.console.Console(engine.settings.total_cols, engine.settings.total_rows, order="F")
    craft_handler.on_render(console)
    DIV = engine.settings.divider_col
    body = "".join(
        "".join(chr(int(c)) if c not in (0, 32) else " " for c in console.rgb[:DIV, y]["ch"])
        for y in range(engine.settings.total_rows)
    )
    assert "天工开物" in body and "炼丹" in body

    # Tab 切到炼器页
    craft_handler.dispatch(tcod.event.KeyDown(sym=KeySym.TAB, scancode=0, mod=tcod.event.Modifier.NONE, repeat=False))
    assert craft_handler.page == 1
    craft_handler.on_render(console)
    # Esc 关闭
    action = craft_handler.dispatch(
        tcod.event.KeyDown(sym=KeySym.ESCAPE, scancode=0, mod=tcod.event.Modifier.NONE, repeat=False)
    )
    assert isinstance(action, ih.CloseMenuAction)


def test_craft_via_ui_produces_item():
    import tcod
    from tcod.event import KeySym

    import input_handlers as ih

    engine = make_engine()
    give_material(engine, "mat_spirit_herb", 2)
    give_material(engine, "mat_cinnabar", 1)
    craft_handler = ih.CraftEventHandler(engine)  # 默认炼丹页，解毒丹是第 3 个
    craft_handler.cursor = 2
    craft_handler.dispatch(
        tcod.event.KeyDown(sym=KeySym.RETURN, scancode=0, mod=tcod.event.Modifier.NONE, repeat=False)
    )
    assert any("解毒丹" in i.name for i in engine.player.inventory.items), "界面回车应完成炼制"


# ---- 新消耗品效果 ----


def test_detox_pill_cleanses_poison():
    from actions import ItemAction

    engine = make_engine()
    give_material(engine, "mat_spirit_herb", 2)
    give_material(engine, "mat_cinnabar", 1)
    import craft

    recipe = next(r for r in engine.content.recipes if r["id"] == "alchemy_detox")
    craft.execute_recipe(engine, recipe)
    pill = next(i for i in engine.player.inventory.items if "解毒丹" in i.name)

    engine.player.fighter.apply_poison(3, 5)
    assert engine.player.fighter.poisoned
    ItemAction(engine.player, pill).perform(engine)
    assert not engine.player.fighter.poisoned, "解毒丹应清除蛊毒"


def test_might_pill_buffs_power():
    from actions import ItemAction

    engine = make_engine()
    give_material(engine, "mat_beast_bone", 2)
    give_material(engine, "mat_cinnabar", 1)
    import craft

    recipe = next(r for r in engine.content.recipes if r["id"] == "alchemy_might")
    craft.execute_recipe(engine, recipe)
    pill = next(i for i in engine.player.inventory.items if "蛮力丹" in i.name)
    base = engine.player.fighter.base_power
    ItemAction(engine.player, pill).perform(engine)
    assert engine.player.fighter.buff_amount("power") == 4, "蛮力丹应给攻 buff"


def test_immobilize_talisman_stuns_visible_enemies():
    from actions import ItemAction

    engine = make_engine()
    give_material(engine, "mat_talisman_paper", 1)
    give_material(engine, "mat_serpent_scale", 1)
    give_material(engine, "mat_cinnabar", 1)
    import craft

    recipe = next(r for r in engine.content.recipes if r["id"] == "talisman_immobilize")
    craft.execute_recipe(engine, recipe)
    talisman = next(i for i in engine.player.inventory.items if "定身符" in i.name)

    import tile_types

    gm = engine.gamemap
    px, py = engine.player.x, engine.player.y
    for cx in range(px, px + 4):
        gm.terrain[cx, py] = tile_types.T_PLAIN
    gm.refresh_tile_flags()
    enemy = engine.content.build_monster("xingxing", gm, px + 2, py)
    gm.update_fov(px, py)
    ItemAction(engine.player, talisman).perform(engine)
    assert enemy.fighter.stun_turns > 0, "定身符应眩晕视野内敌人"


# ---- 效果信息展示 ----


def test_item_effect_summary_categories():
    """物品效果摘要：治疗/雷击/增益丹/定身符/装备加成。"""
    import render

    engine = make_engine()
    strings = engine.content.strings

    def build(iid):
        item = engine.content.build_item(iid, engine.gamemap, 0, 0)
        engine.gamemap.entities.discard(item)
        item.gamemap = None
        return item

    assert render.item_effect_summary(strings, build("lingzhi")) == "疗12"
    assert render.item_effect_summary(strings, build("wulei_fu")) == "伤14"
    assert render.item_effect_summary(strings, build("pill_might")) == "攻+4"
    assert render.item_effect_summary(strings, build("talisman_immobilize")) == "定身3"
    assert "攻+2" in render.item_effect_summary(strings, build("w_taomu"))


def test_inventory_renders_effect_summary():
    import input_handlers as ih
    import tcod

    engine = make_engine()
    item = engine.content.build_item("lingzhi", engine.gamemap, 0, 0)
    engine.gamemap.entities.discard(item)
    item.gamemap = None
    engine.player.inventory.add(item)
    handler = ih.InventoryEventHandler(engine)
    console = tcod.console.Console(engine.settings.total_cols, engine.settings.total_rows, order="F")
    handler.on_render(console)
    body = "".join(
        "".join(chr(c) if c not in (0, 32) else " " for c in console.rgb[:, y]["ch"])
        for y in range(engine.settings.total_rows)
    )
    assert "疗12" in body, "行囊灵芝行应显示效果摘要"


def test_sidebar_skill_row_shows_effect():
    import input_handlers as ih
    import tcod

    engine = make_engine()
    engine.player.skill_points = 3
    engine.learn_skill("s_leifa_1")
    console = tcod.console.Console(engine.settings.total_cols, engine.settings.total_rows, order="F")
    ih.MainGameEventHandler(engine).on_render(console)
    DIV = engine.settings.divider_col
    side = "".join(
        "".join(chr(c) if c not in (0, 32) else " " for c in console.rgb[DIV:, y]["ch"])
        for y in range(engine.settings.total_rows)
    )
    assert "掌心雷" in side and "伤" in side, "已学技能行应附效果摘要"


def test_learn_menu_shows_selected_detail():
    import input_handlers as ih
    import tcod

    engine = make_engine()
    handler = ih.SkillLearnEventHandler(engine)
    console = tcod.console.Console(engine.settings.total_cols, engine.settings.total_rows, order="F")
    handler.on_render(console)
    body = "".join(
        "".join(chr(c) if c not in (0, 32) else " " for c in console.rgb[:, y]["ch"])
        for y in range(engine.settings.total_rows)
    )
    assert "每重 +20%" in body
    assert "伤" in body or "疗" in body or "掠" in body, "选中项应显示效果数值"
