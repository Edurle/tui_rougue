"""输入处理：把 tcod 键盘事件翻译成动作（或菜单操作）。

EventHandler 子类即"输入模式"：主模式、行囊模式、陨落模式。
返回值两种：actions.Action（交给引擎执行）；SwitchHandlerAction 标记
（由主循环切换输入模式 / 重开局），后者不是真正的回合动作。
"""

from __future__ import annotations

from typing import Optional

import tcod
from tcod.event import KeySym

import actions

MOVE_KEYS = {
    # 方向键
    KeySym.UP: (0, -1),
    KeySym.DOWN: (0, 1),
    KeySym.LEFT: (-1, 0),
    KeySym.RIGHT: (1, 0),
    KeySym.HOME: (-1, -1),
    KeySym.END: (-1, 1),
    KeySym.PAGEUP: (1, -1),
    KeySym.PAGEDOWN: (1, 1),
    # vi 键（八方向）
    KeySym.H: (-1, 0),
    KeySym.J: (0, 1),
    KeySym.K: (0, -1),
    KeySym.L: (1, 0),
    KeySym.Y: (-1, -1),
    KeySym.U: (1, -1),
    KeySym.B: (-1, 1),
    KeySym.N: (1, 1),
    # WASD
    KeySym.W: (0, -1),
    KeySym.A: (-1, 0),
    KeySym.S: (0, 1),
    KeySym.D: (1, 0),
    # 小键盘
    KeySym.KP_1: (-1, 1),
    KeySym.KP_2: (0, 1),
    KeySym.KP_3: (1, 1),
    KeySym.KP_4: (-1, 0),
    KeySym.KP_6: (1, 0),
    KeySym.KP_7: (-1, -1),
    KeySym.KP_8: (0, -1),
    KeySym.KP_9: (1, -1),
}

WAIT_KEYS = {
    KeySym.PERIOD,
    KeySym.SPACE,
    KeySym.KP_5,
}

CONFIRM_KEYS = {
    KeySym.RETURN,
    KeySym.KP_ENTER,
}

INVENTORY_TOGGLE_KEY = KeySym.I
PICKUP_KEYS = {KeySym.G, KeySym.COMMA}
DESCEND_KEY = KeySym.GREATER  # Shift + 句号
ASCEND_KEY = KeySym.LESS  # Shift + 逗号

SCROLL_UP_KEYS = {KeySym.LEFTBRACKET}
SCROLL_DOWN_KEYS = {KeySym.RIGHTBRACKET}


def normalize_sym(sym) -> int:
    """字母键码统一为小写：Caps Lock / 部分布局会上报大写键码（65-90）。"""
    value = int(sym)
    if 65 <= value <= 90:
        return value + 32
    return value

INVENTORY_LETTER_KEYS = (
    KeySym.A,
    KeySym.B,
    KeySym.C,
    KeySym.D,
    KeySym.E,
    KeySym.F,
    KeySym.G,
    KeySym.H,
    KeySym.I,
    KeySym.J,
)


class SwitchHandlerAction:
    """输入模式切换标记，不消耗回合。由主循环解释执行。"""


class OpenInventoryAction(SwitchHandlerAction):
    pass


class CloseMenuAction(SwitchHandlerAction):
    pass


class RestartAction(SwitchHandlerAction):
    pass


class ChangeSizeAction:
    """显示设置切换标记（kind: map / sidebar），不消耗回合。由主循环重建窗口。"""

    def __init__(self, kind: str) -> None:
        self.kind = kind


class EventHandler(tcod.event.EventDispatch):
    """基类：持有引擎，渲染主画面；子类可叠加覆盖层与各自按键表。"""

    def __init__(self, engine) -> None:
        self.engine = engine

    def on_render(self, console) -> None:
        import render

        render.render_all(console, self.engine)

    def ev_quit(self, event: tcod.event.Quit) -> Optional[actions.Action]:
        raise SystemExit()

    def ev_pixelsizechanged(self, event) -> None:
        """窗口尺寸变化时保持安静（tcod 会自动缩放点阵画面）。"""


class LogScrollMixin:
    """主模式可用的日志回看：鼠标滚轮滚动事件日志（视图操作，不消耗回合）。"""

    def ev_mousewheel(self, event: tcod.event.MouseWheel):
        if event.y:
            self.engine.message_log.scroll(int(event.y))
        return None


class MainGameEventHandler(LogScrollMixin, EventHandler):
    def ev_keydown(self, event: tcod.event.KeyDown):
        engine = self.engine
        player = engine.player

        key = normalize_sym(event.sym)
        shift_held = bool(event.mod & tcod.event.Modifier.SHIFT)

        if key in MOVE_KEYS and player.is_alive:
            dx, dy = MOVE_KEYS[key]
            return actions.BumpAction(player, dx, dy)
        # 部分布局/输入法下 Shift+句号/逗号 上报为 基础键+Shift 修饰而非 >/< 键位，
        # 因此带 Shift 的句号/逗号一律解释为下楼/上楼，且先于等待/拾取判定。
        if player.is_alive and shift_held and (key == KeySym.PERIOD or key == DESCEND_KEY):
            return actions.TakeStairsAction(player, "down")
        if player.is_alive and shift_held and (key == KeySym.COMMA or key == ASCEND_KEY):
            return actions.TakeStairsAction(player, "up")
        if key in WAIT_KEYS and player.is_alive:
            return actions.WaitAction()
        if key in PICKUP_KEYS and player.is_alive:
            return actions.PickupAction(player)
        if key == DESCEND_KEY and player.is_alive:
            return actions.TakeStairsAction(player, "down")
        if key == ASCEND_KEY and player.is_alive:
            return actions.TakeStairsAction(player, "up")
        if key in SCROLL_UP_KEYS and player.is_alive:
            engine.message_log.scroll(3)
            return None
        if key in SCROLL_DOWN_KEYS and player.is_alive:
            engine.message_log.scroll(-3)
            return None
        if key == INVENTORY_TOGGLE_KEY and player.is_alive:
            if player.inventory.items:
                return OpenInventoryAction()
            engine.message_log.add_message(engine.content.strings["inventory_empty"], "info")
            return None
        if key == KeySym.ESCAPE:
            return actions.EscapeAction()
        if key == KeySym.F1:
            return ChangeSizeAction("map")
        if key == KeySym.F2:
            return ChangeSizeAction("sidebar")
        return None


class InventoryEventHandler(EventHandler):
    def on_render(self, console) -> None:
        super().on_render(console)
        import render

        render.render_inventory_menu(console, self.engine)

    def ev_keydown(self, event: tcod.event.KeyDown):
        engine = self.engine
        key = normalize_sym(event.sym)
        if key == KeySym.ESCAPE or key == INVENTORY_TOGGLE_KEY:
            return CloseMenuAction()
        if key in INVENTORY_LETTER_KEYS:
            index = INVENTORY_LETTER_KEYS.index(key)
            items = list(engine.player.inventory.items)
            if index < len(items):
                return actions.ItemAction(engine.player, items[index])
        return None


class GameOverEventHandler(EventHandler):
    def on_render(self, console) -> None:
        super().on_render(console)
        import render

        render.render_game_over(console, self.engine)

    def ev_keydown(self, event: tcod.event.KeyDown):
        key = event.sym
        if key in CONFIRM_KEYS:
            return RestartAction()
        if key == KeySym.ESCAPE:
            return actions.EscapeAction()
        return None
