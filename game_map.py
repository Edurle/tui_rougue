"""游戏地图：瓦片网格、视野（FOV）、实体容器与查询。"""

from __future__ import annotations

from typing import Optional, Set, Tuple

import numpy as np
import tcod
from tcod import libtcodpy

import tile_types
from entity import Actor, Entity, Item


class GameMap:
    def __init__(self, engine: "Entity", width: int, height: int, floor_number: int = 1) -> None:
        from engine import Engine  # 运行时导入避免循环依赖

        self.engine: Engine = engine  # type: ignore[assignment]
        self.width = width
        self.height = height
        self.floor_number = floor_number
        self.entities: Set[Entity] = set()
        self.downstairs_xy: Tuple[int, int] = (0, 0)

        # order="F" 保证 [x, y] 索引与 tcod FOV 接口一致
        self.tiles = np.zeros((width, height), dtype=tile_types.tile_dtype, order="F")
        self.tiles[...] = tile_types.WALL

        self.explored = np.zeros((width, height), dtype=np.bool_, order="F")
        self.visible = np.zeros((width, height), dtype=np.bool_, order="F")

    # ---- 实体查询 ----

    @property
    def actors(self) -> list:
        return [e for e in self.entities if isinstance(e, Actor) and e.is_alive]

    @property
    def items(self) -> list:
        return [e for e in self.entities if isinstance(e, Item) and e.consumable is not None]

    def get_blocking_entity_at(self, x: int, y: int) -> Optional[Entity]:
        for entity in self.entities:
            if entity.blocks_movement and entity.x == x and entity.y == y:
                return entity
        return None

    def get_actor_at(self, x: int, y: int) -> Optional[Actor]:
        for actor in self.actors:
            if actor.x == x and actor.y == y:
                return actor
        return None

    def get_item_at(self, x: int, y: int) -> Optional[Item]:
        for item in self.items:
            if item.x == x and item.y == y:
                return item
        return None

    # ---- 地图几何 ----

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    # ---- 视野 ----

    def update_fov(self, pov_x: int, pov_y: int, radius: int = 8) -> None:
        """对称阴影 FOV；走过之处保留 explored 记忆。"""
        self.visible = tcod.map.compute_fov(
            self.tiles["transparent"],
            (pov_x, pov_y),
            radius=radius,
            algorithm=libtcodpy.FOV_SYMMETRIC_SHADOWCAST,
        )
        self.explored |= self.visible
