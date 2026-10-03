"""技能系统测试：数据校验、双职业合并、技能点账本、十种效果类。

数据铁律（单机约束）以测试固化：每职业 8 技能、链首 ≥2、伤害/召唤/
控制 ≥4、前置 DAG 无环、requires 引用合法、大招 2 点。
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tcod  # noqa: E402
from tcod.event import KeySym  # noqa: E402

import input_handlers as ih  # noqa: E402
from content_loader import (  # noqa: E402
    _OFFENSIVE_EFFECTS,
    load_content,
)
from engine import Engine  # noqa: E402
from exceptions import Impossible, NeedTarget  # noqa: E402
from settings import Settings  # noqa: E402


def make_engine(class_ids=("leifa", "fushi")):
    return Engine(load_content(), Settings(), class_ids)


def give_craft_materials(engine, material_ids, count):
    """测试用：直接塞修习材料（大招/突破消耗）。"""
    for mid in material_ids:
        item = engine.content.build_item(mid, engine.gamemap, 0, 0)
        engine.gamemap.entities.discard(item)
        item.gamemap = None
        item.stack = count
        engine.player.inventory.add(item)

def learn_all(engine, class_id=None):
    """按拓扑顺序学满当前（或指定）职业全部技能（测试用：点数管够）。"""
    player = engine.player
    player.skill_points = 99
    give_craft_materials(engine, ("mat_demon_core", "mat_elite_essence"), 20)
    if class_id is None:
        class_ids = list(player.class_ids)
    else:
        class_ids = [class_id]
    for cid in class_ids:
        for _ in range(10):
            progress = False
            for skill in engine.content.skills_for_class(cid):
                if skill["id"] in player.learned_skills:
                    continue
                try:
                    engine.learn_skill(skill["id"])
                    progress = True
                except Impossible:
                    pass
            if not progress:
                break


def put_monster(engine, dx, dy, monster_id="xingxing"):
    player = engine.player
    return engine.content.build_monster(
        monster_id, engine.gamemap, player.x + dx, player.y + dy
    )


# ---- 数据校验 ----


def test_skill_data_invariants():
    content = load_content()
    assert len(content.classes) == 10
    assert len(content.skills) == 80
    for cid in content.classes:
        skills = content.skills_for_class(cid)
        assert len(skills) == 8, f"{cid} 应有 8 技能"
        assert [s["slot"] for s in skills] == list(range(1, 9))
        heads = [s for s in skills if not s["requires"]]
        assert len(heads) >= 2, f"{cid} 链首应 ≥2"
        offensive = [s for s in skills if s["effect"]["type"] in _OFFENSIVE_EFFECTS]
        assert len(offensive) >= 4, f"{cid} 伤害/召唤/控制应 ≥4"
        for skill in skills:
            for req in skill["requires"]:
                assert req in content.skills
    # 每职业恰有一个 2 点链尾大招
    for cid in content.classes:
        ults = [s for s in content.skills_for_class(cid) if s.get("cost", 1) == 2]
        assert len(ults) == 1, f"{cid} 应恰有一个 2 点大招"
        assert ults[0]["requires"], f"{cid} 大招应有前置"


def test_dag_cycle_rejected():
    from content_loader import Content, ContentError

    cyclic = [
        {"slot": 1, "requires": ["s_x_2"]},
        {"slot": 2, "requires": ["s_x_3"]},
        {"slot": 3, "requires": ["s_x_1"]},
    ]
    with pytest.raises(ContentError):
        Content._assert_skill_dag_acyclic("x", cyclic)


def test_unknown_requires_rejected():
    content = load_content()
    content.skills["s_bad"] = {
        "class": "leifa",
        "slot": 1,
        "name": {"zh_CN": "坏", "en_US": "Bad"},
        "effect": {"type": "mp_restore", "amount": 1},
        "requires": ["nonexistent"],
    }
    with pytest.raises(Exception):
        content._validate_classes_skills()


def test_unknown_effect_type_rejected():
    content = load_content()
    content.skills["s_bad2"] = {
        "class": "leifa",
        "slot": 2,
        "name": {"zh_CN": "坏2", "en_US": "Bad2"},
        "effect": {"type": "no_such_effect"},
        "requires": [],
    }
    with pytest.raises(Exception):
        content._validate_classes_skills()


# ---- 双职业 ----


def test_dual_class_attribute_merge():
    engine = make_engine(("leifa", "fushi"))
    p = engine.player
    # 主全量 + 副气血/真气上限各半（向上取整）：26+13 / 14+8
    assert p.fighter.max_hp == 26 + (26 + 1) // 2
    assert p.fighter.max_mp == 14 + (16 + 1) // 2
    assert p.fighter.power == 4  # leifa 全量
    assert p.fighter.defense == 1
    assert p.fighter.hp == p.fighter.max_hp
    assert p.fighter.mp == p.fighter.max_mp
    assert p.team == "player"
    assert p.class_ids == ("leifa", "fushi")


def test_all_45_combinations_merge_formula():
    engine = make_engine()
    content = engine.content
    count = 0
    for primary in content.classes:
        for secondary in content.classes:
            if primary == secondary:
                continue
            player = content.build_player(engine.gamemap, 0, 0, (primary, secondary))
            pdef, sdef = content.classes[primary], content.classes[secondary]
            assert player.fighter.max_hp == pdef["hp"] + (sdef["hp"] + 1) // 2
            assert player.fighter.max_mp == pdef["mp"] + (sdef["mp"] + 1) // 2
            assert player.fighter.power == pdef["power"]
            assert player.fighter.defense == pdef["defense"]
            assert player.skill_points == 2
            assert player.class_ids == (primary, secondary)
            count += 1
    assert count == 90  # 10×9 有序组合（主副有别）


def test_same_class_rejected():
    content = load_content()
    with pytest.raises(Exception):
        content.build_player(engine_map(content), 0, 0, ("leifa", "leifa"))


def engine_map(content):
    """独立 GameMap 供 build_player 挂靠。"""
    from game_map import GameMap

    class _FakeEngine:
        pass

    return GameMap(_FakeEngine(), 10, 10)  # type: ignore[arg-type]


def test_class_select_handler_two_stage_flow():
    content = load_content()
    settings = Settings()
    handler = ih.ClassSelectEventHandler(content, settings)

    def press(sym):
        return handler.dispatch(
            tcod.event.KeyDown(sym=sym, scancode=0, mod=tcod.event.Modifier.NONE, repeat=False)
        )

    # 第一段：选主职业（光标 0 → 下移 1 → 回车）
    press(KeySym.DOWN)
    press(KeySym.RETURN)
    assert handler.primary == list(content.classes.keys())[1]
    # 第二段 Esc：回到第一段
    press(KeySym.ESCAPE)
    assert handler.primary is None
    press(KeySym.DOWN)
    press(KeySym.RETURN)
    primary = handler.primary
    # 第二段：选副职业（不能与主重复）
    press(KeySym.DOWN)
    press(KeySym.RETURN)
    assert handler.done and handler.chosen is not None
    main, second = handler.chosen
    assert main == primary and second != primary


# ---- 技能点账本 ----


def test_skill_point_ledger():
    engine = make_engine()
    player = engine.player
    assert player.skill_points == 2

    # 前置锁：雷池 requires 掌心雷
    with pytest.raises(Impossible):
        engine.learn_skill("s_leifa_3")
    # 学链首
    engine.learn_skill("s_leifa_1")
    assert player.skill_points == 1
    assert "s_leifa_1" in player.learned_skills
    assert player.skill_levels["s_leifa_1"] == 1
    # 已学技能=升级（每级 1 点，不再拒绝）
    engine.learn_skill("s_leifa_1")
    assert player.skill_levels["s_leifa_1"] == 2
    assert player.skill_points == 0
    # 点不足：升级与新学都拒绝
    with pytest.raises(Impossible):
        engine.learn_skill("s_leifa_2")
    with pytest.raises(Impossible):
        engine.learn_skill("s_leifa_1")
    # 升级 +1 点（+4 真气上限）
    player.level.add_xp(1000)
    assert player.skill_points >= 1
    # 学第二链首
    engine.learn_skill("s_leifa_2")
    assert player.fighter.base_max_mp == player.fighter.max_mp  # 无装备时聚合=基础
    # 大招 2 点：1 点不够
    learn_all(engine, "leifa")
    # 学满后 8 技能全在
    leifa_ids = {s["id"] for s in engine.content.skills_for_class("leifa")}
    assert leifa_ids <= player.learned_skills


def test_ultimate_costs_two_points():
    engine = make_engine()
    player = engine.player
    player.skill_points = 5
    give_craft_materials(engine, ("mat_demon_core",), 1)  # 大招修习另需魔核
    # 万雷引 requires 天雷破，先学链
    for sid in ("s_leifa_1", "s_leifa_3", "s_leifa_7"):
        engine.learn_skill(sid)
    points_before = player.skill_points
    engine.learn_skill("s_leifa_8")
    assert player.skill_points == points_before - 2


# ---- 效果类 ----


def expected_damage(engine, skill):
    import skills as sk

    return sk.compute_damage(engine.player, skill)


def test_effect_damage_nearest():
    engine = make_engine()
    learn_all(engine, "leifa")
    monster = put_monster(engine, 1, 0)
    hp0 = monster.fighter.hp
    engine.player.fighter.mp = engine.player.fighter.max_mp
    engine.execute_skill(1, target=monster)  # 槽 1 = 掌心雷
    damage = expected_damage(engine, skill_of(engine, "leifa", 1))
    assert not monster.is_alive or monster.fighter.hp == hp0 - damage
    assert engine.player.fighter.mp < engine.player.fighter.max_mp


def skill_of(engine, class_id, slot):
    return engine.content.skill_for_slot(class_id, slot)


def test_effect_damage_nearest_needs_target():
    engine = make_engine()
    learn_all(engine, "leifa")
    put_monster(engine, 1, 0)
    with pytest.raises(NeedTarget):
        engine.execute_skill(1)


def test_effect_damage_aoe_self():
    engine = make_engine()
    learn_all(engine, "leifa")
    m1 = put_monster(engine, 1, 0)
    m2 = put_monster(engine, -1, 0)
    far = put_monster(engine, 6, 0)
    hp = {m: m.fighter.hp for m in (m1, m2, far)}
    engine.player.fighter.mp = engine.player.fighter.max_mp
    engine.execute_skill(3)  # 槽 3 = 雷池（半径 1）
    assert m1.fighter.hp < hp[m1]
    assert m2.fighter.hp < hp[m2]
    assert far.fighter.hp == hp[far]  # 半径外不受波及


def test_effect_buff_defense_and_decay():
    engine = make_engine()
    learn_all(engine, "leifa")
    player = engine.player
    base_def = player.fighter.base_defense
    player.fighter.mp = player.fighter.max_mp
    engine.execute_skill(5)  # 槽 5 = 金光咒：防+3 / 12 回合
    assert player.fighter.defense == base_def + 3
    from actions import WaitAction

    for _ in range(12):
        engine.handle_action(WaitAction())
    assert player.fighter.defense == base_def


def test_effect_buff_power():
    engine = make_engine()
    learn_all(engine, "leifa")
    player = engine.player
    player.fighter.mp = player.fighter.max_mp
    engine.execute_skill(4)  # 槽 4 = 引雷符：攻+2 / 12 回合
    assert player.fighter.power == player.fighter.base_power + 2


def test_effect_teleport_step():
    engine = make_engine()
    learn_all(engine, "leifa")
    player = engine.player
    player.fighter.mp = player.fighter.max_mp
    x0, y0 = player.x, player.y
    with pytest.raises(NeedTarget):
        engine.execute_skill(2)  # 槽 2 = 疾风步
    engine.execute_skill(2, target=(1, 0))
    assert (player.x, player.y) != (x0, y0)
    assert abs(player.x - x0) + abs(player.y - y0) <= 3  # 遇阻即停


def test_effect_heal_self():
    engine = make_engine(("wuzhu", "jianke"))
    learn_all(engine, "wuzhu")
    player = engine.player
    player.fighter.hp = max(1, player.fighter.max_hp - 20)
    hp0 = player.fighter.hp
    player.fighter.mp = player.fighter.max_mp
    engine.execute_skill(3)  # 槽 3 = 回春术
    assert player.fighter.hp > hp0


def test_effect_poison_dot():
    engine = make_engine(("wuzhu", "jianke"))
    learn_all(engine, "wuzhu")
    monster = put_monster(engine, 1, 0)
    engine.player.fighter.mp = engine.player.fighter.max_mp
    engine.execute_skill(2, target=monster)  # 槽 2 = 蚀心蛊
    assert monster.fighter.poisoned
    assert monster.fighter.dot[1] == 6
    hp0 = monster.fighter.hp
    from actions import WaitAction

    engine.handle_action(WaitAction())  # 敌回合结算毒伤
    assert monster.fighter.hp == hp0 - monster.fighter.dot[0] or monster.fighter.hp < hp0


def test_effect_summon():
    engine = make_engine(("yushou", "leifa"))
    learn_all(engine, "yushou")
    count0 = len(engine.gamemap.actors)
    engine.player.fighter.mp = engine.player.fighter.max_mp
    engine.execute_skill(1)  # 槽 1 = 灵犬契约
    beasts = [a for a in engine.gamemap.actors if a.summon_ttl is not None]
    assert len(beasts) == 1
    assert len(engine.gamemap.actors) == count0 + 1
    beast = beasts[0]
    assert beast.team == "player"
    assert beast.fighter.power == 4 and beast.fighter.max_hp == 10
    from ai import AlliedAI

    assert isinstance(beast.ai, AlliedAI)


def test_effect_stun_aoe():
    engine = make_engine(("yushou", "leifa"))
    learn_all(engine, "yushou")
    m1 = put_monster(engine, 1, 0)
    engine.player.fighter.mp = engine.player.fighter.max_mp
    engine.execute_skill(6)  # 槽 6 = 白泽啸：stun 1 回合
    assert m1.fighter.stun_turns >= 1
    # 眩晕的怪跳过 AI：位置不动
    x0, y0 = m1.x, m1.y
    engine.gamemap.visible[m1.x, m1.y] = True  # 强制可见确保无路可走≠未眩晕
    from actions import WaitAction

    engine.handle_action(WaitAction())
    assert (m1.x, m1.y) == (x0, y0)
    assert m1.fighter.stun_turns == 0


def test_effect_mp_restore():
    engine = make_engine(("yueshi", "leifa"))
    learn_all(engine, "yueshi")
    player = engine.player
    player.fighter.mp = 0
    engine.execute_skill(2)  # 槽 2 = 清心曲（mp0 消耗）
    assert player.fighter.mp == 6


def test_hp_cost_skill():
    engine = make_engine(("wuzhu", "jianke"))
    learn_all(engine, "wuzhu")
    player = engine.player
    put_monster(engine, 1, 0)
    player.fighter.mp = player.fighter.max_mp
    player.fighter.hp = 5  # 血祭 hp_cost 6，不足拒放
    with pytest.raises(Impossible):
        engine.execute_skill(6, target=put_monster(engine, -1, 0))
    player.fighter.hp = player.fighter.max_hp
    target = put_monster(engine, -1, 0)
    hp0 = player.fighter.hp
    engine.execute_skill(6, target=target)  # 槽 6 = 血祭
    assert player.fighter.hp == hp0 - 6


def test_mp_low_rejected():
    engine = make_engine()
    learn_all(engine, "leifa")
    engine.player.fighter.mp = 0
    with pytest.raises(Impossible):
        engine.execute_skill(1, target=put_monster(engine, 1, 0))


def test_not_learned_rejected():
    engine = make_engine()
    with pytest.raises(Impossible):
        engine.execute_skill(1, target=put_monster(engine, 1, 0))


# ---- 技能等级制（10 级，满级前可续加） ----


def test_skill_level_upgrade_to_max():
    engine = make_engine()
    player = engine.player
    player.skill_points = 30
    # 5 重与 10 重突破共需精魄×2 + 魔核×1
    give_craft_materials(engine, ("mat_demon_core", "mat_elite_essence"), 5)
    engine.learn_skill("s_leifa_1")  # 初学 1 点
    for _ in range(9):  # 升到 10 级
        engine.learn_skill("s_leifa_1")
    assert player.skill_levels["s_leifa_1"] == 10
    from exceptions import Impossible as Imp

    with pytest.raises(Imp):  # 满级拒绝
        engine.learn_skill("s_leifa_1")


def test_skill_effect_scales_with_level():
    import skills as skills_module

    engine = make_engine()
    player = engine.player
    engine.learn_skill("s_leifa_1")
    lv1 = skills_module.skill_effect_scaled(engine.content.skills["s_leifa_1"], 1)
    lv5 = skills_module.skill_effect_scaled(engine.content.skills["s_leifa_1"], 5)
    e1, e5 = lv1["effect"], lv5["effect"]
    mult = 1 + 0.2 * 4
    assert e5["power"] == max(1, round(e1["power"] * mult))
    assert e5.get("scale", 0) == max(1, round(e1.get("scale", 0) * mult))
    assert e5.get("radius", e1.get("radius")) == e1.get("radius")  # 非强度字段不变
    assert skills_module.skill_effect_scaled(engine.content.skills["s_leifa_1"], 1) is engine.content.skills["s_leifa_1"]


def test_higher_level_skill_hits_harder():
    """同技能不同等级实战伤害更高（cast 走缩放路径）。"""
    import tile_types

    engine = make_engine()
    player = engine.player
    gm = engine.gamemap
    px, py = player.x, player.y
    for cx in range(px, px + 4):
        gm.terrain[cx, py] = tile_types.T_PLAIN
    gm.refresh_tile_flags()

    def kill_damage(skill_level_points):
        player.skill_levels["s_leifa_1"] = skill_level_points
        beast = engine.content.build_monster("xingxing", gm, px + 2, py)
        beast.fighter.base_max_hp = 999
        beast.fighter._hp = 999
        beast.fighter.base_defense = 0
        from actions import CastSkillAction

        player.fighter.mp = 99
        CastSkillAction(player, 1, target=beast).perform(engine)
        return 999 - beast.fighter.hp

    player.learned_skills  # noqa: B018 —— 触发 property 正常
    d1 = kill_damage(1)
    d10 = kill_damage(10)
    assert d10 > d1 * 2, f"10 级伤害 {d10} 应显著高于 1 级 {d1}"


def test_skill_levels_save_roundtrip(tmp_path, monkeypatch):
    import save_manager

    monkeypatch.setattr(save_manager, "SAVE_DIR", str(tmp_path))
    engine = make_engine()
    engine.player.skill_points = 20
    engine.learn_skill("s_leifa_1")
    engine.learn_skill("s_leifa_1")
    engine.learn_skill("s_leifa_1")  # Lv3
    engine.autosave()
    loaded = save_manager.load_engine(engine.content, Settings())
    assert loaded.player.skill_levels.get("s_leifa_1") == 3
    assert set(loaded.player.skill_levels) == loaded.player.learned_skills  # 视图一致


def test_legacy_save_learned_skills_become_level1(tmp_path, monkeypatch):
    """旧档（learned_skills 列表）读入后全部视为 1 级。"""
    import json

    import save_manager

    monkeypatch.setattr(save_manager, "SAVE_DIR", str(tmp_path))
    engine = make_engine()
    engine.player.skill_points = 5
    engine.learn_skill("s_leifa_1")
    engine.autosave()
    # 手工把档改成旧格式
    path = save_manager.save_path()
    data = json.loads(path.read_text(encoding="utf-8"))
    data["player"]["learned_skills"] = ["s_leifa_1", "s_leifa_2"]
    del data["player"]["skill_levels"]
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    loaded = save_manager.load_engine(engine.content, Settings())
    assert loaded.player.skill_levels == {"s_leifa_1": 1, "s_leifa_2": 1}
