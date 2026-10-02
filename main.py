"""《山海行》——字符 Roguelike。

入口：python main.py
冒烟渲染（自动截图退出）：python main.py --smoke [输出路径]
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import tcod

from content_loader import load_content
from engine import Engine
from input_handlers import (
    CloseMenuAction,
    GameOverEventHandler,
    InventoryEventHandler,
    MainGameEventHandler,
    OpenInventoryAction,
    RestartAction,
    SwitchHandlerAction,
)
from paths import resource_path

WINDOW_COLUMNS = 80
WINDOW_ROWS = 45
WINDOW_TITLE = "山海行 — 字符 Roguelike"

FALLBACK_FONTS = (
    "assets/font.ttf",          # 项目内置开源中文字体（打包随附）
    "C:/Windows/Fonts/simhei.ttf",  # 开发机系统黑体
)


def load_tileset() -> tcod.tileset.Tileset:
    """优先内置中文像素字体；加载失败退回 tcod 自带字符集（仅 ASCII 可用）。"""
    for font_path in FALLBACK_FONTS:
        path = Path(font_path)
        if not path.is_absolute():
            path = resource_path(font_path)
        if not path.exists():
            continue
        try:
            return tcod.tileset.load_truetype_font(str(path), 12, 12)
        except Exception as exc:  # noqa: BLE001 —— 字体失败需逐个降级尝试
            print(f"[警告] 字体 {path} 加载失败：{exc}", file=sys.stderr)
    print("[警告] 未找到中文字体，退回 ASCII 字符集，中文将无法显示。", file=sys.stderr)
    return tcod.tileset.get_default()


def new_game(content) -> tuple[Engine, MainGameEventHandler]:
    engine = Engine(content)
    handler = MainGameEventHandler(engine)
    return engine, handler


def run(smoke_output: Optional[str] = None) -> None:
    content = load_content()
    tileset = load_tileset()

    with tcod.context.new(
        columns=WINDOW_COLUMNS,
        rows=WINDOW_ROWS,
        tileset=tileset,
        title=WINDOW_TITLE,
        vsync=True,
    ) as context:
        console = tcod.console.Console(WINDOW_COLUMNS, WINDOW_ROWS, order="F")
        engine, handler = new_game(content)

        if smoke_output:
            handler.on_render(console)
            context.present(console)
            context.save_screenshot(smoke_output)
            print(f"冒烟截图已保存：{smoke_output}")
            return

        while True:
            console.clear()
            handler.on_render(console)
            context.present(console)

            if engine.game_over and not isinstance(handler, GameOverEventHandler):
                handler = GameOverEventHandler(engine)

            for event in tcod.event.wait():
                context.convert_event(event)
                action = handler.dispatch(event)

                if isinstance(action, SwitchHandlerAction):
                    if isinstance(action, OpenInventoryAction):
                        handler = InventoryEventHandler(engine)
                    elif isinstance(action, CloseMenuAction):
                        handler = MainGameEventHandler(engine)
                    elif isinstance(action, RestartAction):
                        engine, handler = new_game(content)
                    continue

                if action is not None:
                    engine.handle_action(action)


def main() -> None:
    smoke_output: Optional[str] = None
    if "--smoke" in sys.argv:
        idx = sys.argv.index("--smoke")
        smoke_output = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "smoke_frame.png"
    try:
        run(smoke_output)
    except SystemExit:
        pass


if __name__ == "__main__":
    main()
