"""地图瓦片定义：字符与颜色分「亮（视野内）/暗（记忆中）」两档。

将来加更多地形（水、岩浆、竹林等）在此扩展 tile 定义，
生成器与渲染器按 walkable/transparent 字段自动适配。
"""

import numpy as np


tile_dtype = np.dtype(
    [
        ("walkable", np.bool_),
        ("transparent", np.bool_),
        ("light_char", "U1"),
        ("light_fg", (np.uint8, 3)),
        ("dark_char", "U1"),
        ("dark_fg", (np.uint8, 3)),
    ]
)


def _tile(char: str, walkable: bool, transparent: bool, light_fg: tuple, dark_fg: tuple) -> np.void:
    darkened = tuple(int(c * 0.45) for c in light_fg)
    return np.array(
        (walkable, transparent, char, light_fg, char, dark_fg or darkened),
        dtype=tile_dtype,
    )[()]


FLOOR = _tile("·", True, True, (96, 94, 110), (44, 42, 52))
WALL = _tile("#", False, False, (146, 120, 86), (62, 50, 36))
