"""输入处理：把 tcod 键盘/鼠标事件翻译成动作（或菜单操作）。

EventHandler 子类即"输入模式"：主模式、行囊、技能参悟（K）、瞄准（单体
技能）、择向（位移技能）、陨落模式、开局职业选择。返回值两种：
actions.Action（交给引擎执行）；SwitchHandlerAction 标记（由主循环切换
输入模式 / 重开局），后者不是真正的回合动作。需目标的技能经引擎抛出
NeedTarget，主循环接管切换到瞄准/择向模式。
"""

from __future__ import annotations

from typing import List, Optional

import tcod
from tcod.event import KeySym

import actions
from equipment import SLOT_ORDER

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
    # vi 键（八方向；K 已让位给技能参悟界面，上移请用方向键/W）
    KeySym.H: (-1, 0),
    KeySym.J: (0, 1),
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
SKILL_LEARN_KEY = KeySym.K  # vi 的 K 让位：上移用方向键/W
EXAMINE_KEY = KeySym.X  # 查看视野内怪物属性
WORLD_MAP_KEY = KeySym.M  # 山海图卷（大世界地图）
TAB_KEY = KeySym.TAB
EQUIP_KEY = KeySym.E

SCROLL_UP_KEYS = {KeySym.LEFTBRACKET}
SCROLL_DOWN_KEYS = {KeySym.RIGHTBRACKET}

# 技能热键：主键排数字 1-8（小键盘数字仍用于移动）
SLOT_KEYS = [
    KeySym.N1,
    KeySym.N2,
    KeySym.N3,
    KeySym.N4,
    KeySym.N5,
    KeySym.N6,
    KeySym.N7,
    KeySym.N8,
]

# 装备槽卸下键：1-5 对应 兵/甲/履/佩/冠（行囊界面内）
UNEQUIP_KEYS = SLOT_KEYS[: len(SLOT_ORDER)]


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


class OpenSkillLearnAction(SwitchHandlerAction):
    pass


class OpenExamineAction(SwitchHandlerAction):
    pass


class OpenWorldMapAction(SwitchHandlerAction):
    pass


class RestartAction(SwitchHandlerAction):
    """重开局：回到职业选择界面（由主循环解释）。"""


class LoadGameAction(SwitchHandlerAction):
    """读档：从存档重建引擎（由主循环解释）。"""


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

        if engine.traveling is not None:
            engine.traveling = None  # 任意按键打断旅行（本键仍正常生效）

        if key in MOVE_KEYS and player.is_alive:
            dx, dy = MOVE_KEYS[key]
            if shift_held and engine.gamemap.map_type == "world":
                # 大世界旅行：Shift+方向 连续行走直到遇事（不耗回合，步进由主循环驱动）
                engine.traveling = (dx, dy)
                return None
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
        if player.is_alive and key in SLOT_KEYS:
            return actions.CastSkillAction(player, SLOT_KEYS.index(key) + 1)  # 键 N → 槽 N
        if player.is_alive and key == TAB_KEY:
            engine.active_page = 1 - engine.active_page  # 视图操作，不耗回合
            return None
        if player.is_alive and key == SKILL_LEARN_KEY:
            return OpenSkillLearnAction()
        if player.is_alive and key == EXAMINE_KEY:
            if _visible_examine_targets(engine):
                return OpenExamineAction()
            engine.message_log.add_message(engine.content.strings["examine_none"], "info")
            return None
        if key == WORLD_MAP_KEY:
            return OpenWorldMapAction()
        if key in SCROLL_UP_KEYS and player.is_alive:
            engine.message_log.scroll(3)
            return None
        if key in SCROLL_DOWN_KEYS and player.is_alive:
            engine.message_log.scroll(-3)
            return None
        if key == INVENTORY_TOGGLE_KEY and player.is_alive:
            return OpenInventoryAction()
        if key == KeySym.ESCAPE:
            return actions.EscapeAction()
        if key == KeySym.F1:
            return ChangeSizeAction("map")
        if key == KeySym.F2:
            return ChangeSizeAction("sidebar")
        if key == KeySym.F5 and player.is_alive:
            import save_manager

            save_manager.save_game(engine)
            engine.message_log.add_message(engine.content.strings["save_ok"], "system")
            return None
        if key == KeySym.F9:
            import save_manager

            if save_manager.save_exists():
                return LoadGameAction()
            engine.message_log.add_message(engine.content.strings["save_none"], "warn")
            return None
        return None


