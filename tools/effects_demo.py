"""特效演示帧：注入全部特效状态后截图，验证动效渲染。"""

from __future__ import annotations

import sys
from pathlib import Path

import tcod

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from content_loader import load_content  # noqa: E402
from engine import Engine  # noqa: E402
from input_handlers import MainGameEventHandler  # noqa: E402
from main import TILE_SIZE, WINDOW_COLUMNS, WINDOW_ROWS, load_tileset  # noqa: E402
from tileset_art import inject_art_tiles  # noqa: E402


def main() -> None:
    content = load_content("zh_CN")
    engine = Engine(content)
    player = engine.player
    gamemap = engine.gamemap
    fx = engine.effects

    px, py = player.x, player.y
    monster = content.build_monster("gudiao", gamemap, px + 4, py)
    fx.spawn_damage(px + 4, py, 4, is_player_victim=False)
    fx.spawn_damage(px, py, 6, is_player_victim=True)
    fx.spawn_heal(px - 3, py + 2, 12)
    fx.spawn_notice(px + 4, py)
    fx.spawn_level_up(px, py)
    fx.spawn_pickup(px - 5, py - 3)
    bolt_color = tuple(content.theme["messages"]["lightning"])
    fx.spawn_lightning(px + 7, py - 2, 14, bolt_color)

    tileset, _ = load_tileset()
    inject_art_tiles(tileset, TILE_SIZE)
    with tcod.context.new(
        columns=WINDOW_COLUMNS, rows=WINDOW_ROWS, tileset=tileset, title="effects demo"
    ) as context:
        console = tcod.console.Console(WINDOW_COLUMNS, WINDOW_ROWS, order="F")
        handler = MainGameEventHandler(engine)
        handler.on_render(console)
        context.present(console, keep_aspect=True, integer_scaling=True)
        out = str(Path(__file__).parent / "effects_demo.png")
        context.save_screenshot(out)
        print(f"特效演示帧已保存：{out}")


if __name__ == "__main__":
    main()
