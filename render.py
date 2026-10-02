"""渲染：地图、实体、消息日志、HUD 与各类菜单覆盖层。

布局（80x45）：
- 第 0~41 行：地牢
- 第 42~43 行：消息日志
- 第 44 行：HUD（气血条 / 修为 / 层数）
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List

import tcod

from entity import Actor, Item

if TYPE_CHECKING:
    from engine import Engine

MAP_VIEW_HEIGHT = 42
HUD_Y = 44

STAIRS_LIGHT = (200, 180, 60)
STAIRS_DARK = (90, 80, 28)


def render_all(console: tcod.console.Console, engine: "Engine") -> None:
    gamemap = engine.gamemap
    strings = engine.content.strings

    for x in range(gamemap.width):
        for y in range(gamemap.height):
            tile = gamemap.tiles[x, y]
            if gamemap.visible[x, y]:
                console.print(x, y, str(tile["light_char"]), fg=tuple(int(c) for c in tile["light_fg"]))
            elif gamemap.explored[x, y]:
                console.print(x, y, str(tile["dark_char"]), fg=tuple(int(c) for c in tile["dark_fg"]))

    stairs_x, stairs_y = gamemap.downstairs_xy
    if gamemap.visible[stairs_x, stairs_y]:
        console.print(stairs_x, stairs_y, ">", fg=STAIRS_LIGHT)
    elif gamemap.explored[stairs_x, stairs_y]:
        console.print(stairs_x, stairs_y, ">", fg=STAIRS_DARK)

    for entity in sorted(gamemap.entities, key=_render_order):
        if not gamemap.visible[entity.x, entity.y]:
            continue
        console.print(entity.x, entity.y, entity.char, fg=entity.color)

    engine.message_log.render(console, start_y=MAP_VIEW_HEIGHT)
    _render_hud(console, engine)


def _render_order(entity) -> int:
    if isinstance(entity, Actor):
        return 0 if not entity.is_alive else 2
    if isinstance(entity, Item):
        return 1
    return 1


def _render_hud(console: tcod.console.Console, engine: "Engine") -> None:
    strings = engine.content.strings
    fighter = engine.player.fighter
    level = engine.player.level

    hp_text = strings["hud_hp"].format(hp=fighter.hp, max_hp=fighter.max_hp) if fighter else strings["hud_hp_dead"]
    console.print(1, HUD_Y, hp_text, fg=(220, 90, 90))

    if level:
        xp_text = strings["hud_level"].format(
            level=level.current_level, xp=level.current_xp, next=level.experience_to_next_level
        )
        console.print(24, HUD_Y, xp_text, fg=(220, 200, 120))

    floor_text = strings["hud_floor"].format(floor=engine.gamemap.floor_number)
    console.print(52, HUD_Y, floor_text, fg=(160, 200, 220))

    if not engine.player.is_alive:
        console.print(64, HUD_Y, strings["game_over_tag"], fg=(240, 90, 90))


def render_inventory_menu(console: tcod.console.Console, engine: "Engine") -> None:
    """行囊覆盖菜单：字母选择使用。"""
    strings = engine.content.strings
    inventory = engine.player.inventory
    items: List[Item] = list(inventory.items)

    menu_width = 40
    menu_height = len(items) + 4
    x = console.width // 2 - menu_width // 2
    y = console.height // 2 - menu_height // 2

    console.draw_frame(x=x, y=y, width=menu_width, height=menu_height, title=f" {strings['inventory_title']} ", clear=True, fg=(220, 210, 160), bg=(20, 18, 24))

    letters = "abcdefghij"
    for i, item in enumerate(items):
        letter = letters[i] if i < len(letters) else " "
        console.print(x + 2, y + 2 + i, f"{letter}) {item.name}", fg=item.color)


def render_game_over(console: tcod.console.Console, engine: "Engine") -> None:
    strings = engine.content.strings
    text = strings["game_over_hint"]
    x = console.width // 2 - len(text) // 2
    console.print(x, HUD_Y - 2, text, fg=(240, 110, 110))
