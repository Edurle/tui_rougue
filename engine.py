"""引擎：持有玩家、地图、消息日志；驱动回合推进与楼层切换。"""

from __future__ import annotations

import random

import exceptions
import procgen
from game_map import GameMap
from message_log import MessageLog


class Engine:
    def __init__(self, content) -> None:
        self.content = content
        self.message_log = MessageLog(x=0, width=80, height=2)
        self.rng = random.Random()
        self.game_over = False

        # 玩家实体在第 1 层生成时创建一次，此后跨层复用（保留状态）
        self.player = None  # type: ignore[assignment]
        self.gamemap: GameMap = GameMap(self, procgen.MAP_WIDTH, procgen.MAP_HEIGHT, floor_number=1)
        self.player = content.build_player(self.gamemap, 0, 0)
        self.gamemap = procgen.generate_dungeon(self, floor_number=1, rng=self.rng)
        self.update_fov()
        self.message_log.add_message(content.strings["welcome"], (210, 200, 160))

    def handle_action(self, action) -> None:
        """执行玩家动作：成功则敌人行动并刷新视野；失败则提示原因。"""
        try:
            action.perform(self)
        except exceptions.Impossible as exc:
            self.message_log.add_message(str(exc), (220, 160, 160))
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
        self.gamemap = procgen.generate_dungeon(self, self.gamemap.floor_number + 1, self.rng)
        self.update_fov()
