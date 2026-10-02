"""存档系统测试：roundtrip 状态一致、死亡删档、版本不符拒绝。"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from actions import TakeStairsAction  # noqa: E402
from content_loader import load_content  # noqa: E402
from engine import Engine  # noqa: E402
from settings import Settings  # noqa: E402


def setup_module(module):
    import save_manager

    save_manager._test_orig_dir = save_manager.SAVE_DIR


def teardown_module(module):
    import save_manager

    save_manager.SAVE_DIR = save_manager._test_orig_dir


def make_engine() -> Engine:
    return Engine(load_content(), Settings())


def _find_gate(engine, realm_id):
    for entity in engine.world.entities:
        if "realm_gate" in entity.tags and realm_id in entity.tags:
            return entity
    return None


def test_save_load_roundtrip(tmp_path, monkeypatch):
    import save_manager

    monkeypatch.setattr(save_manager, "SAVE_DIR", str(tmp_path))

    engine = make_engine()
    # 制造状态：升级 + 学技能 + 掉血 + 进秘境下行一层
    player = engine.player
    player.level.current_xp = 77
    player.skill_points = 5
    player.fighter.hp -= 5
    player.fighter.mp -= 3
    gate = _find_gate(engine, "yaoshan_gudong")
    engine.player.x, engine.player.y = gate.x, gate.y
    TakeStairsAction(engine.player, "down").perform(engine)  # autosave 触发
    engine.player.x, engine.player.y = engine.gamemap.downstairs_xy
    TakeStairsAction(engine.player, "down").perform(engine)  # BOSS 层
    world_explored_before = engine.world.explored.sum()
    realm_1_before = engine.realms["yaoshan_gudong"][1]

    assert save_manager.save_exists()
    loaded = save_manager.load_engine(engine.content, Settings())
    assert loaded is not None

    # 玩家状态一致
    lp = loaded.player
    assert (lp.x, lp.y) == (engine.player.x, engine.player.y)
    assert lp.level.current_xp == 77 and lp.skill_points == 5
    assert lp.fighter.hp == player.fighter.hp and lp.fighter.mp == player.fighter.mp
    assert set(lp.class_ids) == set(player.class_ids)
    # 世界一致
    assert loaded.world.width == engine.world.width
    assert loaded.world.explored.sum() == world_explored_before
    assert len(loaded.world.actors) == len(engine.world.actors)
    # 秘境缓存一致（第 1 层对象级比较：地形数组相等）
    assert "yaoshan_gudong" in loaded.realms
    assert 1 in loaded.realms["yaoshan_gudong"]
    assert (loaded.realms["yaoshan_gudong"][1].terrain == realm_1_before.terrain).all()
    # 当前上下文一致：在 BOSS 层（第 2 层）
    assert loaded.gamemap.map_type == "realm"
    assert loaded.gamemap.realm_id == "yaoshan_gudong"
    assert loaded.gamemap.realm_depth == 2
    assert any("boss" in getattr(a, "tags", []) for a in loaded.gamemap.actors)


def test_player_death_deletes_save(tmp_path, monkeypatch):
    import save_manager

    monkeypatch.setattr(save_manager, "SAVE_DIR", str(tmp_path))

    engine = make_engine()
    engine.autosave()
    assert save_manager.save_exists()

    killer = engine.content.build_monster(
        "zhulong", engine.gamemap, engine.player.x + 1, engine.player.y
    )
    killer.fighter.power = 999
    import tile_types

    gm = engine.gamemap
    for cx in range(engine.player.x, engine.player.x + 2):
        gm.terrain[cx, engine.player.y] = tile_types.T_PLAIN
    gm.refresh_tile_flags()
    killer.fighter.attack(engine.player.fighter)
    assert engine.game_over
    assert not save_manager.save_exists(), "陨落应删档"


def test_version_mismatch_rejected(tmp_path, monkeypatch):
    import save_manager

    monkeypatch.setattr(save_manager, "SAVE_DIR", str(tmp_path))
    engine = make_engine()
    engine.autosave()
    # 篡改版本号
    path = save_manager.save_path()
    data = json.loads(path.read_text(encoding="utf-8"))
    data["version"] = 99999
    path.write_text(json.dumps(data), encoding="utf-8")
    assert save_manager.load_engine(engine.content, Settings()) is None


def test_class_select_has_continue_option(tmp_path, monkeypatch):
    import input_handlers as ih
    import save_manager

    monkeypatch.setattr(save_manager, "SAVE_DIR", str(tmp_path))
    engine = make_engine()
    engine.autosave()

    handler = ih.ClassSelectEventHandler(engine.content, Settings(), has_save=True)
    options = handler._options()
    assert options[0] == ih.CONTINUE_ID
    assert len(options) == len(engine.content.classes) + 1
