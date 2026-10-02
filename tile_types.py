"""地图地形定义：terrain id → 通行/透光语义 + 主题键。

颜色与字符在 theme.json 的 terrains 节（按主题键配置，代码零颜色）。
GameMap.tiles 结构化数组（walkable/transparent）是 terrain 的派生缓存，
由 GameMap.refresh_tile_flags() 重建——FOV/AI/移动只读派生数组。

terrain id 必须稳定不变：地图数组与存档直接存 id。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

tile_dtype = np.dtype(
    [
        ("walkable", np.bool_),
        ("transparent", np.bool_),
    ]
)


@dataclass(frozen=True)
class TerrainDef:
    tid: int
    key: str  # theme.terrains 键（字符/明暗色的索引）
    walkable: bool
    transparent: bool


# ---- 地形 id（0/1 为秘境地牢沿用，世界地形从 2 起）----

T_FLOOR = 0  # 秘境地面
T_WALL = 1  # 秘境石壁（邻接线框渲染）
T_PLAIN = 2  # 大地原野
T_FOREST = 3  # 森林（遮视野）
T_HILL = 4  # 丘陵
T_MOUNTAIN = 5  # 山脉（不可通行）
T_WATER = 6  # 湖泊
T_RIVER = 7  # 河流
T_BRIDGE = 8  # 桥（架在河上，可通行）
T_ABYSS = 9  # 深渊裂谷
T_SNOW = 10  # 雪峰（极高山巅）
T_SHORE = 11  # 水岸滩涂

TERRAIN_DEFS: dict[int, TerrainDef] = {
    d.tid: d
    for d in (
        TerrainDef(T_FLOOR, "floor", True, True),
        TerrainDef(T_WALL, "wall", False, False),
        TerrainDef(T_PLAIN, "plain", True, True),
        TerrainDef(T_FOREST, "forest", True, False),
        TerrainDef(T_HILL, "hill", True, True),
        TerrainDef(T_MOUNTAIN, "mountain", False, False),
        TerrainDef(T_WATER, "water", False, True),
        TerrainDef(T_RIVER, "river", False, True),
        TerrainDef(T_BRIDGE, "bridge", True, True),
        TerrainDef(T_ABYSS, "abyss", False, True),
        TerrainDef(T_SNOW, "snow", False, True),
        TerrainDef(T_SHORE, "shore", True, True),
    )
}

N_TERRAINS = len(TERRAIN_DEFS)

# terrain id → walkable/transparent 查找表（refresh_tile_flags 向量化用）
WALKABLE_LUT = np.array([d.walkable for d in TERRAIN_DEFS.values()], dtype=np.bool_)
TRANSPARENT_LUT = np.array([d.transparent for d in TERRAIN_DEFS.values()], dtype=np.bool_)

# 兼容别名：秘境地牢的经典写法
FLOOR = T_FLOOR
WALL = T_WALL


def is_wall(tid) -> bool:
    return tid == T_WALL