class InventoryEventHandler(EventHandler):
    """行囊：字母=使用消耗品/装备装备件；↑↓+E=光标装备/卸下；1-5=卸下对应槽。"""

    def __init__(self, engine) -> None:
        super().__init__(engine)
        self.cursor = 0  # 统一列表：前行囊物品，后 5 个装备槽

    def _row_count(self) -> int:
        return len(self.engine.player.inventory.items) + len(SLOT_ORDER)

    def on_render(self, console) -> None:
        super().on_render(console)
        import render

        render.render_inventory_menu(console, self.engine, cursor=self.cursor)

    def ev_keydown(self, event: tcod.event.KeyDown):
        engine = self.engine
        key = normalize_sym(event.sym)
        if key == KeySym.ESCAPE or key == INVENTORY_TOGGLE_KEY:
            return CloseMenuAction()
        items = list(engine.player.inventory.items)
        # E 优先于字母选择（字母表中不再用 e 选第 5 件）
        if key == EQUIP_KEY:
            return self._cursor_equip()
        if key == KeySym.UP:
            self.cursor = max(0, self.cursor - 1)
            return None
        if key == KeySym.DOWN:
            self.cursor = min(self._row_count() - 1, self.cursor + 1)
            return None
        if key in CONFIRM_KEYS:
            if self.cursor < len(items):
                return self._use_or_equip(items[self.cursor])
            return None
        if key in INVENTORY_LETTER_KEYS:
            index = INVENTORY_LETTER_KEYS.index(key)
            if index < len(items):
                return self._use_or_equip(items[index])
            return None
        if key in UNEQUIP_KEYS:
            slot = SLOT_ORDER[UNEQUIP_KEYS.index(key)]
            if engine.player.equipment.slots.get(slot) is not None:
                return actions.UnequipAction(engine.player, slot)
            return None
        return None

    def _use_or_equip(self, item):
        if item.equipment is not None:
            return actions.EquipAction(self.engine.player, item)
        if item.consumable is not None:
            return actions.ItemAction(self.engine.player, item)
        return None

    def _cursor_equip(self):
        engine = self.engine
        items = list(engine.player.inventory.items)
        if self.cursor < len(items):
            item = items[self.cursor]
            if item.equipment is not None:
                return actions.EquipAction(engine.player, item)
            return None
        slot = SLOT_ORDER[self.cursor - len(items)]
        if engine.player.equipment.slots.get(slot) is not None:
            return actions.UnequipAction(engine.player, slot)
        return None


def items_is_empty_guard(engine, key) -> bool:  # pragma: no cover - 兼容占位
    return False


class SkillLearnEventHandler(EventHandler):
    """参悟界面（K）：Tab 换职业页，↑↓ 选择，回车 学习，Esc 关闭。均不耗回合。"""

    def __init__(self, engine) -> None:
        super().__init__(engine)
        self.page = engine.active_page
        self.cursor = 0

    def _skills(self) -> List[dict]:
        class_id = self.engine.player.class_ids[self.page]
        return self.engine.content.skills_for_class(class_id)

    def on_render(self, console) -> None:
        super().on_render(console)
        import render

        render.render_skill_learn_menu(console, self.engine, page=self.page, cursor=self.cursor)

    def ev_keydown(self, event: tcod.event.KeyDown):
        engine = self.engine
        key = normalize_sym(event.sym)
        if key == KeySym.ESCAPE or key == SKILL_LEARN_KEY:
            return CloseMenuAction()
        if key == TAB_KEY:
            self.page = 1 - self.page
            engine.active_page = self.page
            self.cursor = 0
            return None
        if key == KeySym.UP:
            self.cursor = max(0, self.cursor - 1)
            return None
        if key == KeySym.DOWN:
            self.cursor = min(len(self._skills()) - 1, self.cursor + 1)
            return None
        if key in CONFIRM_KEYS:
            skill = self._skills()[self.cursor]
            try:
                engine.learn_skill(skill["id"])
            except Exception as exc:  # noqa: BLE001 —— Impossible 转提示
                engine.message_log.add_message(str(exc), "warn")
            return None
        return None


