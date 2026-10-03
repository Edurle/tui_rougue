"""字形管线：PIL 重渲 + 生僻字回退注入。

tcod 的 load_truetype_font 对双宽 CJK 字体推导的字号严重偏小（实测墨迹仅
格高的 ~19%），因此主字体字形全部由 PIL 按 font_size≈tile_size 居中重渲后
逐码点注入 tileset，掌控墨迹比例；主字体缺失的码点再从系统字体回退注入。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable

from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

BASE_DESIGN = 12

FALLBACK_FONT_CANDIDATES = (
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simsun.ttc",
)


def font_cmap(font_path: Path) -> set[int]:
    font = TTFont(str(font_path), fontNumber=0)
    codes: set[int] = set()
    for table in font["cmap"].tables:
        if table.isUnicode():
            codes.update(table.cmap.keys())
    return codes


def collect_text(value) -> Iterable[str]:
    if isinstance(value, str):
        yield from value
    elif isinstance(value, dict):
        for v in value.values():
            yield from collect_text(v)
    elif isinstance(value, list):
        for v in value:
            yield from collect_text(v)


def content_characters(content) -> set[str]:
    chars: set[str] = set()
    for text in content.strings.values():
        chars.update(text)
    for pool in (content.monsters, content.items):
        for definition in pool.values():
            chars.update(collect_text(definition.get("name", "")))
            chars.update(collect_text(definition.get("lore", "")))
    # 职业与技能：名称、简介、召唤兽名（双语）进字形管线
    for definition in content.classes.values():
        chars.update(collect_text(definition.get("name", "")))
        chars.update(collect_text(definition.get("desc", "")))
    for definition in content.skills.values():
        chars.update(collect_text(definition.get("name", "")))
        chars.update(collect_text(definition.get("desc", "")))
        chars.update(collect_text(definition["effect"].get("beast_name", "")))
    for region in content.regions:
        chars.update(collect_text(region["name"]))
        chars.update(collect_text(region["mountains"]))
    chars.update(collect_text(content.player_def.get("name", "")))
    # 地形字形（theme.terrains 的 char，如 ♣▲≈▼）进字形管线
    for terrain in content.theme.get("terrains", {}).values():
        chars.update(collect_text(terrain.get("char", "")))
    chars.update("0123456789")
    return {c for c in chars if not c.isspace()}


EXTRA_RUNTIME_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    "!?+-*/=<>():;,._'\"[]{}@#$%&|~^` "
    "✦⚡!%?><·✓×↑►"
)


def _draw_centered(ch: str, font, tile_size: int) -> "Image.Image":
    """按字形实际 bbox 居中绘制：带下伸部（g/p/q/y 等）与超宽字形不会被画布裁剪。"""
    img = Image.new("L", (tile_size, tile_size), 0)
    bbox = font.getbbox(ch)
    if bbox is None:
        return img
    x0, y0, x1, y1 = bbox
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return img
    # PIL text 坐标默认以左上（含 ascent 的布局顶）为原点，与 getbbox 同系
    x_off = (tile_size - w) // 2 - x0
    y_off = (tile_size - h) // 2 - y0
    ImageDraw.Draw(img).text((x_off, y_off), ch, font=font, fill=255)
    return img


def rasterize_glyphs(tileset, font_path: Path, chars: set[str], tile_size: int, font_size: int) -> int:
    """PIL 重渲字形并注入 tileset（白色 + alpha，fg 调制），返回注入数量。"""
    import numpy as np

    font = ImageFont.truetype(str(font_path), font_size)
    injected = 0
    for ch in sorted(chars):
        cp = ord(ch)
        if cp < 32:
            continue
        alpha = np.array(_draw_centered(ch, font, tile_size))
        if alpha.max() < 40:
            continue  # 字体无此字形，交由回退处理
        rgba = np.zeros((tile_size, tile_size, 4), dtype=np.uint8)
        rgba[..., 0] = rgba[..., 1] = rgba[..., 2] = 255
        rgba[..., 3] = alpha
        tileset[cp] = rgba
        injected += 1
    return injected


def _load_fallback_font(tile_size: int):
    for candidate in FALLBACK_FONT_CANDIDATES:
        path = Path(candidate)
        if path.exists():
            try:
                return ImageFont.truetype(str(path), tile_size), path
            except Exception:
                continue
    return None, None


def _rasterize(ch: str, font, tile_size: int) -> "object":
    return _draw_centered(ch, font, tile_size)


def apply_font_pipeline(tileset, content, main_font_path: Path, tile_size: int) -> None:
    """字形管线：先 PIL 重渲全部所需字形，再对主字体缺字做系统字体回退。"""
    chars = content_characters(content) | EXTRA_RUNTIME_CHARS
    count = rasterize_glyphs(tileset, main_font_path, chars, tile_size, font_size=int(tile_size * 0.96))
    print(f"[字形] PIL 重渲注入 {count} 个字形（font_size={int(tile_size * 0.96)}px）", file=sys.stderr)
    _apply_fallback(tileset, content, main_font_path, tile_size)


def _apply_fallback(tileset, content, main_font_path: Path, tile_size: int) -> int:
    """主字体缺字注入，返回注入数量。无可用回退字体时警告并跳过。"""
    chars = content_characters(content)
    try:
        known = font_cmap(main_font_path)
    except Exception as exc:
        print(f"[警告] 无法读取主字体 cmap，跳过生僻字回退：{exc}", file=sys.stderr)
        return 0
    missing = [c for c in sorted(chars) if ord(c) not in known]
    if not missing:
        return 0

    font, used_path = _load_fallback_font(tile_size)
    if font is None:
        print(
            f"[警告] 内容含 {len(missing)} 个主字体缺字（{''.join(missing[:10])}…），"
            "且无可用回退字体，这些字符将显示为空白。",
            file=sys.stderr,
        )
        return 0

    import numpy as np

    injected = 0
    for ch in missing:
        img = _rasterize(ch, font, tile_size)
        if img.getextrema()[1] == 0:
            continue
        rgba = np.zeros((tile_size, tile_size, 4), dtype=np.uint8)
        rgba[..., 0] = rgba[..., 1] = rgba[..., 2] = 255
        rgba[..., 3] = np.array(img)
        tileset[ord(ch)] = rgba
        injected += 1
    print(f"[字体回退] {used_path.name} 注入 {injected} 个缺字：{''.join(missing[:20])}", file=sys.stderr)
    return injected
