"""引擎：持有玩家、地图、消息日志与特效；驱动回合推进与楼层切换。"""

from __future__ import annotations

import random

import exceptions
import procgen
from effects import Effects
from game_map import GameMap
from message_log import MessageLog


class Engine:
    def __init__(self, content, settings) -> None:
        self.content = content
        self.settings = settings
        self.message_log = MessageLog(
            x=settings.content_x,
            width=settings.content_w,
            height=settings.log_height,
            theme_messages=content.theme["messages"],
        )
        self.effects = Effects(content.theme["effects"])
        self.rng = random.Random()
        self.game_over = False
        self.floors: dict = {}  # 楼层历史：floor_number -> GameMap，支持上行返回

        # 玩家实体在第 1 层生成时创建一次，此后跨层复用（保留状态）
        self.player = None  # type: ignore[assignment]
        self.gamemap: GameMap = GameMap(self, settings.map_cols, settings.map_rows, floor_number=1)
        self.player = content.build_player(self.gamemap, 0, 0)
        self.gamemap = procgen.generate_dungeon(
            self, floor_number=1, rng=self.rng, width=settings.map_cols, height=settings.map_rows
        )
        self.update_fov()
        self.message_log.add_message(content.strings["welcome"], "system")

    def handle_action(self, action) -> None:
        """执行玩家动作：成功则敌人行动并刷新视野；失败则提示原因。"""
        self.message_log.scroll_offset = 0  # 采取行动即回到日志底部
        try:
            action.perform(self)
        except exceptions.Impossible as exc:
            self.message_log.add_message(str(exc), "warn")
            return  # 非法动作不消耗回合
        if not self.game_over:
            self.handle_enemy_turns()
            self.update_fov()

    def handle_enemy_turns(self) -> None:
        for actor in self.gamemap.actors:
            if actor is self.player or not actor.is_alive or actor.ai is None:
                continue
            if self.game_over:
                return
            try:
                actor.ai.perform()
            except exceptions.Impossible:
                pass  # 敌人的非法行动静默跳过

    def update_fov(self) -> None:
        self.gamemap.update_fov(self.player.x, self.player.y)

    def next_floor(self) -> None:
        self.floors[self.gamemap.floor_number] = self.gamemap
        next_number = self.gamemap.floor_number + 1
        if next_number in self.floors:
            self.gamemap = self.floors[next_number]
            self.player.place(self.gamemap, *self.gamemap.upstairs_xy)
        else:
            self.gamemap = procgen.generate_dungeon(
                self,
                next_number,
                self.rng,
                width=self.settings.map_cols,
                height=self.settings.map_rows,
            )
        self.effects.clear()
        self.update_fov()

    def previous_floor(self) -> None:
        if self.gamemap.floor_number <= 1:
            return
        above = self.floors.get(self.gamemap.floor_number - 1)
        if above is None:
            # 楼层历史已清空（如改过显示设置），来路不存在——给提示而非崩溃
            raise exceptions.Impossible(self.content.strings["no_floor_above"])
        self.floors[self.gamemap.floor_number] = self.gamemap
        self.gamemap = above
        self.player.place(self.gamemap, *self.gamemap.downstairs_xy)
        self.effects.clear()
        self.update_fov()

    def apply_layout(self) -> None:
        """显示设置变更后应用新几何：日志参数更新并按当前层数重生成地牢。"""
        log = self.message_log
        log.x = self.settings.content_x
        log.width = self.settings.content_w
        log.height = self.settings.log_height
        log.scroll_offset = 0
        self.floors.clear()
        self.gamemap = procgen.generate_dungeon(
            self,
            self.gamemap.floor_number,
            self.rng,
            width=self.settings.map_cols,
            height=self.settings.map_rows,
        )
        self.update_fov()
