"""AI 行为组件。

注册表 AI_TYPES 供 content_loader 分发：数据里写 "ai": {"type": "hostile"}，
新增 AI 行为 = 新类 + 在注册表登记 + 数据引用，机制代码零改动。
"""

from __future__ import annotations

import typing

import numpy as np
import tcod

import exceptions
from actions import MeleeAction, MovementAction
from base_component import BaseComponent

if typing.TYPE_CHECKING:
    from entity import Actor
    from engine import Engine


class BaseAI(BaseComponent):
    def perform(self) -> None:
        raise NotImplementedError()

    @property
    def can_see_player(self) -> bool:
        """FOV 对称：异兽所在格在玩家视野内，即异兽也能看到玩家。"""
        return self.engine.gamemap.visible[self.parent.x, self.parent.y]


class HostileEnemy(BaseAI):
    """视野内 A* 追击，相邻则攻击；看不见则原地待命。"""

    def perform(self) -> None:
        engine: Engine = self.engine
        target: Actor = engine.player
        if not self.can_see_player:
            return  # 未见玩家，不动（将来可在此挂游荡/巡逻行为）

        # 代价数组：可行走为 1，被其他战斗单位占据的格子加高成本避免堵门
        cost = np.array(engine.gamemap.tiles["walkable"], dtype=np.int16)
        for actor in engine.gamemap.actors:
            if cost[actor.x, actor.y]:
                cost[actor.x, actor.y] += 10

        graph = tcod.path.SimpleGraph(cost=cost, cardinal=2, diagonal=3)
        pathfinder = tcod.path.Pathfinder(graph)
        pathfinder.add_root((self.parent.x, self.parent.y))
        path = pathfinder.path_to((target.x, target.y))  # 含起点，首元素是当前位置

        if path is None or len(path) < 2:
            return  # 无路可走，待命
        dest_x, dest_y = int(path[1][0]), int(path[1][1])
        if (dest_x, dest_y) == (target.x, target.y):
            MeleeAction(self.parent, target.x - self.parent.x, target.y - self.parent.y).perform(engine)
            return
        if engine.gamemap.get_actor_at(dest_x, dest_y):
            return  # 前路被同伴占据，等待
        MovementAction(self.parent, dest_x - self.parent.x, dest_y - self.parent.y).perform(engine)


AI_TYPES = {
    "hostile": HostileEnemy,
}
