"""秘境地牢层间移动（上楼梯/层历史）与日志滚动测试。

Engine 默认启动在大世界；这里用 helper 切到秘境式地牢验证层间语义。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import procgen  # noqa: E402
from actions import TakeStairsAction  # noqa: E402
from content_loader import load_content  # noqa: E402
from engine import Engine  # noqa: E402
from message_log import MessageLog  # noqa: E402
from settings import Settings  # noqa: E402


def make_engine() -> Engine:
    engine = Engine(load_content(), Settings())
    # 模拟进入单狐冰窖秘境第 1 层（4 层深，层间移动语义）
    engine.gamemap = procgen.generate_dungeon(
        engine, 7, engine.rng, realm_id="danhu_bingjiao", realm_depth=1
    )
    engine.current_realm = "danhu_bingjiao"
    return engine


def test_descend_then_ascend_roundtrip():
    engine = make_engine()
    floor1 = engine.gamemap
    floor1_map = id(floor1)

    engine.player.x, engine.player.y = floor1.downstairs_xy
    TakeStairsAction(engine.player, "down").perform(engine)
    assert engine.gamemap.realm_depth == 2
    assert id(engine.gamemap) != floor1_map

    engine.player.x, engine.player.y = engine.gamemap.upstairs_xy
    TakeStairsAction(engine.player, "up").perform(engine)
    assert engine.gamemap.realm_depth == 1
    assert id(engine.gamemap) == floor1_map  # 楼层保留：同一张地图对象
    assert (engine.player.x, engine.player.y) == floor1.downstairs_xy  # 落回下行楼梯口


def test_floor_state_persists():
    engine = make_engine()
    monster = engine.content.build_monster("xingxing", engine.gamemap, 2, 2)
    engine.player.fighter.power = 50
    for _ in range(30):
        engine.player.fighter.attack(monster.fighter)
        if not monster.is_alive:
            break
    assert not monster.is_alive
    corpse_name = monster.name

    engine.player.x, engine.player.y = engine.gamemap.downstairs_xy
    TakeStairsAction(engine.player, "down").perform(engine)
    engine.player.x, engine.player.y = engine.gamemap.upstairs_xy
    TakeStairsAction(engine.player, "up").perform(engine)

    assert any(e.name == corpse_name for e in engine.gamemap.entities)  # 尸骸仍在原位


def test_revisit_descended_floor_keeps_map():
    engine = make_engine()
    floor1 = engine.gamemap
    engine.player.x, engine.player.y = floor1.downstairs_xy
    TakeStairsAction(engine.player, "down").perform(engine)
    floor2 = engine.gamemap
    engine.player.x, engine.player.y = floor2.downstairs_xy
    TakeStairsAction(engine.player, "down").perform(engine)  # 下到 3 层
    assert engine.gamemap.realm_depth == 3
    engine.player.x, engine.player.y = engine.gamemap.upstairs_xy
    TakeStairsAction(engine.player, "up").perform(engine)  # 回 2 层（已存在）
    assert id(engine.gamemap) == id(floor2)


def test_ascend_on_floor1_returns_to_world():
    engine = make_engine()
    engine.world_return_xy = engine.world.spawn_xy
    engine.player.x, engine.player.y = engine.gamemap.upstairs_xy
    TakeStairsAction(engine.player, "up").perform(engine)  # 第 1 层上行 = 回世界
    assert engine.gamemap is engine.world
    assert engine.current_realm is None
    assert (engine.player.x, engine.player.y) == engine.world.spawn_xy


def test_wrong_spot_ascend_raises():
    import exceptions

    engine = make_engine()
    engine.player.x, engine.player.y = (1, 1)
    try:
        TakeStairsAction(engine.player, "up").perform(engine)
    except exceptions.Impossible:
        pass
    else:
        raise AssertionError("不在上行楼梯上应提示无法上楼")


def test_log_scroll_and_window():
    log = MessageLog(x=27, width=13, height=10, theme_messages={})
    for i in range(40):
        log.add_message(f"消息{i}", "info")
    assert len(log.messages) == 40  # 完整历史保留
    assert log.messages[-1].plain_text == "消息39"
    win = log.visible_window()
    assert log.messages[win][-1].plain_text == "消息39"  # 默认窗口显示最新

    log.scroll(100)
    win = log.visible_window()
    assert log.messages[win][0].plain_text == "消息0"  # 翻到最旧（offset 夹到 30）
    log.scroll(-5)
    win = log.visible_window()
    assert log.messages[win][-1].plain_text == "消息14"  # 回翻 5 行

    log.add_message("新消息", "info")
    assert log.scroll_offset == 0  # 新消息回到底部


def test_handle_action_resets_scroll():
    from actions import WaitAction

    engine = make_engine()
    log = engine.message_log
    for i in range(30):
        log.add_message(f"消息{i}", "info")
    log.scroll(10)
    assert log.scroll_offset > 0
    engine.handle_action(WaitAction())
    assert log.scroll_offset == 0