class TargetingEventHandler(EventHandler):
    """瞄准模式：单体技能指定目标。Tab 循环 / 鼠标点击 / 回车确认 / Esc 取消。"""

    def __init__(self, engine, skill: dict, slot: int) -> None:
        super().__init__(engine)
        self.skill = skill
        self.slot = slot
        self.targets: List = skills_visible_enemies(engine)
        self.index = 0

    def on_render(self, console) -> None:
        super().on_render(console)
        import render

        target = self.current_target
        if target is not None:
            render.render_targeting_overlay(console, self.engine, target, self.skill)

    @property
    def current_target(self):
        if not self.targets:
            return None
        self.targets = [t for t in self.targets if t.is_alive]
        if not self.targets:
            return None
        return self.targets[self.index % len(self.targets)]

    def ev_keydown(self, event: tcod.event.KeyDown):
        engine = self.engine
        key = normalize_sym(event.sym)
        if key == KeySym.ESCAPE:
            return CloseMenuAction()  # 取消：不耗真气不耗回合
        if key == TAB_KEY:
            if self.targets:
                self.index = (self.index + 1) % len(self.targets)
            return None
        if key in CONFIRM_KEYS:
            target = self.current_target
            if target is None:
                return CloseMenuAction()
            return actions.CastSkillAction(engine.player, self.slot, target=target)
        return None

    def ev_mousebuttondown(self, event: tcod.event.MouseButtonDown):
        # tcod 21：经 context.convert_event 后 position 即格坐标（tile 属性已废弃）
        # position 为视口屏幕坐标，需按摄像机偏移换算回地图坐标
        if event.button == 1 and event.position is not None:
            from render import viewport_offset

            off_x, off_y = viewport_offset(self.engine)
            tx, ty = int(event.position[0]) - off_x, int(event.position[1]) - off_y
            for i, actor in enumerate(self.targets):
                if actor.is_alive and (actor.x, actor.y) == (tx, ty):
                    self.index = i
                    return actions.CastSkillAction(
                        self.engine.player, self.slot, target=actor
                    )
        return None


def skills_visible_enemies(engine) -> List:
    import skills as skills_module

    return skills_module.visible_enemies(engine, engine.player)


def _visible_examine_targets(engine) -> List:
    """视野内可查看的 actor（除玩家；含敌对与契约兽），按距离排序。"""
    gamemap = engine.gamemap
    targets = [
        actor
        for actor in gamemap.actors
        if actor is not engine.player and gamemap.visible[actor.x, actor.y]
    ]
    targets.sort(key=engine.player.distance_to)
    return targets


class ExamineEventHandler(EventHandler):
    """查看模式：视野内怪物/契约兽属性卡。Tab 循环 / 鼠标点击 / Esc 或 X 关闭，不耗回合。"""

    def __init__(self, engine) -> None:
        super().__init__(engine)
        self.targets: List = _visible_examine_targets(engine)
        self.index = 0

    @property
    def current_target(self):
        if not self.targets:
            return None
        self.targets = [t for t in self.targets if t.is_alive]
        if not self.targets:
            return None
        return self.targets[self.index % len(self.targets)]

    def on_render(self, console) -> None:
        super().on_render(console)
        import render

        target = self.current_target
        if target is not None:
            render.render_examine_card(console, self.engine, target)

    def ev_keydown(self, event: tcod.event.KeyDown):
        key = normalize_sym(event.sym)
        if key == KeySym.ESCAPE or key == EXAMINE_KEY or key in CONFIRM_KEYS:
            return CloseMenuAction()
        if key == TAB_KEY:
            if self.targets:
                self.index = (self.index + 1) % len(self.targets)
            return None
        return None

    def ev_mousebuttondown(self, event: tcod.event.MouseButtonDown):
        # tcod 21：经 context.convert_event 后 position 即格坐标（tile 属性已废弃）
        # position 为视口屏幕坐标，需按摄像机偏移换算回地图坐标
        if event.button == 1 and event.position is not None:
            from render import viewport_offset

            off_x, off_y = viewport_offset(self.engine)
            tx, ty = int(event.position[0]) - off_x, int(event.position[1]) - off_y
            for i, actor in enumerate(self.targets):
                if actor.is_alive and (actor.x, actor.y) == (tx, ty):
                    self.index = i  # 点击即切换查看对象，不关闭
                    return None
        return None


