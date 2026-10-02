"""地图瓦片语义定义（walkable/transparent）。颜色与字符在 theme.json / 邻接计算。"""

import numpy as np


tile_dtype = np.dtype(
    [
        ("walkable", np.bool_),
        ("transparent", np.bool_),
    ]
)


def _tile(walkable: bool, transparent: bool) -> np.void:
    return np.array((walkable, transparent), dtype=tile_dtype)[()]


FLOOR = _tile(True, True)
WALL = _tile(False, False)
