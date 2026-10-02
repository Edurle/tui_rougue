"""回合状态机与瞄准交互测试：buff/毒/眩晕/召唤回合流，瞄准输入管线，渲染断言。"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tcod  # noqa: E402
from tcod.event import KeySym  # noqa: E402

import input_handlers as ih  # noqa: E402
from actions import WaitAction  # noqa: E402
from content_loader import load_content  # noqa: E402
from engine import Engine  # noqa: E402
from exceptions import NeedTarget  # noqa: E402
from settings import Settings  # noqa: E402


def make_engine(class_ids=("leifa", "fushi")):
    return Engine(load_content(), Settings(), class_ids)


def dispatch_key(handler, sym, shift=False):
    mod = tcod.event.Modifier.SHIFT if shift else tcod.event.Modifier.NONE
    return handler.dispatch(tcod.event.KeyDown(sym=sym, scancode=0, mod=mod, repeat=False))


def learn_all(engine, class_id):
    player = engine.player
    player.skill_points = 99
    for _ in range(10):
        progress = False
        for skill in engine.content.skills_for_class(class_id):
            if skill["id"] in player.learned_skills:
                continue
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


# ---- 回合状态机 ----


def test_buff_decays_per_turn():
    engine = make_engine()
    learn_all(engine, "leifa")
    player = engine.player
    player.fighter.mp = player.fighter.max_mp
    engine.execute_skill(4)  # 引雷符：攻+2 / 12 回合
    boosted = player.fighter.power
    for _ in range(12):
        engine.handle_action(WaitAction())
    assert player.fighter.power == boosted - 2


def test_poison_ticks_and_expires_on_monster():
    engine = make_engine(("wuzhu", "jianke"))
    learn_all(engine, "wuzhu")
    monster = put_monster(engine, 1, 0)
    player = engine.player
    player.fighter.mp = player.fighter.max_mp
    engine.execute_skill(2, target=monster)  # 蚀心蛊：3/回合 ×6
    per_turn = monster.fighter.dot[0]
    hp0 = monster.fighter.hp
    for i in range(6):
        engine.handle_action(WaitAction())
        expected = max(0, hp0 - per_turn * (i + 1))
        if monster.is_alive:
            assert monster.fighter.hp == expected
    assert not monster.is_alive or not monster.fighter.poisoned  # 6 回合后毒解（或已毒毙）


def test_stun_skips_ai_turn():
    engine = make_engine(("yushou", "leifa"))
    learn_all(engine, "yushou")
    monster = put_monster(engine, 1, 0)  # 白泽啸半径 1.5，怪须在近旁
    player = engine.player
    player.fighter.mp = player.fighter.max_mp
    engine.execute_skill(6)  # 白泽啸：stun 1 回合
    assert monster.fighter.stun_turns >= 1
    x0, y0 = monster.x, monster.y
    engine.gamemap.visible[monster.x, monster.y] = True
    engine.handle_action(WaitAction())
    assert (monster.x, monster.y) == (x0, y0)
    assert monster.fighter.stun_turns == 0  # 眩晕仅持续 1 回合


def test_summon_expires_after_duration():
    engine = make_engine(("yushou", "leifa"))
    learn_all(engine, "yushou")
    player = engine.player
    player.fighter.mp = player.fighter.max_mp
    engine.execute_skill(1)  # 灵犬契约 15 回合
    beasts = [a for a in engine.gamemap.actors if a.summon_ttl is not None]
    assert len(beasts) == 1
    beast = beasts[0]
    for _ in range(15):
        engine.handle_action(WaitAction())
        if beast not in engine.gamemap.entities:
            break
    assert beast not in engine.gamemap.entities
    assert beast not in engine.gamemap.actors


def test_summon_tanks_hostility():
    """召唤兽比玩家更近时，异兽的仇恨落在召唤兽上。"""
    engine = make_engine(("yushou", "leifa"))
    learn_all(engine, "yushou")
    player = engine.player
    player.fighter.mp = player.fighter.max_mp
    engine.execute_skill(1)
    beast = next(a for a in engine.gamemap.actors if a.summon_ttl is not None)
    # 把玩家移远：清出一条空地放怪（怪放召唤兽旁）
    monster = engine.content.build_monster("xingxing", engine.gamemap, beast.x + 1, beast.y)
    engine.gamemap.visible[beast.x, beast.y] = True
    engine.gamemap.visible[monster.x, monster.y] = True
    dist_player = monster.distance_to(player)
    dist_beast = monster.distance_to(beast)
    if dist_beast < dist_player:
        beast_hp0 = beast.fighter.hp
        for _ in range(6):
            engine.handle_action(WaitAction())
            if beast.fighter.hp < beast_hp0 or not beast.is_alive:
                break
        assert not beast.is_alive or beast.fighter.hp < beast_hp0, "近处的召唤兽应承伤"


def test_allied_ai_attacks_nearest_enemy():
    from ai import AlliedAI

    engine = make_engine(("yushou", "leifa"))
    learn_all(engine, "yushou")
    player = engine.player
    player.fighter.mp = player.fighter.max_mp
    engine.execute_skill(1)
    beast = next(a for a in engine.gamemap.actors if a.summon_ttl is not None)
    monster = engine.content.build_monster("xingxing", engine.gamemap, beast.x + 1, beast.y)
    assert isinstance(beast.ai, AlliedAI)
    engine.gamemap.visible[beast.x, beast.y] = True
    beast.ai.perform()
    # 相邻即攻击：怪掉血或被杀
    assert not monster.is_alive or monster.fighter.hp < monster.fighter.max_hp


# ---- 瞄准输入管线 ----


def test_targeting_pipeline_tab_confirm_escape():
    engine = make_engine()
    learn_all(engine, "leifa")
    player = engine.player
    m1 = put_monster(engine, 2, 0)
    m2 = put_monster(engine, 3, 0)
    engine.gamemap.update_fov(player.x, player.y)
    handler = ih.MainGameEventHandler(engine)

    # 按 1（掌心雷）→ CastSkillAction → 引擎抛 NeedTarget
    action = dispatch_key(handler, KeySym.N1)
    assert type(action).__name__ == "CastSkillAction"
    with pytest.raises(NeedTarget):
        engine.handle_action(action)

    skill = engine.content.skill_for_slot("leifa", 1)
    handler = ih.TargetingEventHandler(engine, skill, 1)
    assert handler.current_target is not None
    first = handler.current_target
    # Tab 循环换目标
    action = dispatch_key(handler, KeySym.TAB)
    assert action is None
    assert handler.current_target is not first or len({m1, m2}) == 1
    # 回车确认 → 带目标施放
    hp_before = handler.current_target.fighter.hp
    action = dispatch_key(handler, KeySym.RETURN)
    assert type(action).__name__ == "CastSkillAction"
    mp_before = player.fighter.mp
    engine.handle_action(action)
    target = action.target
    assert not target.is_alive or target.fighter.hp < hp_before
    assert player.fighter.mp < mp_before


def test_targeting_escape_costs_nothing():
    engine = make_engine()
    learn_all(engine, "leifa")
    player = engine.player
    put_monster(engine, 2, 0)
    engine.gamemap.update_fov(player.x, player.y)
    skill = engine.content.skill_for_slot("leifa", 1)
    handler = ih.TargetingEventHandler(engine, skill, 1)
    mp_before = player.fighter.mp
    action = dispatch_key(handler, KeySym.ESCAPE)
    assert isinstance(action, ih.CloseMenuAction)
    assert player.fighter.mp == mp_before


def test_targeting_mouse_click_selects():
    engine = make_engine()
    learn_all(engine, "leifa")
    player = engine.player
    monster = put_monster(engine, 2, 0)
    engine.gamemap.update_fov(player.x, player.y)
    skill = engine.content.skill_for_slot("leifa", 1)
    handler = ih.TargetingEventHandler(engine, skill, 1)
    from render import viewport_offset

    off_x, off_y = viewport_offset(engine)
    click = tcod.event.MouseButtonDown(
        button=1, position=tcod.event.Point(monster.x + off_x, monster.y + off_y)
    )
    action = handler.dispatch(click)
    assert type(action).__name__ == "CastSkillAction"
    assert action.target is monster
    hp0 = monster.fighter.hp
    engine.handle_action(action)
    assert not monster.is_alive or monster.fighter.hp < hp0


def test_direction_select_pipeline():
    engine = make_engine()
    learn_all(engine, "leifa")
    player = engine.player
    skill = engine.content.skill_for_slot("leifa", 2)  # 疾风步
    handler = ih.DirectionSelectEventHandler(engine, skill, 2)
    action = dispatch_key(handler, KeySym.UP)  # 向上
    assert action is None and (handler.dx, handler.dy) == (0, -1)
    x0, y0 = player.x, player.y
    action = dispatch_key(handler, KeySym.RETURN)
    assert type(action).__name__ == "CastSkillAction"
    engine.handle_action(action)
    assert (player.x, player.y) != (x0, y0)
    assert player.y <= y0  # 向上位移


def test_tab_switches_skill_page():
    engine = make_engine()
    handler = ih.MainGameEventHandler(engine)
    assert engine.active_page == 0
    dispatch_key(handler, KeySym.TAB)
    assert engine.active_page == 1
    dispatch_key(handler, KeySym.TAB)
    assert engine.active_page == 0


def test_k_opens_learn_menu_and_learn_flow():
    engine = make_engine()
    handler = ih.MainGameEventHandler(engine)
    action = dispatch_key(handler, KeySym.K)
    assert isinstance(action, ih.OpenSkillLearnAction)
    handler = ih.SkillLearnEventHandler(engine)
    assert "掌心雷" not in " ".join(m.plain_text for m in engine.message_log.messages)
    # 光标 0 → 回车学习链首
    action = dispatch_key(handler, KeySym.RETURN)
    assert action is None  # 学习不消耗回合
    assert engine.player.skill_points == 1
    assert "s_leifa_1" in engine.player.learned_skills
    # Tab 切到副职业页
    dispatch_key(handler, KeySym.TAB)
    assert handler.page == 1 and engine.active_page == 1
    # Esc 关闭
    action = dispatch_key(handler, KeySym.ESCAPE)
    assert isinstance(action, ih.CloseMenuAction)


# ---- 渲染断言 ----


def sidebar_text(console, engine, rows):
    x = engine.settings.content_x
    return "".join(
        "".join(chr(c) for c in console.rgb[x:, y]["ch"] if c != 32) for y in rows
    )


def test_sidebar_renders_skills_and_equipment():
    import render

    engine = make_engine()
    from settings import sidebar_layout

    layout = sidebar_layout(engine.settings.total_rows)
    learn_all(engine, "leifa")
    engine.player.fighter.mp = 0  # 真气不足 → 暗红仍在
    console = tcod.console.Console(engine.settings.total_cols, engine.settings.total_rows, order="F")
    render.render_all(console, engine)
    skill_rows = list(range(layout["skill_first"], layout["skill_first"] + layout["skill_count"]))
    text = sidebar_text(console, engine, skill_rows)
    assert "掌心雷" in text and "疾风步" in text
    # 装备区：空槽占位
    equip_rows = list(range(layout["equip_first"], layout["equip_first"] + 5))
    text = sidebar_text(console, engine, equip_rows)
    for slot_key in ("兵", "甲", "履", "佩", "冠"):
        assert slot_key in text

    # 装备后显示件名
    from actions import EquipAction

    item = engine.content.build_item("w_taomu", engine.gamemap, 0, 0)
    engine.gamemap.entities.discard(item)
    engine.player.inventory.add(item)
    EquipAction(engine.player, item).perform(engine)
    render.render_all(console, engine)
    text = sidebar_text(console, engine, equip_rows)
    assert "桃木剑" in text


def test_sidebar_compact_two_columns():
    import render

    from settings import sidebar_layout

    for map_size, expect_two in (("large", True), ("medium", False)):
        settings = Settings(map_size, "large")
        layout = sidebar_layout(settings.total_rows)
        assert layout["skill_two_cols"] is expect_two
        assert settings.log_height >= 5
        assert layout["divider"] + settings.log_height + 1 == settings.total_rows


def test_learn_menu_renders_marks():
    import render

    engine = make_engine()  # 未学任何技能：链首 · 可学，链中 × 前置未齐
    console = tcod.console.Console(engine.settings.total_cols, engine.settings.total_rows, order="F")
    render.render_skill_learn_menu(console, engine, page=0, cursor=0)
    full = "".join(
        "".join(chr(c) for c in console.rgb[:, y]["ch"] if c != 32)
        for y in range(console.height)
    )
    assert "掌心雷" in full and "·" in full  # 链首可学标记
    assert "×" in full and "需" in full  # 前置未齐标记（雷池需掌心雷）
