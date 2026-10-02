"""集成测试：合成键盘事件驱动完整输入管线（按键→动作→引擎→敌回合）。

模拟 main.py 的 handler 切换逻辑，验证真实按键路径下的
战斗 / 拾取 / 行囊 / 使用物品 / 下楼 / 死亡重开。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tcod  # noqa: E402
from tcod.event import KeySym  # noqa: E402

import input_handlers as ih  # noqa: E402
from content_loader import load_content
from settings import Settings  # noqa: E402
from engine import Engine  # noqa: E402


def dispatch_key(handler, sym, shift=False):
    """构造合成 KeyDown 事件并派发，返回动作。"""
    mod = tcod.event.Modifier.SHIFT if shift else tcod.event.Modifier.NONE
    event = tcod.event.KeyDown(sym=sym, scancode=0, mod=mod, repeat=False)
    return handler.dispatch(event)


def apply(handler, action, engine):
    """镜像 main.py 主循环对返回值的处理逻辑。"""
    if action is None:
        return handler
    if isinstance(action, ih.SwitchHandlerAction):
        if isinstance(action, ih.OpenInventoryAction):
            return ih.InventoryEventHandler(engine)
        if isinstance(action, ih.CloseMenuAction):
            return ih.MainGameEventHandler(engine)
        if isinstance(action, ih.RestartAction):
            return None  # 由调用方重建
        return handler
    engine.handle_action(action)
    return handler


def test_full_key_pipeline_combat_pickup_inventory_stairs():
    content = load_content()
    engine = Engine(content, Settings())
    handler = ih.MainGameEventHandler(engine)
    player = engine.player

    # 1) 在玩家左侧放一只狌狌，往左走 = bump 攻击，直到击杀
    monster = content.build_monster("xingxing", engine.gamemap, player.x - 1, player.y)
    for _ in range(60):
        action = dispatch_key(handler, KeySym.H)
        handler = apply(handler, action, engine)
        if not monster.is_alive:
            break
    assert not monster.is_alive, "按 H 攻击应能击杀狌狌"
    joined_log = " ".join(m.plain_text for m in engine.message_log.messages)
    assert "狌狌" in joined_log
    assert player.level.current_xp > 0

    # 2) 脚下放灵芝，按 G 拾取（先清掉 procgen 可能投在同格的随机物品）
    for existing in list(engine.gamemap.items):
        if (existing.x, existing.y) == (monster.x, monster.y):
            engine.gamemap.entities.discard(existing)
    item = content.build_item("lingzhi", engine.gamemap, monster.x, monster.y)
    player.x, player.y = monster.x, monster.y
    action = dispatch_key(handler, KeySym.G)
    handler = apply(handler, action, engine)
    assert item in player.inventory.items

    # 3) 按 I 开行囊（切 handler），按 A 使用灵芝
    player.fighter.hp = player.fighter.max_hp - 8
    hp_before = player.fighter.hp
    action = dispatch_key(handler, KeySym.I)
    handler = apply(handler, action, engine)
    assert isinstance(handler, ih.InventoryEventHandler)
    action = dispatch_key(handler, KeySym.A)
    handler = apply(handler, action, engine)
    assert player.fighter.hp > hp_before
    assert item not in player.inventory.items

    # 4) Esc 关闭行囊回到主模式
    action = dispatch_key(handler, KeySym.ESCAPE)
    handler = apply(handler, action, engine)
    assert isinstance(handler, ih.MainGameEventHandler)

    # 5) 大世界没有山径：按 > 应得到提示而非下楼
    action = dispatch_key(handler, KeySym.GREATER)
    handler = apply(handler, action, engine)
    joined = " ".join(m.plain_text for m in engine.message_log.messages)
    assert "山径" in joined
    assert engine.gamemap is engine.world  # 仍在世界


def test_shift_comma_is_ascend_not_pickup():
    """部分布局/输入法把 Shift+逗号 上报为 逗号+Shift 修饰：应为上楼而非拾取。"""
    from actions import PickupAction, TakeStairsAction

    content = load_content()
    engine = Engine(content, Settings())
    handler = ih.MainGameEventHandler(engine)

    action = dispatch_key(handler, KeySym.COMMA, shift=True)
    assert isinstance(action, TakeStairsAction) and action.direction == "up"

    action = dispatch_key(handler, KeySym.COMMA)
    assert isinstance(action, PickupAction)

    action = dispatch_key(handler, KeySym.PERIOD, shift=True)
    assert isinstance(action, TakeStairsAction) and action.direction == "down"

    action = dispatch_key(handler, KeySym.PERIOD)
    assert type(action).__name__ == "WaitAction"

    action = dispatch_key(handler, KeySym.LESS)
    assert isinstance(action, TakeStairsAction) and action.direction == "up"

    action = dispatch_key(handler, KeySym.GREATER)
    assert isinstance(action, TakeStairsAction) and action.direction == "down"


def test_caps_lock_and_uppercase_tolerance():
    """Caps Lock 场景：字母键码保持小写值（tcod 归一未知值为 UNKNOWN），
    CAPS 修饰不影响绑定；normalize_sym 对大写值做防御性归一。"""
    from actions import BumpAction, PickupAction

    content = load_content()
    engine = Engine(content, Settings())
    handler = ih.MainGameEventHandler(engine)

    caps_event = tcod.event.KeyDown(
        sym=KeySym.H, scancode=0, mod=tcod.event.Modifier.CAPS, repeat=False
    )
    action = handler.dispatch(caps_event)
    assert isinstance(action, BumpAction) and (action.dx, action.dy) == (-1, 0)

    assert ih.normalize_sym(KeySym.G) == int(KeySym.G)
    assert ih.normalize_sym(72) == 104 and ih.normalize_sym(65) == 97  # 防御性大写归一
    assert ih.normalize_sym(KeySym.PERIOD) == int(KeySym.PERIOD)  # 非字母不变

    action = dispatch_key(handler, KeySym.G)
    assert isinstance(action, PickupAction)


def test_brackets_scroll_log_and_space_waits():
    from actions import WaitAction

    content = load_content()
    engine = Engine(content, Settings())
    handler = ih.MainGameEventHandler(engine)

    for i in range(30):
        engine.message_log.add_message(f"消息{i}", "info")
    engine.message_log.scroll(100)
    top_before = engine.message_log.visible_window().start

    action = dispatch_key(handler, KeySym.RIGHTBRACKET)  # ] 回到底部方向
    assert action is None
    assert engine.message_log.visible_window().start > top_before

    engine.message_log.scroll(100)
    action = dispatch_key(handler, KeySym.LEFTBRACKET)  # [ 向上翻
    assert action is None

    action = dispatch_key(handler, KeySym.SPACE)
    assert type(action).__name__ == "WaitAction"

    action = dispatch_key(handler, KeySym.RETURN)
    assert action is None  # 回车在主模式不绑定


def test_player_death_and_restart():
    content = load_content()
    engine = Engine(content, Settings())
    player = engine.player
    handler = ih.MainGameEventHandler(engine)

    # 玩家身边放一只九尾狐并反复互殴直至玩家死亡（不闪避，直接站撸）
    killer = content.build_monster("jiuweihu", engine.gamemap, player.x + 1, player.y)
    killer.fighter.power = 50  # 确保快速致死
    old_level_xp = player.level.current_xp
    for _ in range(80):
        action = dispatch_key(handler, KeySym.PERIOD)  # 原地待命一回合
        handler = apply(handler, action, engine)
        if engine.game_over:
            break
    assert engine.game_over
    assert not player.is_alive
    assert player.level.current_xp >= old_level_xp  # 反杀过也不影响结论

    # 陨落模式：回车 = 重开
    handler = ih.GameOverEventHandler(engine)
    action = dispatch_key(handler, KeySym.RETURN)
    assert isinstance(action, ih.RestartAction)
    engine2 = Engine(content, Settings())
    assert engine2.gamemap is engine2.world  # 新开局出生在大世界
    assert engine2.gamemap.map_type == "world"
    assert engine2.player.is_alive
