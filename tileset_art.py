"""程序生成的图块（白色形状，颜色由 console 的 fg 调制）。

两类图块：
- 地形（墙面制表符/地面点/孤立墙）：满格绘制，墙线在格子间无缝相连
- 实体（道具/尸骸/楼梯等）：按 INK_RATIO 墨迹比例居中，与字体字形视觉大小一致

ART_REGISTRY 为实体图块注册表：items.json / monsters.json 用 "art": "thunder_talisman"
引用。每个 art 分配一个 PUA 码点（U+E000 起）。
"""

from __future__ import annotations

from typing import Callable

import numpy as np
from PIL import Image

ART_BASE_CODEPOINT = 0xE000
BASE_DESIGN = 12
INK_RATIO = 0.72  # 实体图块墨迹占格比例，对齐字体字形的视觉大小

WALL_GLYPHS = "#│││─┘┐┤─└┌├─┴┬┼"  # 索引 = 上*1 + 下*2 + 左*4 + 右*8


def _canvas() -> np.ndarray:
    return np.zeros((BASE_DESIGN, BASE_DESIGN), dtype=bool)


def _mask_to_tile(mask: np.ndarray, size: int, ink_ratio: float = 1.0) -> np.ndarray:
    """布尔掩码 → RGBA 白色图块。ink_ratio<1 时按比例缩小居中。"""
    if ink_ratio >= 1.0:
        ink = size
        margin = 0
    else:
        ink = max(1, int(round(size * ink_ratio)))
        margin = (size - ink) // 2
    img = Image.fromarray((mask * 255).astype(np.uint8), mode="L")
    img = img.resize((ink, ink), Image.NEAREST)
    canvas_img = Image.new("L", (size, size), 0)
    canvas_img.paste(img, (margin, margin))
    alpha = np.array(canvas_img)
    out = np.zeros((size, size, 4), dtype=np.uint8)
    out[..., 0] = out[..., 1] = out[..., 2] = 255
    out[..., 3] = alpha
    return out


def wall_mask(bitmask: int) -> np.ndarray:
    """按方向位画墙面：线宽 2 设计像素，臂伸到格子边缘保证相邻格无缝相接。"""
    m = _canvas()
    if bitmask == 0:
        m[4:8, 4:8] = True  # 孤立墙：实心方墩
        return m
    if bitmask & 1:  # 上
        m[0:7, 5:7] = True
    if bitmask & 2:  # 下
        m[5:12, 5:7] = True
    if bitmask & 4:  # 左
        m[5:7, 0:7] = True
    if bitmask & 8:  # 右
        m[5:7, 5:12] = True
    return m


def floor_dot_mask() -> np.ndarray:
    m = _canvas()
    m[5:7, 5:7] = True
    return m


def inject_terrain_tiles(tileset, tile_size: int, floor_char: str) -> None:
    """注入满格地形图块：墙线/地面点，覆盖字体原生字形。"""
    for i, glyph in enumerate(WALL_GLYPHS):
        tileset[ord(glyph)] = _mask_to_tile(wall_mask(i), tile_size)
    tileset[ord(floor_char)] = _mask_to_tile(floor_dot_mask(), tile_size)


# ---- 实体图块 ----


def _thunder_talisman() -> np.ndarray:
    m = _canvas()
    bolt = [(8, 0), (7, 1), (8, 2), (5, 3), (6, 4), (5, 5), (4, 6), (5, 7), (4, 8), (3, 9), (4, 10), (3, 11)]
    for x, y in bolt:
        m[y, x] = True
    for dx in (1, 0):
        for x, y in bolt:
            if 0 <= x + dx < 12:
                m[y, x + dx] = True
    return m


def _lingzhi() -> np.ndarray:
    m = _canvas()
    m[2, 3:9] = True
    m[3, 2] = m[3, 9] = True
    m[4, 2] = m[4, 9] = True
    m[3, 4] = m[3, 7] = True
    m[5, 5] = m[5, 6] = True
    for y in range(6, 12):
        m[y, 5:7] = True
    m[8, 4] = m[9, 3] = m[10, 2] = m[9, 7] = m[10, 8] = m[11, 9] = True
    return m


def _corpse() -> np.ndarray:
    m = _canvas()
    m[3, 2:5] = True
    m[4, 2] = m[4, 4] = True
    m[3, 5] = m[4, 5] = True
    for x in range(5, 11):
        m[4, x] = True
        m[5, x] = True
    m[3, 8] = m[5, 8] = m[6, 8] = m[7, 7] = m[7, 9] = m[8, 6] = m[8, 10] = m[9, 5] = m[9, 11] = True
    m[10, 5] = m[11, 5] = m[10, 11] = m[11, 11] = True
    return m


def _stairs_glow() -> np.ndarray:
    m = _canvas()
    for x in range(0, 12):
        m[2, x] = True
    for x in range(2, 12):
        m[5, x] = True
    for x in range(4, 12):
        m[8, x] = True
    for x in range(6, 12):
        m[11, x] = True
    for y in range(2, 12):
        m[y, 11] = True
    return m


def _realm_gate() -> np.ndarray:
    """秘境之门：同心漩涡。"""
    m = _canvas()
    m[1, 3:9] = True
    m[2, 2] = m[2, 9] = True
    m[3, 1] = m[3, 10] = True
    m[4, 1] = m[4, 10] = True
    m[7, 1] = m[7, 10] = True
    m[8, 1] = m[8, 10] = True
    m[9, 2] = m[9, 9] = True
    m[10, 3:9] = True
    m[3, 4] = m[4, 3] = m[3, 7] = m[4, 8] = True
    m[7, 3] = m[8, 4] = m[7, 8] = m[8, 7] = True
    m[5:7, 5:7] = True
    return m


def _realm_gate_sealed() -> np.ndarray:
    """封印之门：门框 + 十字封条。"""
    m = _realm_gate()
    m[5, 2:10] = True
    m[6, 2:10] = True
    for y in range(2, 10):
        m[y, 5] = m[y, 6] = True
    return m


ART_REGISTRY: dict[str, Callable[[], np.ndarray]] = {
    "thunder_talisman": _thunder_talisman,
    "lingzhi": _lingzhi,
    "corpse": _corpse,
    "stairs_glow": _stairs_glow,
    "realm_gate": _realm_gate,
    "realm_gate_sealed": _realm_gate_sealed,
}


def art_codepoint(art_name: str) -> int:
    if art_name not in ART_REGISTRY:
        raise KeyError(f"未知图块 '{art_name}'，可用：{sorted(ART_REGISTRY)}")
    return ART_BASE_CODEPOINT + list(ART_REGISTRY).index(art_name)


def art_char(art_name: str) -> str:
    return chr(art_codepoint(art_name))


def inject_art_tiles(tileset, tile_size: int) -> None:
    """把注册表全部实体图块注入 tileset（墨迹比例居中，与字体视觉一致）。"""
    for name, generator in ART_REGISTRY.items():
        mask = generator()
        tileset[art_codepoint(name)] = _mask_to_tile(mask, tile_size, INK_RATIO)
