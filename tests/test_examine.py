"""查看模式测试：X 键进入、Tab 循环、鼠标点击切换、Esc 退出、属性卡渲染。"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tcod  # noqa: E402
from tcod.event import KeySym  # noqa: E402

import input_handlers as ih  # noqa: E402
from content_loader import load_content  # noqa: E402
from engine import Engine  # noqa: E402
from settings import Settings  # noqa: E402


def make_engine(class_ids=("leifa", "fushi")):
    return Engine(load_content(), Settings(), class_ids)


def dispatch_key(handler, sym):
    return handler.dispatch(
        tcod.event.KeyDown(sym=sym, scancode=0, mod=tcod.event.Modifier.NONE, repeat=False)
    )


def put_monster(engine, dx, dy, monster_id):
    import tile_types

    x, y = engine.player.x + dx, engine.player.y + dy
    # 大世界的森林会遮视野：把玩家与目标包围盒清成开阔地，保证测试可见
    for cx in range(min(engine.player.x, x), max(engine.player.x, x) + 1):
        for cy in range(min(engine.player.y, y), max(engine.player.y, y) + 1):
            engine.gamemap.terrain[cx, cy] = tile_types.T_PLAIN
    engine.gamemap.refresh_tile_flags()
    monster = engine.content.build_monster(monster_id, engine.gamemap, x, y)
    engine.gamemap.update_fov(engine.player.x, engine.player.y)
    return monster


# ---- 输入管线 ----


def test_x_opens_examine_and_esc_closes():
    engine = make_engine()
    handler = ih.MainGameEventHandler(engine)
    put_monster(engine, 1, 0, "xingxing")
    action = dispatch_key(handler, KeySym.X)
    assert isinstance(action, ih.OpenExamineAction)

    handler = ih.ExamineEventHandler(engine)
    assert handler.current_target is not None
    action = dispatch_key(handler, KeySym.ESCAPE)
    assert isinstance(action, ih.CloseMenuAction)


def test_x_without_targets_gives_hint():
    engine = make_engine()
    handler = ih.MainGameEventHandler(engine)
    # 清场：把 procgen 生成的怪全部移出视野（挪玩家到已探索空格并强制视野）
    for actor in list(engine.gamemap.actors):
        if actor is not engine.player:
            engine.gamemap.entities.discard(actor)
    engine.update_fov()
    action = dispatch_key(handler, KeySym.X)
    assert action is None  # 不进入模式
    assert any("视野" in m.plain_text for m in engine.message_log.messages)


def test_tab_cycles_targets_and_click_switches():
    engine = make_engine()
    near = put_monster(engine, 1, 0, "xingxing")
    far = put_monster(engine, 3, 0, "gudiao")
    handler = ih.ExamineEventHandler(engine)
    assert handler.current_target is near  # 自动锁最近

    action = dispatch_key(handler, KeySym.TAB)
    assert action is None
    assert handler.current_target is far

    # 鼠标点击近怪切回
    click = tcod.event.MouseButtonDown(
        button=1, position=tcod.event.Point(near.x, near.y)
    )
    assert handler.dispatch(click) is None
    assert handler.current_target is near


def test_examine_costs_no_turn():
    engine = make_engine()
    put_monster(engine, 1, 0, "xingxing")
    handler = ih.ExamineEventHandler(engine)
    x0, y0 = engine.player.x, engine.player.y
    dispatch_key(handler, KeySym.TAB)
    dispatch_key(handler, KeySym.RETURN)  # 回车=关闭
    mp0 = engine.player.fighter.mp
    assert engine.player.x == x0 and engine.player.fighter.mp == mp0


def test_examine_includes_summon():
    engine = make_engine(("yushou", "leifa"))
    player = engine.player
    player.skill_points = 99
    for skill in engine.content.skills_for_class("yushou"):
        try:
            engine.learn_skill(skill["id"])
        except Exception:
            pass
    player.fighter.mp = player.fighter.max_mp
    engine.execute_skill(1)  # 灵犬契约
    beast = next(a for a in engine.gamemap.actors if a.summon_ttl is not None)
    engine.gamemap.update_fov(player.x, player.y)
    handler = ih.ExamineEventHandler(engine)
    assert beast in handler.targets


# ---- 渲染 ----


def card_text(console, engine):
    return "".join(
        "".join(chr(c) for c in console.rgb[:, y]["ch"] if c != 32)
        for y in range(console.height)
    )


def test_examine_card_renders_stats_resist_lore():
    import render

    engine = make_engine()
    zhulong = put_monster(engine, 2, 0, "zhulong")
    handler = ih.ExamineEventHandler(engine)
    console = tcod.console.Console(
        engine.settings.total_cols, engine.settings.total_rows, order="F"
    )
    handler.on_render(console)
    text = card_text(console, engine)
    assert "烛龙" in text
    assert "气血" in text and "攻" in text and "防" in text  # 属性行
    assert "雷抗60%" in text.replace(" ", "") and "火抗60%" in text.replace(" ", "")
    assert "雷" in text and "爪击" in text  # 元素爪击行
    assert "钟山之神" in text  # 山海经典故


def test_examine_card_plain_monster_no_resist_line():
    import render

    engine = make_engine()
    put_monster(engine, 1, 0, "xingxing")
    handler = ih.ExamineEventHandler(engine)
    console = tcod.console.Console(
        engine.settings.total_cols, engine.settings.total_rows, order="F"
    )
    handler.on_render(console)
    text = card_text(console, engine)
    assert "狌狌" in text
    assert "抗性：无" in text.replace(" ", "")
    assert "招摇之山" in text  # lore 仍在
