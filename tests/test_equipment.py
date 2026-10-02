"""装备系统测试：聚合数值、槽互换、行囊交互、词条、掉落与 tier 门槛。"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tcod  # noqa: E402
from tcod.event import KeySym  # noqa: E402

import input_handlers as ih  # noqa: E402
from actions import EquipAction, UnequipAction  # noqa: E402
from content_loader import load_content  # noqa: E402
from engine import Engine  # noqa: E402
from equipment import SLOT_ORDER  # noqa: E402
from inventory import InventoryFull  # noqa: E402
from settings import Settings  # noqa: E402


def make_engine():
    return Engine(load_content(), Settings())


def give_item(engine, item_id):
    """直接塞进行囊（绕过拾取），返回物品。"""
    item = engine.content.build_item(item_id, engine.gamemap, engine.player.x, engine.player.y)
    engine.gamemap.entities.discard(item)
    engine.player.inventory.add(item)
    return item


def dispatch_key(handler, sym):
    event = tcod.event.KeyDown(sym=sym, scancode=0, mod=tcod.event.Modifier.NONE, repeat=False)
    return handler.dispatch(event)


# ---- 聚合数值 ----


def test_equip_bonuses_aggregate():
    engine = make_engine()
    player = engine.player
    base_power = player.fighter.base_power
    sword = give_item(engine, "w_taomu")  # power+2
    EquipAction(player, sword).perform(engine)
    assert player.fighter.power == base_power + 2
    assert player.equipment.slots["weapon"] is sword
    assert sword not in player.inventory.items

    helm = give_item(engine, "m_zhuli")  # defense+1
    EquipAction(player, helm).perform(engine)
    assert player.fighter.defense == player.fighter.base_defense + 1


def test_unequip_restores_and_clamps():
    engine = make_engine()
    player = engine.player
    shell = give_item(engine, "a_xuangui")  # def+2 hp+6
    EquipAction(player, shell).perform(engine)
    assert player.fighter.max_hp == player.fighter.base_max_hp + 6
    player.fighter.heal(99)  # 装备上限内补满
    assert player.fighter.hp == player.fighter.max_hp
    UnequipAction(player, "armor").perform(engine)
    assert player.fighter.max_hp == player.fighter.base_max_hp
    assert player.fighter.hp == player.fighter.base_max_hp  # clamp 生效
    assert shell in player.inventory.items


def test_slot_swap_returns_old_item():
    engine = make_engine()
    player = engine.player
    sword1 = give_item(engine, "w_taomu")
    EquipAction(player, sword1).perform(engine)
    sword2 = give_item(engine, "w_qingtong")
    EquipAction(player, sword2).perform(engine)
    assert player.equipment.slots["weapon"] is sword2
    assert sword1 in player.inventory.items  # 旧件回行囊
    assert player.fighter.power == player.fighter.base_power + 3


def test_unequip_when_inventory_full():
    engine = make_engine()
    player = engine.player
    sword = give_item(engine, "w_taomu")
    EquipAction(player, sword).perform(engine)
    for i in range(player.inventory.capacity):
        filler = engine.content.build_item(
            "lingzhi", engine.gamemap, engine.player.x, engine.player.y
        )
        engine.gamemap.entities.discard(filler)
        player.inventory.add(filler)
    from exceptions import Impossible

    with pytest.raises(Impossible):
        UnequipAction(player, "weapon").perform(engine)
    assert player.equipment.slots["weapon"] is sword  # 放不回则原样穿回


# ---- 词条 ----


def test_affix_aggregation():
    engine = make_engine()
    player = engine.player
    assert player.fighter.mp == player.fighter.max_mp
    # 昆吾刀：aoe_damage+2；獬豸冠：aoe_damage+3 → 叠加 5
    EquipAction(player, give_item(engine, "w_kunwu")).perform(engine)
    EquipAction(player, give_item(engine, "m_xiezhi")).perform(engine)
    assert player.equipment.affix("aoe_damage") == 5
    assert player.equipment.affix("thunder_damage") == 0


def test_mp_cost_reduce_affix():
    engine = make_engine()
    player = engine.player
    import skills as sk

    engine.learn_skill("s_leifa_1")  # 掌心雷 mp4
    skill = engine.content.skill_for_slot("leifa", 1)
    assert sk.mp_cost(player, skill) == 4
    EquipAction(player, give_item(engine, "w_taomu")).perform(engine)  # 耗气-1
    assert sk.mp_cost(player, skill) == 3


def test_thunder_damage_affix_boosts_damage():
    engine = make_engine()
    player = engine.player
    import skills as sk

    engine.learn_skill("s_leifa_1")  # 掌心雷（thunder）
    skill = engine.content.skill_for_slot("leifa", 1)
    EquipAction(player, give_item(engine, "p_zhaoyao")).perform(engine)  # 雷伤+3
    # 伤害公式整体舍入：power 6 + 1级×1.5 + 词条 3
    assert sk.compute_damage(player, skill) == int(round(6 + 1 * 1.5 + 3))
    # 对照：无词条时不含加成
    base = int(round(6 + 1 * 1.5))
    assert sk.compute_damage(player, skill) >= base + 2


def test_kill_heal_affix():
    engine = make_engine()
    player = engine.player
    EquipAction(player, give_item(engine, "w_ganjiang")).perform(engine)  # 弑回血2
    player.fighter.hp = player.fighter.max_hp - 5
    hp0 = player.fighter.hp
    monster = engine.content.build_monster(
        "xingxing", engine.gamemap, player.x + 1, player.y
    )
    player.fighter.power = 50
    player.fighter.attack(monster.fighter)
    assert not monster.is_alive
    assert player.fighter.hp == hp0 + 2


# ---- 行囊交互 ----


def test_inventory_letter_equips():
    engine = make_engine()
    handler = ih.MainGameEventHandler(engine)
    give_item(engine, "w_taomu")
    action = dispatch_key(handler, KeySym.I)
    assert isinstance(action, ih.OpenInventoryAction)
    handler = ih.InventoryEventHandler(engine)
    action = dispatch_key(handler, KeySym.A)  # 首件装备
    assert isinstance(action, EquipAction)
    engine.handle_action(action)
    assert engine.player.equipment.slots["weapon"] is not None


def test_inventory_cursor_e_and_digit_unequip():
    engine = make_engine()
    give_item(engine, "w_taomu")
    handler = ih.InventoryEventHandler(engine)
    action = dispatch_key(handler, KeySym.E)  # 光标 0 在首件装备上
    assert isinstance(action, EquipAction)
    engine.handle_action(action)

    action = dispatch_key(handler, KeySym.N1)  # 1 = 兵槽卸下
    assert isinstance(action, UnequipAction)
    engine.handle_action(action)
    assert engine.player.equipment.slots["weapon"] is None


def test_consumable_letter_still_usable():
    engine = make_engine()
    from actions import ItemAction

    give_item(engine, "huiqisan")  # 回气散
    engine.player.fighter.mp = 0
    handler = ih.InventoryEventHandler(engine)
    action = dispatch_key(handler, KeySym.A)
    assert isinstance(action, ItemAction)
    engine.handle_action(action)
    assert engine.player.fighter.mp == 8


def test_heal_mp_consumable_full_rejected():
    engine = make_engine()
    from exceptions import Impossible

    powder = give_item(engine, "huiqisan")
    with pytest.raises(Impossible):  # 满真气拒用且不消耗
        powder.consumable.activate(None)
    assert powder in engine.player.inventory.items


# ---- 掉落 ----


def test_roll_drop_tier_gate():
    content = load_content()
    import random

    rng = random.Random(42)
    # 第 1 层门槛 tier ≤ 2，干将(t3)/照妖镜(t3)/獬豸冠(t3) 不可出
    for _ in range(60):
        assert content.random_equipment_id(1, rng) not in ("w_ganjiang", "p_zhaoyao", "m_xiezhi")
    # 第 16 层门槛 tier ≤ 6，全池可出
    pool16 = set()
    for _ in range(200):
        pool16.add(content.random_equipment_id(16, rng))
    assert "w_ganjiang" in pool16


def test_monster_death_rolls_drop():
    engine = make_engine()
    player = engine.player
    player.fighter.power = 50
    items_before = len(engine.gamemap.items)
    monster = engine.content.build_monster(
        "xingxing", engine.gamemap, player.x + 1, player.y
    )
    # 用可控 rng：强制 22% 命中
    engine.rng.seed(1)
    dropped = False
    for i in range(30):
        engine.rng = __import__("random").Random(i)
        monster2 = engine.content.build_monster(
            "xingxing", engine.gamemap, player.x + 1, player.y + 1
        )
        before = len(engine.gamemap.items)
        player.fighter.attack(monster2.fighter)
        if not monster2.is_alive and len(engine.gamemap.items) > before:
            dropped = True
            break
    assert dropped, "多次击杀应至少触发一次装备掉落"


def test_equipment_items_render_as_ground_items():
    engine = make_engine()
    player = engine.player
    gear = engine.content.build_item("w_taomu", engine.gamemap, player.x, player.y + 1)
    from actions import PickupAction

    player.x, player.y = player.x, player.y + 1
    PickupAction(player).perform(engine)
    assert gear in player.inventory.items
