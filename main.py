"""《山海行》——字符 Roguelike。

入口：python main.py [--lang zh_CN|en_US] [--map large|medium|small]
                     [--sidebar large|medium|small] [--smoke [输出路径]]
语言优先级：--lang 参数 > 开始界面设置 > 系统语言检测 > zh_CN
显示与语言设置集中在开始界面（设置子界面，即时生效并持久化）；对局中不可调整
开局：开始界面 → 两段职业选择（主→副）；转世重修回开始界面
"""

from __future__ import annotations

import locale
import sys
import time
from pathlib import Path
from typing import Optional

import tcod

import exceptions
import skills as skills_module
from content_loader import DEFAULT_LANG, SUPPORTED_LANGS, load_content
from engine import Engine
from font_fallback import apply_font_pipeline
from input_handlers import (
    ClassSelectEventHandler,
    CloseMenuAction,
    CraftEventHandler,
    DirectionSelectEventHandler,
    ExamineEventHandler,
    GameOverEventHandler,
    InventoryEventHandler,
    LoadGameAction,
    MainGameEventHandler,
    OpenCraftAction,
    OpenExamineAction,
    OpenInventoryAction,
    OpenSkillLearnAction,
    OpenWorldMapAction,
    RestartAction,
    SettingsMenuEventHandler,
    SkillLearnEventHandler,
    SwitchHandlerAction,
    TargetingEventHandler,
    TitleMenuEventHandler,
    WorldMapEventHandler,
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


def _present(context, console) -> None:
    # 保持宽高比 + 整数倍缩放：窗口任意拉伸/最大化都不发糊（余量留黑边）
    context.present(console, keep_aspect=True, integer_scaling=True)


def collect_class_ids(context, console, content, settings) -> tuple:
    """开局两段职业选择（主→副）；返回 (主 id, 副 id)。"""
    console.clear(fg=(236, 236, 240), bg=tuple(content.theme["background"]))
    handler = ClassSelectEventHandler(content, settings)
    while not handler.done:
        handler.on_render(console)
        _present(context, console)
        for event in tcod.event.get():
            handler.dispatch(event)
    console.clear(fg=(236, 236, 240), bg=tuple(content.theme["background"]))
    return handler.chosen


def title_menu_loop(context, console, content, settings):
    """开始界面主菜单（含设置子界面）。

    返回 (choice, content)：
    - ("new", content)      开始新游历（随后进职业选择）
    - ("continue", content) 继续游历（存档存在）
    - ("quit", content)     离开（调用方 SystemExit/返回）
    - ("resize", content)   设置改了显示档位 → 外层重建窗口后回主菜单
    content 可能因语言切换被重载（设置内即时生效），同时重烘字形并
    热替换 tileset（格数不变，无需重建窗口）。
    """
    import save_manager

    while True:
        handler = TitleMenuEventHandler(content, settings, has_save=save_manager.save_exists())
        handler_done = False
        while not handler_done:
            handler.on_render(console)
            _present(context, console)
            for event in tcod.event.get():
                handler.dispatch(event)
                if handler.done:
                    handler_done = True

        if handler.choice == "settings":
            settings_menu = SettingsMenuEventHandler(content, settings)
            while not settings_menu.done:
                settings_menu.on_render(console)
                _present(context, console)
                for event in tcod.event.get():
                    settings_menu.dispatch(event)
                    if settings_menu.lang_changed:
                        # 字形集按语言烘焙：切语言重载 content 后必须重烘 tileset
                        # 并热替换，否则新语言字符缺字形显示空白
                        content = settings_menu.content
                        context.change_tileset(build_tileset(content, settings))
                        settings_menu.lang_changed = False
            content = settings_menu.content  # 语言可能已切换（content 重载）
            if settings_menu.needs_resize:
                return "resize", content
            continue  # 回主菜单

        return handler.choice, content


def _run_session(context, console, engine, content) -> str:
    """一次游戏会话：退出（Esc/关窗）或切档位时，存活的进度先落盘再离开。"""
    try:
        return game_loop(context, console, engine, content)
    finally:
        # 死亡已删档（roguelike 铁律），其余情况退出前自动存档防进度丢失
        if not engine.game_over and engine.player is not None and engine.player.is_alive:
            engine.autosave()


def game_loop(context, console, engine, content) -> str:
    """主循环；返回变更类型（map/sidebar/restart）请求上层处理，退出走 SystemExit。"""
    handler = MainGameEventHandler(engine)
    last_time = time.perf_counter()
    last_travel = 0.0
    while True:
        now = time.perf_counter()
        dt = min(0.1, now - last_time)
        last_time = now

        engine.effects.update(dt)

        # 大世界旅行步进（Shift+方向触发，55ms 一步，任意按键打断）
        if engine.traveling is not None and not engine.game_over:
            if now - last_travel >= 0.055:
                last_travel = now
                engine.travel_step()

        handler.on_render(console)
        _present(context, console)

        if engine.game_over and not isinstance(handler, GameOverEventHandler):
            handler = GameOverEventHandler(engine)

        for event in tcod.event.get():
            context.convert_event(event)
            action = handler.dispatch(event)

            if isinstance(action, SwitchHandlerAction):
                engine.traveling = None  # 切换输入模式即终止旅行
                if isinstance(action, OpenInventoryAction):
                    handler = InventoryEventHandler(engine)
                elif isinstance(action, OpenSkillLearnAction):
                    handler = SkillLearnEventHandler(engine)
                elif isinstance(action, OpenExamineAction):
                    handler = ExamineEventHandler(engine)
                elif isinstance(action, OpenWorldMapAction):
                    handler = WorldMapEventHandler(engine)
                elif isinstance(action, OpenCraftAction):
                    handler = CraftEventHandler(engine)
                elif isinstance(action, CloseMenuAction):
                    handler = MainGameEventHandler(engine)
                elif isinstance(action, LoadGameAction):
                    import save_manager

                    loaded = save_manager.load_engine(content, settings)
                    if loaded is not None:
                        engine = loaded
                        engine.message_log.add_message(strings["save_loaded"], "system")
                    handler = MainGameEventHandler(engine)
                elif isinstance(action, RestartAction):
                    return "restart"
                continue

            if action is not None:
                try:
                    engine.handle_action(action)
                except exceptions.NeedTarget as need:
                    # 需要指定目标/方向的技能：切输入模式，不消耗回合
                    effect = skills_module.SKILL_EFFECTS[need.skill["effect"]["type"]]
                    if effect.needs_direction:
                        handler = DirectionSelectEventHandler(engine, need.skill, need.slot)
                    else:
                        handler = TargetingEventHandler(engine, need.skill, need.slot)


def new_engine(content, settings, class_ids=None, previous_messages=None) -> Engine:
    if class_ids is None:
        class_ids = engine_default(content)
    engine = Engine(content, settings, class_ids)
    if previous_messages:
        engine.message_log.messages = previous_messages
    return engine


def engine_default(content) -> tuple:
    from content_loader import DEFAULT_CLASS_IDS

    return DEFAULT_CLASS_IDS


def run(lang: Optional[str], smoke_output: Optional[str] = None) -> None:
    settings = Settings.load()
    map_override = parse_arg_value(sys.argv, "--map")
    sidebar_override = parse_arg_value(sys.argv, "--sidebar")
    if map_override:
        settings.map_size = map_override
    if sidebar_override:
        settings.sidebar_size = sidebar_override
    # 语言优先级：--lang 参数 > 设置界面保存的语言 > 系统语言检测
    if lang in SUPPORTED_LANGS:
        resolved_lang = lang
    elif settings.lang in SUPPORTED_LANGS:
        resolved_lang = settings.lang
    else:
        resolved_lang = detect_lang()
    content = load_content(resolved_lang)

    selected: Optional[tuple] = None  # 本会话双职业；restart 后置 None 回主菜单
    while True:
        strings = content.strings
        tileset = build_tileset(content, settings)
        with tcod.context.new(
            columns=settings.total_cols,
            rows=settings.total_rows,
            tileset=tileset,
            title=strings[WINDOW_TITLE_KEY],
            vsync=True,
        ) as context:
            console = tcod.console.Console(settings.total_cols, settings.total_rows, order="F")

            if smoke_output:
                engine = new_engine(content, settings)  # 冒烟走默认双职业
                handler = MainGameEventHandler(engine)
                handler.on_render(console)
                _present(context, console)
                context.save_screenshot(smoke_output)
                print(f"冒烟截图已保存：{smoke_output}")
                return

            # ---- 开始界面（新开局 / 转世重修后回到这里）----
            if selected is None:
                choice, content = title_menu_loop(context, console, content, settings)
                strings = content.strings
                if choice == "quit":
                    return
                if choice == "resize":
                    continue  # 设置改了显示档位：重建窗口回主菜单
                if choice == "continue":
                    import save_manager

                    engine = save_manager.load_engine(content, settings)
                    if engine is None:  # 存档消失/版本旧：回主菜单
                        continue
                    engine.message_log.add_message(strings["save_loaded"], "system")
                    selected = ("§loaded§", None)  # 标记：引擎已就绪，跳过职业选择
                else:  # new：进入两段职业选择
                    selected = collect_class_ids(context, console, content, settings)
                    console.clear(fg=(236, 236, 240), bg=tuple(content.theme["background"]))
                    continue  # 选完职业，重建画面进入游戏

            # ---- 游戏会话 ----
            if selected and selected[0] == "§loaded§":
                pass  # 读档引擎已在上面就绪
            else:
                engine = new_engine(content, settings, selected)
                engine.message_log.add_message(
                    strings["class_chosen"].format(
                        primary=content.class_name(selected[0]),
                        secondary=content.class_name(selected[1]),
                    ),
                    "system",
                )

            _run_session(context, console, engine, content)
            selected = None  # 会话结束（退出存档后）回开始界面
            # 循环回到顶部：重建窗口；旧 context 已由 with 退出时关闭


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
