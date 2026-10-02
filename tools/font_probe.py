"""tcod 表现力探针：验证多色符号 / Nerd 字体图标 / 运行时彩色图块。

用法：
    python tools/font_probe.py <字体路径> [输出png]
    python tools/font_probe.py            # 用 assets/font.ttf（像素字体，无Nerd图标）
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import tcod

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from paths import resource_path  # noqa: E402

TS = 24  # 与游戏一致的 2x 像素基准


def make_taijitu(size: int) -> np.ndarray:
    """程序生成一枚全彩太极图块（证明可运行时上传任意 RGBA 图形）。"""
    yy, xx = np.mgrid[0:size, 0:size]
    cy = cx = (size - 1) / 2
    r = size * 0.46
    dist = np.hypot(xx - cx, yy - cy)
    art = np.zeros((size, size, 4), dtype=np.uint8)
    art[..., :3] = (24, 22, 30)
    art[..., 3] = 255
    inside = dist <= r
    right_half = inside & (xx >= cx)
    left_half = inside & (xx < cx)
    art[right_half] = (232, 230, 224, 255)
    art[left_half] = (38, 36, 44, 255)
    upper = np.hypot(xx - cx, yy - (cy - r / 2)) <= r / 2.7
    lower = np.hypot(xx - cx, yy - (cy + r / 2)) <= r / 2.7
    art[upper] = (232, 230, 224, 255)
    art[lower] = (38, 36, 44, 255)
    art[np.hypot(xx - cx, yy - (cy - r / 2)) <= r / 9] = (38, 36, 44, 255)
    art[np.hypot(xx - cx, yy - (cy + r / 2)) <= r / 9] = (232, 230, 224, 255)
    return art


def main() -> None:
    font = Path(sys.argv[1]) if len(sys.argv) > 1 else resource_path("assets/font.ttf")
    out = sys.argv[2] if len(sys.argv) > 2 else str(Path(__file__).parent / "probe.png")

    tileset = tcod.tileset.load_truetype_font(str(font), TS, TS)
    tileset[ord("☯")] = make_taijitu(TS)  # 运行时图块：覆盖任意码点为自定义彩色图形

    width, height = 62, 16
    with tcod.context.new(columns=width, rows=height, tileset=tileset, title="tcod 表现力探针") as ctx:
        con = tcod.console.Console(width, height, order="F")

        con.print(1, 1, f"字体: {font.name}  |  ASCII abc 123 与中文混排", fg=(235, 235, 235))

        # 1) 前景色独立（同一符号不同色）
        con.print(1, 3, "前景色:", fg=(150, 150, 150))
        for i, (r, g, b) in enumerate([(230, 80, 80), (90, 220, 120), (90, 140, 250), (250, 210, 90), (220, 120, 230)]):
            con.print(9 + i * 3, 3, "◆", fg=(r, g, b))

        # 2) 背景色独立 + 前景叠加
        con.print(1, 5, "前+背景:", fg=(150, 150, 150))
        for i, (fg, bg) in enumerate(zip(
            [(255, 255, 255), (30, 30, 40), (250, 220, 90), (20, 60, 90), (240, 240, 240)],
            [(60, 50, 40), (200, 60, 60), (40, 40, 50), (240, 230, 160), (90, 60, 140)],
        )):
            con.print(9 + i * 3, 5, "@", fg=fg, bg=bg)

        # 3) Nerd Font 图标（PUA 私用区码点）
        icons = (
            "\ue0b0"  # Powerline 实心箭头
            "\uf005"  # fa 星形
            "\uf07b"  # 文件夹
            "\uf121"  # 代码
            "\uf015"  # 首页
            "\uf06d"  # 火焰
            "\uf09b"  # GitHub 章鱼猫
            "\uf0e7"  # 闪电
            "\uf188"  # 虫子
            "\uf021"  # 循环箭头
        )
        con.print(1, 7, "Nerd图标:", fg=(150, 150, 150))
        con.print(11, 7, icons, fg=(120, 220, 180))

        # 4) 图标做彩色 UI 条（模拟状态栏）
        con.print(1, 9, "彩色UI:", fg=(150, 150, 150))
        con.print(9, 9, "\uf0e7 五雷符", fg=(250, 220, 100))
        con.print(17, 9, "\uf06d 火焰", fg=(250, 120, 80))
        con.print(24, 9, "\uf005 修为", fg=(250, 210, 90))
        con.print(31, 9, "\uf188 蛊雕", fg=(150, 200, 120))

        # 5) 运行时上传的全彩图块（太极）
        con.print(1, 11, "自定义图块:", fg=(150, 150, 150))
        con.print(13, 11, "☯ ☯ ☯  ← 程序生成的 RGBA 图形", fg=(235, 235, 235))

        # 6) 半透明混合背景条（bg_blend）
        con.print(1, 13, "混合背景条: ▓▓▓▓▓▓▓▓", fg=(200, 200, 210), bg=(80, 40, 90))

        ctx.present(con)
        ctx.save_screenshot(out)
        print(f"探针截图已保存：{out}")


if __name__ == "__main__":
    main()
