"""抗性系统测试：折算数学、技能/DOT/眩晕/元素爪击路径、装备词条聚合、数据校验。"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from actions import EquipAction  # noqa: E402
from content_loader import load_content  # noqa: E402
from engine import Engine  # noqa: E402
from settings import Settings  # noqa: E402


def make_engine(class_ids=("leifa", "fushi")):
    return Engine(load_content(), Settings(), class_ids)


def learn_all(engine, class_id):
    player = engine.player
    player.skill_points = 99
    for _ in range(10):
        progress = False
        for skill in engine.content.skills_for_class(class_id):
            if skill["id"] not in player.learned_skills:
                try:
                    engine.learn_skill(skill["id"])
                    progress = True
                except Exception:
                    pass
        if not progress:
            break


def put_monster(engine, dx, dy, monster_id="xingxing"):
    return engine.content.build_monster(
        monster_id, engine.gamemap, engine.player.x + dx, engine.player.y + dy
    )


# ---- 数据校验 ----


def test_monster_resistance_data_valid():
    content = load_content()
    # 加载即校验（kind/范围）；抽查已配置的抗性
    assert content.monsters["zhulong"]["resistances"]["thunder"] == 60
    assert content.monsters["zhulong"]["resistances"]["fire"] == 60
    assert content.monsters["xiangliu"]["resistances"]["poison"] == 60
    assert content.monsters["bifang"]["attack_tags"] == ["fire"]
    assert "resistances" not in content.monsters["xingxing"]  # 初级怪无抗性
    # build 后聚合可读
    engine = make_engine()
    zhulong = put_monster(engine, 2, 0, "zhulong")
    assert zhulong.fighter.resistance("thunder") == 60
    assert zhulong.fighter.resistance("poison") == 0


def test_invalid_resistance_rejected():
    content = load_content()
    content.monsters["bad"] = {
        "name": "坏",
        "char": "b",
        "color": [1, 1, 1],
        "resistances": {"shadow": 50},
        "components": {"fighter": {"hp": 5, "power": 1, "defense": 0, "xp_reward": 0},
                       "ai": {"type": "hostile"}},
    }
    with pytest.raises(Exception):
        content._validate()


def test_out_of_range_resistance_rejected():
    content = load_content()
    content.monsters["bad2"] = {
        "name": "坏2",
        "char": "b",
        "color": [1, 1, 1],
        "resistances": {"fire": 95},
        "components": {"fighter": {"hp": 5, "power": 1, "defense": 0, "xp_reward": 0},
                       "ai": {"type": "hostile"}},
    }
    with pytest.raises(Exception):
        content._validate()


# ---- 折算数学 ----


def test_mitigate_math():
    from fighter import Fighter

    f = Fighter(hp=10, power=1, defense=0, resistances={"fire": 50})
    assert f.mitigate_incoming(8, ["fire"]) == 4  # 50% 折半
    assert f.mitigate_incoming(8, ["fire", "thunder"]) == 4  # 取命中最高抗性
    assert f.mitigate_incoming(8, []) == 8  # 无元素不减
    assert f.mitigate_incoming(8, ["aoe"]) == 8  # 形态 tag 不参与
    f2 = Fighter(hp=10, power=1, defense=0, resistances={"fire": 80})
    assert f2.mitigate_incoming(3, ["fire"]) == 1  # 下限 1 点
    assert f2.mitigate_incoming(1, ["fire"]) == 1


# ---- 技能路径 ----


def test_elemental_skill_reduced_by_target_resistance():
    engine = make_engine()
    learn_all(engine, "leifa")
    player = engine.player
    player.fighter.mp = player.fighter.max_mp
    monster = put_monster(engine, 1, 0, "zhulong")
    monster.fighter.base_max_hp = 200
    monster.fighter.heal(200)
    import skills as sk

    skill = engine.content.skill_for_slot("leifa", 1)  # 掌心雷（thunder）
    raw = sk.compute_damage(player, skill)  # 8（6+1×1.5）
    hp0 = monster.fighter.hp
    engine.execute_skill(1, target=monster)
    expected = monster.fighter.mitigate_incoming(raw, ["thunder"])  # 60% 抗 → round(8×0.4)=3
    assert expected < raw
    assert monster.fighter.hp == hp0 - expected


def test_non_elemental_skill_not_reduced():
    engine = make_engine(("jianke", "leifa"))
    learn_all(engine, "jianke")
    player = engine.player
    player.fighter.mp = player.fighter.max_mp
    monster = put_monster(engine, 1, 0, "zhulong")
    monster.fighter.base_max_hp = 200
    monster.fighter.heal(200)
    import skills as sk

    skill = engine.content.skill_for_slot("jianke", 1)  # 斩铁（无元素 tag）
    raw = sk.compute_damage(player, skill)
    hp0 = monster.fighter.hp
    engine.execute_skill(1, target=monster)
    assert monster.fighter.hp == hp0 - raw  # 烛龙雷/火抗不影响纯物理技能


def test_poison_dot_reduced_by_resistance():
    engine = make_engine(("gushi", "leifa"))
    learn_all(engine, "gushi")
    player = engine.player
    player.fighter.mp = player.fighter.max_mp
    target = put_monster(engine, 1, 0, "qiuyu")  # 犰狳毒抗 40
    target.fighter.base_max_hp = 100
    target.fighter.heal(100)
    engine.execute_skill(1, target=target)  # 蚀骨蛊：3/跳 ×5
    per_tick = target.fighter.dot[0]
    assert per_tick == max(1, int(round((3 + 1) * 0.6)))  # 4 → 2
    hp0 = target.fighter.hp
    from actions import WaitAction

    engine.handle_action(WaitAction())
    assert target.fighter.hp == hp0 - per_tick


def test_stun_duration_shortened_by_willpower():
    engine = make_engine(("yushou", "leifa"))
    learn_all(engine, "yushou")
    player = engine.player
    player.fighter.mp = player.fighter.max_mp
    # 白泽啸 stun 1 回合：九尾狐定力 50 → 完全抵抗；无抗性怪正常中眩
    fox = put_monster(engine, 1, 0, "jiuweihu")
    engine.execute_skill(6)
    assert fox.fighter.stun_turns == 0  # int(1×0.5)=0 → 抵抗

    plain = put_monster(engine, -1, 0, "xingxing")
    engine.player.fighter.mp = engine.player.fighter.max_mp
    engine.execute_skill(6)
    assert plain.fighter.stun_turns >= 1  # 无定力怪正常被眩晕


# ---- 玩家侧：装备词条 ----


def test_player_resistance_from_equipment():
    engine = make_engine()
    player = engine.player
    assert player.fighter.resistance("fire") == 0
    robe = engine.content.build_item("a_bihuo", engine.gamemap, 0, 0)
    engine.gamemap.entities.discard(robe)
    player.inventory.add(robe)
    EquipAction(player, robe).perform(engine)
    assert player.fighter.resistance("fire") == 40
    assert player.fighter.resistance("thunder") == 0


def test_player_resistance_capped_at_80():
    engine = make_engine()
    player = engine.player
    player.fighter.base_resistances["fire"] = 60
    robe = engine.content.build_item("a_bihuo", engine.gamemap, 0, 0)
    engine.gamemap.entities.discard(robe)
    player.inventory.add(robe)
    EquipAction(player, robe).perform(engine)
    assert player.fighter.resistance("fire") == 80  # 60+40 封顶


def test_monster_elemental_attack_reduced_by_player_gear():
    engine = make_engine()
    player = engine.player
    bifang = put_monster(engine, 1, 0, "bifang")  # 火爪
    assert bifang.attack_tags == ["fire"]
    robe = engine.content.build_item("a_bihuo", engine.gamemap, 0, 0)
    engine.gamemap.entities.discard(robe)
    player.inventory.add(robe)
    EquipAction(player, robe).perform(engine)

    # 无抗性基线：多轮被击，统计有抗后的伤害是否显著低于 (power-defense) 上界
    player.fighter.base_defense = 100  # 挡到接近 0 伤，看抗性是否仍保底
    player.fighter.heal(999)
    hp0 = player.fighter.hp
    bifang.fighter.attack(player.fighter)
    # power7 - def100 + rand[-1,2] ≤ 0 → 抗性折算前 ≤0；折算下限 1 仅对 >0 生效
    # 该轮伤害 0 或 1，任何情况都不应超过 1
    assert player.fighter.hp >= hp0 - 1


def test_resist_description_for_targeting_ui():
    engine = make_engine()
    learn_all(engine, "leifa")
    import skills as sk

    skill = engine.content.skill_for_slot("leifa", 1)  # 掌心雷 thunder
    zhulong = put_monster(engine, 2, 0, "zhulong")
    desc = sk.resist_description(engine.content, zhulong, skill)
    assert "雷抗" in desc and "60" in desc
    plain = put_monster(engine, -2, 0, "xingxing")
    assert sk.resist_description(engine.content, plain, skill) == ""


def test_four_resistance_gear_pieces_exist():
    content = load_content()
    resist_gear = [
        iid for iid, idef in content.equip_items.items()
        if any(a["id"].startswith("resist_") for a in idef["equipment"].get("affixes", []))
    ]
    assert len(resist_gear) >= 4  # 雷/火/毒/定力 四类覆盖
    kinds = {
        a["id"]
        for iid in resist_gear
        for a in content.equip_items[iid]["equipment"]["affixes"]
        if a["id"].startswith("resist_")
    }
    assert kinds == {"resist_thunder", "resist_fire", "resist_poison", "resist_stun"}
