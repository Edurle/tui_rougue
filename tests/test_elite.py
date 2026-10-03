"""精英怪与专属掉落经济测试：精英化/掉落/顶级配方/技能材料门槛/存档往返。"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tile_types  # noqa: E402
from content_loader import load_content  # noqa: E402
from engine import Engine  # noqa: E402
from settings import Settings  # noqa: E402


def make_engine() -> Engine:
    return Engine(load_content(), Settings())


def give_material(engine, material_id, count):
    item = engine.content.build_item(material_id, engine.gamemap, 0, 0)
    engine.gamemap.entities.discard(item)
    item.gamemap = None
    item.stack = count
    engine.player.inventory.add(item)


def clear_and_place(engine, dx, dy, monster_id, elite=False):
    gm = engine.gamemap
    px, py = engine.player.x, engine.player.y
    for cx in range(min(px, px + dx), max(px, px + dx) + 1):
        for cy in range(min(py, py + dy), max(py, py + dy) + 1):
            gm.terrain[cx, cy] = tile_types.T_PLAIN
    gm.refresh_tile_flags()
    return engine.content.build_monster(monster_id, gm, px + dx, py + dy, elite=elite)


# ---- 精英怪 ----


def test_elite_monster_stats_and_prefix():
    engine = make_engine()
    normal = clear_and_place(engine, 3, 0, "xingxing")
    elite = clear_and_place(engine, 5, 0, "xingxing", elite=True)
    assert "elite" in elite.tags and "elite" not in normal.tags
    assert "精英·" in elite.name
    assert elite.fighter.max_hp == int(normal.fighter.max_hp * 1.8)
    assert elite.fighter.base_power == int(normal.fighter.base_power * 1.4)
    assert elite.fighter.xp_reward == int(normal.fighter.xp_reward * 3)


def test_elite_drops_essence_on_death():
    engine = make_engine()
    elite = clear_and_place(engine, 3, 0, "xingxing", elite=True)
    engine.player.fighter.power = 999
    engine.player.fighter.attack(elite.fighter)
    assert not elite.is_alive
    drops = [i.name for i in engine.gamemap.items if i.is_material]
    assert any("精魄" in n for n in drops), "精英应必掉精魄"


def test_world_and_realm_have_elites():
    """世界生成含精英（概率性，宽松断言多次采样）。"""
    found = False
    for seed in range(5):
        engine = make_engine()
        if any("elite" in getattr(a, "tags", []) for a in engine.world.actors):
            found = True
            break
    assert found, "世界投放应出现精英怪"


# ---- 顶级配方 ----


def test_top_recipes_require_special_drops():
    import craft

    content = load_content()
    by_id = {r["id"]: r for r in content.recipes}
    for rid, needs in (
        ("alchemy_ninegold", ("mat_elite_essence", "mat_demon_core")),
        ("talisman_execlipse", ("mat_elite_essence",)),
        ("forge_xuanyuan", ("mat_elite_essence", "mat_demon_core")),
    ):
        inputs = {entry["id"] for entry in by_id[rid]["inputs"]}
        assert set(needs) <= inputs, f"{rid} 应消耗专属掉落"

    engine = make_engine()
    give_material(engine, "mat_spirit_herb", 4)
    give_material(engine, "mat_cinnabar", 2)
    give_material(engine, "mat_elite_essence", 1)
    give_material(engine, "mat_demon_core", 1)
    craft.execute_recipe(engine, by_id["alchemy_ninegold"])
    assert any("九转金丹" in i.name for i in engine.player.inventory.items)


# ---- 技能材料门槛 ----


def test_ultimate_requires_demon_core():
    from exceptions import Impossible

    engine = make_engine()
    player = engine.player
    player.skill_points = 9
    for sid in ("s_leifa_1", "s_leifa_3", "s_leifa_7"):
        engine.learn_skill(sid)
    try:
        engine.learn_skill("s_leifa_8")  # 大招：无魔核
        raise AssertionError("大招无魔核应被拒绝")
    except Impossible as exc:
        assert "魔核" in str(exc)
    give_material(engine, "mat_demon_core", 1)
    engine.learn_skill("s_leifa_8")
    assert player.skill_levels["s_leifa_8"] == 1
    assert engine.player.inventory.count_material("mat_demon_core", engine.content) == 0


def test_breakthrough_at_5_and_10_need_essence():
    from exceptions import Impossible

    engine = make_engine()
    player = engine.player
    player.skill_points = 30
    engine.learn_skill("s_leifa_1")
    for _ in range(3):  # 升到 4 重
        engine.learn_skill("s_leifa_1")
    assert player.skill_levels["s_leifa_1"] == 4
    try:
        engine.learn_skill("s_leifa_1")  # 5 重突破：无精魄
        raise AssertionError("5 重无精魄应被拒绝")
    except Impossible as exc:
        assert "精魄" in str(exc)
    give_material(engine, "mat_elite_essence", 2)
    give_material(engine, "mat_demon_core", 1)
    engine.learn_skill("s_leifa_1")  # 5 重
    assert player.skill_levels["s_leifa_1"] == 5
    for _ in range(4):  # 6-9 重
        engine.learn_skill("s_leifa_1")
    engine.learn_skill("s_leifa_1")  # 10 重：精魄+魔核
    assert player.skill_levels["s_leifa_1"] == 10
    assert engine.player.inventory.count_material("mat_elite_essence", engine.content) == 0
    assert engine.player.inventory.count_material("mat_demon_core", engine.content) == 0


# ---- 存档往返 ----


def test_elite_monster_save_roundtrip(tmp_path, monkeypatch):
    import save_manager

    monkeypatch.setattr(save_manager, "SAVE_DIR", str(tmp_path))
    engine = make_engine()
    elite = clear_and_place(engine, 3, 0, "xingxing", elite=True)
    engine.autosave()
    loaded = save_manager.load_engine(engine.content, Settings())
    # 按测试创建的位置定位（世界中另有随机投放的精英，不能混同）
    ex, ey = elite.x, elite.y
    restored = next(
        a
        for a in loaded.gamemap.actors
        if "elite" in getattr(a, "tags", []) and (a.x, a.y) == (ex, ey)
    )
    assert "精英·" in restored.name and "狌狌" in restored.name
    assert restored.fighter.base_power == elite.fighter.base_power
