"""《山海行》——字符 Roguelike。

入口：python main.py [--lang zh_CN|en_US] [--map large|medium|small]
                     [--sidebar large|medium|small] [--smoke [输出路径]]
语言优先级：--lang 参数 > 系统语言检测 > zh_CN
显示设置：F1 循环画面大小（字号+格数），F2 循环信息板宽度；持久化到 settings.json
"""

from __future__ import annotations

import locale
import sys
import time
from pathlib import Path
from typing import Optional

import tcod

from content_loader import DEFAULT_LANG, SUPPORTED_LANGS, load_content
from engine import Engine
from font_fallback import apply_font_pipeline
from input_handlers import (
    ChangeSizeAction,
    CloseMenuAction,
    GameOverEventHandler,
    InventoryEventHandler,
    MainGameEventHandler,
    OpenInventoryAction,
    RestartAction,
    SwitchHandlerAction,
)
from paths import resource_path
from settings import Settings
from tileset_art import inject_art_tiles, inject_terrain_tiles

WINDOW_TITLE_KEY = "window_title"

# 字体回退链：优先项目内置字体（打包随附）
FALLBACK_FONTS = (
    "assets/font.ttf",
    "C:/Windows/Fonts/simhei.ttf",
)


def detect_lang() -> str:
    loc = locale.getlocale()[0] or ""
    for supported in SUPPORTED_LANGS:
        if loc.replace("-", "_").lower().startswith(supported.split("_")[0].lower()):
            return supported
    return DEFAULT_LANG


def parse_arg_value(argv: list[str], flag: str) -> Optional[str]:
    if flag in argv:
        idx = argv.index(flag)
        if idx + 1 < len(argv):
            return argv[idx + 1]
    return None


def load_tileset(tile_size: int) -> tuple[tcod.tileset.Tileset, Path | None]:
    """优先内置中文字体；加载失败退回 tcod 自带字符集（仅 ASCII 可用）。"""
    for font_path in FALLBACK_FONTS:
        path = Path(font_path)
        if not path.is_absolute():
            path = resource_path(font_path)
        if not path.exists():
            continue
        try:
            return tcod.tileset.load_truetype_font(str(path), tile_size, tile_size), path
        except Exception as exc:  # noqa: BLE001 —— 字体失败需逐个降级尝试
            print(f"[警告] 字体 {path} 加载失败：{exc}", file=sys.stderr)
    print("[警告] 未找到中文字体，退回 ASCII 字符集，中文将无法显示。", file=sys.stderr)
    return tcod.tileset.get_default(), None


def build_tileset(content, settings) -> tcod.tileset.Tileset:
    tileset, main_font_path = load_tileset(settings.tile_size)
    inject_terrain_tiles(tileset, settings.tile_size, content.theme["tiles"]["floor_char"])
    inject_art_tiles(tileset, settings.tile_size)
    if main_font_path is not None:
        apply_font_pipeline(tileset, content, main_font_path, settings.tile_size)
    return tileset


def game_loop(context, console, engine, content) -> str:
    """主循环；返回变更类型（map/sidebar）请求重建窗口，退出走 SystemExit。"""
    handler = MainGameEventHandler(engine)
    last_time = time.perf_counter()
    while True:
        now = time.perf_counter()
        dt = min(0.1, now - last_time)
        last_time = now

        engine.effects.update(dt)
        handler.on_render(console)
        # 保持宽高比 + 整数倍缩放：窗口任意拉伸/最大化都不发糊（余量留黑边）
        context.present(console, keep_aspect=True, integer_scaling=True)

        if engine.game_over and not isinstance(handler, GameOverEventHandler):
            handler = GameOverEventHandler(engine)

        for event in tcod.event.get():
            context.convert_event(event)
            action = handler.dispatch(event)

            if isinstance(action, ChangeSizeAction):
                if action.kind == "map":
                    engine.settings.cycle_map()
                else:
                    engine.settings.cycle_sidebar()
                engine.settings.save()
                return action.kind

            if isinstance(action, SwitchHandlerAction):
                if isinstance(action, OpenInventoryAction):
                    handler = InventoryEventHandler(engine)
                elif isinstance(action, CloseMenuAction):
                    handler = MainGameEventHandler(engine)
                elif isinstance(action, RestartAction):
                    engine = new_engine(engine.content, engine.settings)
                    handler = MainGameEventHandler(engine)
                continue

            if action is not None:
                engine.handle_action(action)


def new_engine(content, settings, previous_messages=None) -> Engine:
    engine = Engine(content, settings)
    if previous_messages:
        engine.message_log.messages = previous_messages
    return engine


def run(lang: Optional[str], smoke_output: Optional[str] = None) -> None:
    resolved_lang = lang if lang in SUPPORTED_LANGS else detect_lang()
    content = load_content(resolved_lang)
    strings = content.strings

    settings = Settings.load()
    map_override = parse_arg_value(sys.argv, "--map")
    sidebar_override = parse_arg_value(sys.argv, "--sidebar")
    if map_override:
        settings.map_size = map_override
    if sidebar_override:
        settings.sidebar_size = sidebar_override

    while True:
        tileset = build_tileset(content, settings)
        with tcod.context.new(
            columns=settings.total_cols,
            rows=settings.total_rows,
            tileset=tileset,
            title=strings[WINDOW_TITLE_KEY],
            vsync=True,
        ) as context:
            console = tcod.console.Console(settings.total_cols, settings.total_rows, order="F")
            engine = new_engine(content, settings)

            if smoke_output:
                handler = MainGameEventHandler(engine)
                handler.on_render(console)
                context.present(console, keep_aspect=True, integer_scaling=True)
                context.save_screenshot(smoke_output)
                print(f"冒烟截图已保存：{smoke_output}")
                return

            changed = game_loop(context, console, engine, content)
            if changed == "map":
                engine = new_engine(content, settings, previous_messages=engine.message_log.messages)
                engine.message_log.add_message(
                    strings["ui_map_size"].format(size=strings[f"size_{settings.map_size}"]), "info"
                )
            elif changed == "sidebar":
                engine = new_engine(content, settings, previous_messages=engine.message_log.messages)
                engine.message_log.add_message(
                    strings["ui_sidebar_size"].format(size=strings[f"size_{settings.sidebar_size}"]), "info"
                )
            # 循环回到顶部：以新设置重建窗口；旧 context 已由 with 退出时关闭


def main() -> None:
    smoke_output: Optional[str] = None
    if "--smoke" in sys.argv:
        idx = sys.argv.index("--smoke")
        smoke_output = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "smoke_frame.png"
    try:
        run(parse_arg_value(sys.argv, "--lang"), smoke_output)
    except SystemExit:
        pass


if __name__ == "__main__":
    main()
