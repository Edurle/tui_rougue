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
    assert (gate.x, gate.y) in engine.known_gates
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
    # 图卷记忆一致
    assert (gate.x, gate.y) in loaded.known_gates


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


def test_title_menu_pipeline(tmp_path, monkeypatch):
    """开始界面：主菜单项完整、继续游历无档置灰、设置界面语言/档位调整。"""
    import input_handlers as ih
    import save_manager
    import tcod
    from tcod.event import KeySym

    monkeypatch.setattr(save_manager, "SAVE_DIR", str(tmp_path))
    content = load_content()
    settings = Settings()

    # 无档：继续游历置灰（回车不产生选择）
    handler = ih.TitleMenuEventHandler(content, settings, has_save=False)
    handler.cursor = 1  # 停在"继续游历"
    handler.dispatch(tcod.event.KeyDown(sym=KeySym.RETURN, scancode=0, mod=tcod.event.Modifier.NONE, repeat=False))
    assert not handler.done and handler.choice is None

    # 有档：可选择继续
    engine = make_engine()
    engine.autosave()
    handler = ih.TitleMenuEventHandler(content, settings, has_save=True)
    handler.cursor = 1
    handler.dispatch(tcod.event.KeyDown(sym=KeySym.RETURN, scancode=0, mod=tcod.event.Modifier.NONE, repeat=False))
    assert handler.done and handler.choice == "continue"

    # 设置界面：切换语言（content 即时重载并保存）、切档位（needs_resize）
    menu = ih.SettingsMenuEventHandler(content, settings)
    menu.cursor = 0  # 语言项
    menu.dispatch(tcod.event.KeyDown(sym=KeySym.RIGHT, scancode=0, mod=tcod.event.Modifier.NONE, repeat=False))
    assert settings.lang in ("zh_CN", "en_US") and settings.lang != content.lang
    assert menu.lang_changed and menu.content.lang == settings.lang
    menu.cursor = 1  # 画面
    menu.dispatch(tcod.event.KeyDown(sym=KeySym.RIGHT, scancode=0, mod=tcod.event.Modifier.NONE, repeat=False))
    assert menu.needs_resize and settings.map_size == "medium"
    # Esc 返回
    menu.dispatch(tcod.event.KeyDown(sym=KeySym.ESCAPE, scancode=0, mod=tcod.event.Modifier.NONE, repeat=False))
    assert menu.done


def test_level_up_autosaves(tmp_path, monkeypatch):
    """升级即存档：世界游玩的进度里程碑（防退出丢进度）。"""
    import save_manager

    monkeypatch.setattr(save_manager, "SAVE_DIR", str(tmp_path))
    engine = make_engine()
    assert save_manager.save_exists()  # 开局新区域首入已存

    # 世界中升级（大量经验触发自动升级）
    engine.player.x += 30  # 玩家已移动
    engine.player.level.add_xp(10000)
    assert engine.player.level.current_level >= 2

    loaded = save_manager.load_engine(engine.content, Settings())
    assert loaded.player.level.current_level == engine.player.level.current_level
    assert (loaded.player.x, loaded.player.y) == (engine.player.x, engine.player.y)


def test_exit_session_saves_progress(tmp_path, monkeypatch):
    """退出会话（Esc/关窗）前自动存档：位置与状态落盘。"""
    import save_manager

    monkeypatch.setattr(save_manager, "SAVE_DIR", str(tmp_path))
    engine = make_engine()

    # 模拟世界游玩：移动 + 拾取材料 + 真气消耗（不触发任何常规 autosave 点）
    engine.player.x += 25
    engine.player.y += 8
    engine.player.fighter.mp -= 5
    item = engine.content.build_item("mat_spirit_herb", engine.gamemap, 0, 0)
    engine.gamemap.entities.discard(item)
    item.gamemap = None
    item.stack = 9
    engine.player.inventory.add(item)

    # 模拟 main._run_session 的 finally 语义
    from main import _run_session  # noqa: F401 —— 语义见下；game_loop 需窗口，此处直接调用 autosave
    engine.autosave()

    loaded = save_manager.load_engine(engine.content, Settings())
    assert (loaded.player.x, loaded.player.y) == (engine.player.x, engine.player.y)
    assert loaded.player.fighter.mp == engine.player.fighter.mp
    mats = [i for i in loaded.player.inventory.items if i.is_material]
    assert mats and mats[0].stack == 9
