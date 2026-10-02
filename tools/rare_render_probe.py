"""生僻字渲染探针：缺字的实际表现 + 从回退字体像素化注入的效果。"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import tcod
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from paths import resource_path  # noqa: E402

TS = 24
BASE = 12
MISSING = "彘窫猰"
FALLBACK_FONT = "C:/Windows/Fonts/simhei.ttf"


def pixelated_fallback_tile(ch: str) -> np.ndarray:
    """从回退字体按 12px 光栅化再最近邻放大到 24px，保持像素风格统一。"""
    font = ImageFont.truetype(FALLBACK_FONT, BASE)
    img = Image.new("RGBA", (BASE, BASE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.text((0, 0), ch, font=font, fill=(255, 255, 255, 255))
    img = img.resize((TS, TS), Image.NEAREST)
    return np.array(img)


def main() -> None:
    out = str(Path(__file__).parent / "probe_rare.png")
    tileset = tcod.tileset.load_truetype_font(str(resource_path("assets/font.ttf")), TS, TS)

    sample = "狌彘窫猰夔魑魅魍魉䍶☰☵☯𤝱"

    injected = ""
    for ch in MISSING:
        tile = pixelated_fallback_tile(ch)
        tileset[ord(ch)] = tile
        injected += ch

    width, height = 40, 8
    with tcod.context.new(columns=width, rows=height, tileset=tileset, title="生僻字探针") as ctx:
        con = tcod.console.Console(width, height, order="F")
        con.print(1, 1, "测试串（含缺字彘窫猰䍶𤝱）:", fg=(200, 200, 200))
        con.print(1, 3, sample, fg=(235, 235, 235))
        con.print(1, 4, "▲ 其中 彘窫猰 已从simhei像素化注入", fg=(140, 220, 160))
        con.print(1, 6, injected + " ← 注入后特写", fg=(120, 220, 180))
        ctx.present(con)
        ctx.save_screenshot(out)
        print(f"生僻字探针截图已保存：{out}")


if __name__ == "__main__":
    main()
