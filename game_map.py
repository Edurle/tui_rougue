"""游戏地图：地形网格、视野（FOV）、邻接墙字符、实体容器与查询。

地图尺寸与屏幕视口解耦：世界地图远大于视口（渲染层做摄像机滚动），
秘境地牢固定尺寸。terrain 数组存地形 id（见 tile_types），walkable/
transparent 是其派生缓存，改动地形后须调 refresh_tile_flags()。
"""

from __future__ import annotations

from typing import Optional, Set, Tuple

import numpy as np
import tcod
from tcod import libtcodpy

import tile_types
from entity import Actor, Entity, Item
from tileset_art import WALL_GLYPHS

FOV_RADIUS = 8  # 默认视野半径（秘境）；世界地图在生成时另行设置

# 邻接墙字符：索引 = 上*1 + 下*2 + 左*4 + 右*8（邻居为墙记 1，边界外视为墙）
_WALL_CODEPOINTS = np.array([ord(c) for c in WALL_GLYPHS], dtype=np.int32)


class GameMap:
    def __init__(
        self,
        engine: "Engine",
        width: int,
        height: int,
        floor_number: int = 1,
        map_type: str = "realm",
        realm_id: Optional[str] = None,
        realm_depth: int = 1,
        default_terrain: int = tile_types.T_WALL,
    ) -> None:
        from engine import Engine

        self.engine: Engine = engine  # type: ignore[assignment]
        self.width = width
        self.height = height
        self.floor_number = floor_number
        # "world" = 大世界常驻地图；"realm" = 秘境地牢（realm_id/realm_depth 标识）
        self.map_type = map_type
        self.realm_id = realm_id
        self.realm_depth = realm_depth
        self.fov_radius = FOV_RADIUS
        self.entities: Set[Entity] = set()
        self.downstairs_xy: Tuple[int, int] = (-1, -1)
        self.upstairs_xy: Tuple[int, int] = (-1, -1)

        # 世界地图专用：区域索引网格（regions.json 顺序）、名山地标、出生点
        self.region_ids: Optional["np.ndarray"] = None
        self.landmarks: list = []
        self.spawn_xy: Tuple[int, int] = (0, 0)

        # order="F" 保证 [x, y] 索引与 tcod FOV 接口一致
        self.terrain = np.full((width, height), default_terrain, dtype=np.uint8, order="F")
        self.tiles = np.zeros((width, height), dtype=tile_types.tile_dtype, order="F")
        self.refresh_tile_flags()

        self.explored = np.zeros((width, height), dtype=np.bool_, order="F")
        self.visible = np.zeros((width, height), dtype=np.bool_, order="F")
        self.wall_glyphs = np.zeros((width, height), dtype=np.int32, order="F")
        self.rebuild_wall_glyphs()

    # ---- 实体查询 ----

    @property
    def actors(self) -> list:
        return [e for e in self.entities if isinstance(e, Actor) and e.is_alive]

    @property
    def items(self) -> list:
        return [
            e
            for e in self.entities
            if isinstance(e, Item) and (e.consumable is not None or e.equipment is not None)
        ]

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

    def nearest_landmark(self, x: int, y: int, max_dist: float = 30.0) -> Optional[dict]:
        """最近的名山地标（曼哈顿距离，超出 max_dist 返回 None）。"""
        best = None
        best_d = max_dist
        for lm in self.landmarks:
            d = abs(lm["x"] - x) + abs(lm["y"] - y)
            if d < best_d:
                best_d = d
                best = lm
        return best

    def refresh_tile_flags(self) -> None:
        """按 terrain 重建 walkable/transparent 派生缓存（地形改动后调用）。"""
        self.tiles["walkable"] = tile_types.WALKABLE_LUT[self.terrain]
        self.tiles["transparent"] = tile_types.TRANSPARENT_LUT[self.terrain]

    def rebuild_wall_glyphs(self) -> None:
        """按四邻居是否石壁（T_WALL）计算每格墙字符，生成/挖掘后调用。

        仅秘境石壁参与线框连接；世界地形（山/水/渊）各有独立字形。
        """
        walls = self.terrain == tile_types.T_WALL
        w, h = walls.shape
        ones_col = np.ones((w, 1), dtype=bool)
        ones_row = np.ones((1, h), dtype=bool)
        up = np.concatenate([ones_col, walls[:, :-1]], axis=1)
        down = np.concatenate([walls[:, 1:], ones_col], axis=1)
        left = np.concatenate([ones_row, walls[:-1, :]], axis=0)
        right = np.concatenate([walls[1:, :], ones_row], axis=0)
        bitmask = up * 1 + down * 2 + left * 4 + right * 8
        self.wall_glyphs = _WALL_CODEPOINTS[bitmask]

    # ---- 视野 ----

    def update_fov(self, pov_x: int, pov_y: int, radius: Optional[int] = None) -> None:
        """对称阴影 FOV；走过之处保留 explored 记忆。"""
        self.visible = tcod.map.compute_fov(
            self.tiles["transparent"],
            (pov_x, pov_y),
            radius=self.fov_radius if radius is None else radius,
            algorithm=libtcodpy.FOV_SYMMETRIC_SHADOWCAST,
        )
        self.explored |= self.visible

    def lighting_factors(self, pov_x: int, pov_y: int, inner_radius: float, edge_falloff: float) -> np.ndarray:
        """每格亮度因子 (W,H)：inner 内全亮，至 FOV 边缘线性降到 (1-edge_falloff)。"""
        xs = np.arange(self.width, dtype=np.float32)[:, None]
        ys = np.arange(self.height, dtype=np.float32)[None, :]
        dist = np.hypot(xs - pov_x, ys - pov_y)
        t = np.clip((dist - inner_radius) / max(1e-6, self.fov_radius - inner_radius), 0.0, 1.0)
        return 1.0 - t * edge_falloff