class DirectionSelectEventHandler(EventHandler):
    """择向模式：位移技能选八向落点。方向键选择 / 回车确认 / Esc 取消。"""

    def __init__(self, engine, skill: dict, slot: int) -> None:
        super().__init__(engine)
        self.skill = skill
        self.slot = slot
        self.dx, self.dy = 1, 0

    def on_render(self, console) -> None:
        super().on_render(console)
        import render

        render.render_direction_overlay(console, self.engine, self.skill, self.dx, self.dy)

    def ev_keydown(self, event: tcod.event.KeyDown):
        engine = self.engine
        key = normalize_sym(event.sym)
        if key == KeySym.ESCAPE:
            return CloseMenuAction()
        if key in MOVE_KEYS:
            self.dx, self.dy = MOVE_KEYS[key]
            return None
        if key in CONFIRM_KEYS:
            return actions.CastSkillAction(
                engine.player, self.slot, target=(self.dx, self.dy)
            )
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


class WorldMapEventHandler(EventHandler):
    """山海图卷（M）：世界探索全图。M/Esc/回车关闭，不消耗回合。"""

    def on_render(self, console) -> None:
        super().on_render(console)
        import render

        render.render_world_map_overlay(console, self.engine)

    def ev_keydown(self, event: tcod.event.KeyDown):
        key = normalize_sym(event.sym)
        if key in (KeySym.ESCAPE, WORLD_MAP_KEY) or key in CONFIRM_KEYS:
            return CloseMenuAction()
        return None


CONTINUE_ID = "§continue§"  # 职业选择列表顶部的"继续游历"占位项


class ClassSelectEventHandler(tcod.event.EventDispatch):
    """开局双职业选择：两段（主→副）。不持有 engine——选择完成后 chosen 非 None。

    has_save 时列表顶部多一项"继续游历（读档）"。
    """

    def __init__(self, content, settings, has_save: bool = False) -> None:
        self.content = content
        self.settings = settings
        self.has_save = has_save
        self.class_ids: List[str] = list(content.classes.keys())
        self.primary: Optional[str] = None
        self.cursor = 0
        self.chosen: Optional[tuple] = None  # (主, 副) 就绪后由主循环取用
        self.continue_requested = False  # 顶部"继续游历"被选中
        self.done = False

    def _options(self) -> List[str]:
        return ([CONTINUE_ID] if self.has_save else []) + self.class_ids

    def on_render(self, console) -> None:
        import render

        render.render_class_select(console, self.content, self.settings, primary=self.primary,
                                   cursor=self.cursor, has_save=self.has_save)

    def ev_quit(self, event: tcod.event.Quit):
        raise SystemExit()

    def ev_keydown(self, event: tcod.event.KeyDown):
        key = normalize_sym(event.sym)
        if self.primary is None:
            options = self._options()
            if key == KeySym.UP:
                self.cursor = (self.cursor - 1) % len(options)
                return None
            if key == KeySym.DOWN:
                self.cursor = (self.cursor + 1) % len(options)
                return None
            if key in CONFIRM_KEYS:
                picked = options[self.cursor % len(options)]
                if picked == CONTINUE_ID:
                    self.continue_requested = True
                    self.done = True
                    return None
                self.primary = picked
                self.cursor = 0
                return None
            if key == KeySym.ESCAPE:
                raise SystemExit()
        else:
            remaining = [c for c in self.class_ids if c != self.primary]
            if key == KeySym.UP:
                self.cursor = (self.cursor - 1) % len(remaining)
                return None
            if key == KeySym.DOWN:
                self.cursor = (self.cursor + 1) % len(remaining)
                return None
            if key in CONFIRM_KEYS:
                secondary = remaining[self.cursor % len(remaining)]
                self.chosen = (self.primary, secondary)
                self.done = True
                return None
            if key == KeySym.ESCAPE:
                self.primary = None  # 回到主职业选择
                self.cursor = 0
                return None
        return None
