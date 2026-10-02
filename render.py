"""渲染：向量化地图（邻接墙+光照+脉动）、图块实体、特效层、右侧信息板。

布局由 engine.settings 动态决定（画面/信息板两档大中小独立调节）：
- 第 0~divider_col-1 列：地牢 map_cols x map_rows
- 第 divider_col 列：鎏金竖分隔线
- 其右：信息板——属性区（气血条/修为/层数/行囊）+ 分隔线 + 事件日志
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, List, Tuple

import numpy as np
import tcod

from entity import Actor, Item
from tileset_art import art_codepoint

if TYPE_CHECKING:
    from engine import Engine

BAR_FILLED = "▓"
BAR_EMPTY = "░"


def render_all(console: tcod.console.Console, engine: "Engine") -> None:
    theme = engine.content.theme
    console.clear(fg=(236, 236, 240), bg=tuple(theme["background"]))

    gamemap = engine.gamemap
    player = engine.player
    lighting_cfg = theme["lighting"]
    effects_cfg = theme["effects"]
    factors = gamemap.lighting_factors(
        player.x, player.y, lighting_cfg["inner_radius"], lighting_cfg["edge_falloff"]
    )
    t = time.perf_counter()
    pulse = 1.0 + effects_cfg["light_pulse_amplitude"] * np.sin(t * effects_cfg["light_pulse_speed"])
    factors = np.clip(factors * pulse, 0.0, 1.0)

    shake_x, shake_y = engine.effects.shake_offset
    _render_map(console, engine, factors, shake_x, shake_y)
    _render_entities(console, engine, factors, shake_x, shake_y)
    _render_sidebar(console, engine)
    engine.effects.render(console, engine.settings.map_cols, engine.settings.map_rows)


def _render_map(console: tcod.console.Console, engine: "Engine", factors, shake_x: int, shake_y: int) -> None:
    gamemap = engine.gamemap
    theme = engine.content.theme

    walkable = gamemap.tiles["walkable"]
    visible = gamemap.visible
    explored = gamemap.explored
    known = visible | explored

    floor_char = ord(theme["tiles"]["floor_char"])
    ch = np.full(walkable.shape, 32, dtype=np.int32)
    ch[walkable & known] = floor_char
    ch[~walkable & known] = gamemap.wall_glyphs[~walkable & known]

    fg = np.zeros(walkable.shape + (3,), dtype=np.float64)
    light = visible
    dark = explored & ~visible
    floor_l = np.array(theme["tiles"]["floor_light"], dtype=np.float64)
    wall_l = np.array(theme["tiles"]["wall_light"], dtype=np.float64)
    scaled = factors[..., None]
    fg[light & walkable] = floor_l * scaled[light & walkable]
    fg[light & ~walkable] = wall_l * scaled[light & ~walkable]
    fg[dark & walkable] = np.array(theme["tiles"]["floor_dark"], dtype=np.float64)
    fg[dark & ~walkable] = np.array(theme["tiles"]["wall_dark"], dtype=np.float64)

    bg = np.zeros(walkable.shape + (3,), dtype=np.float64)
    bg[...] = np.array(theme["background"], dtype=np.float64)

    flash = engine.effects.hit_flash
    if flash > 0:
        fg[known] = fg[known] * (1 - flash) + np.array([255, 60, 60], dtype=np.float64) * flash
        bg[known] = bg[known] * (1 - flash * 0.6) + np.array([120, 16, 16], dtype=np.float64) * (flash * 0.6)

    sx, sy = gamemap.downstairs_xy
    if known[sx, sy]:
        ch[sx, sy] = art_codepoint("stairs_glow")
        if visible[sx, sy]:
            fg[sx, sy] = np.array(theme["stairs"]["light"], dtype=np.float64) * factors[sx, sy]
        else:
            fg[sx, sy] = np.array(theme["stairs"]["dark"], dtype=np.float64)

    ux, uy = gamemap.upstairs_xy
    if known[ux, uy]:
        ch[ux, uy] = art_codepoint("stairs_glow")
        if visible[ux, uy]:
            fg[ux, uy] = np.array(theme["stairs"]["up_light"], dtype=np.float64) * factors[ux, uy]
        else:
            fg[ux, uy] = np.array(theme["stairs"]["up_dark"], dtype=np.float64)

    width, height = walkable.shape
    map_cols = engine.settings.map_cols
    map_rows = engine.settings.map_rows
    x0, x1 = max(0, shake_x), min(map_cols, width + shake_x)
    y0, y1 = max(0, shake_y), min(map_rows, height + shake_y)
    src_x = x0 - shake_x
    src_y = y0 - shake_y
    span_x = x1 - x0
    span_y = y1 - y0
    region = console.rgb[x0:x1, y0:y1]
    region["ch"] = ch[src_x : src_x + span_x, src_y : src_y + span_y]
    region["fg"] = fg[src_x : src_x + span_x, src_y : src_y + span_y].astype(np.uint8)
    region["bg"] = bg[src_x : src_x + span_x, src_y : src_y + span_y].astype(np.uint8)


def _render_entities(console: tcod.console.Console, engine: "Engine", factors, shake_x: int, shake_y: int) -> None:
    gamemap = engine.gamemap
    for entity in sorted(gamemap.entities, key=_render_order):
        if not gamemap.visible[entity.x, entity.y]:
            continue
        f = factors[entity.x, entity.y]
        color = tuple(int(c * f) for c in entity.color)
        glyph = chr(art_codepoint(entity.art)) if entity.art else entity.char
        console.print(entity.x + shake_x, entity.y + shake_y, glyph, fg=color)


def _render_order(entity) -> int:
    if isinstance(entity, Actor):
        return 0 if not entity.is_alive else 2
    if isinstance(entity, Item):
        return 1
    return 1


def _render_sidebar(console: tcod.console.Console, engine: "Engine") -> None:
    theme = engine.content.theme
    strings = engine.content.strings
    player = engine.player
    settings = engine.settings

    frame_color = tuple(theme["ui"]["frame"])
    for y in range(settings.total_rows):
        console.print(settings.divider_col, y, "│", fg=frame_color)
    for x in range(settings.content_x, console.width):
        console.print(x, settings.divider_row, "─", fg=frame_color)

    x = settings.content_x
    fighter = player.fighter
    level = player.level

    console.print(x, 0, player.name, fg=(238, 238, 244))
    if not player.is_alive:
        tag = strings["game_over_tag"]
        console.print(console.width - len(tag) - 1, 0, tag, fg=tuple(theme["hud"]["dead_tag"]))

    if fighter:
        hp_text = strings["hud_hp"].format(hp=fighter.hp, max_hp=fighter.max_hp)
        console.print(x, 1, hp_text, fg=tuple(theme["hud"]["hp"]))
        filled = round(settings.content_w * fighter.hp / fighter.max_hp)
        console.print(x, 2, BAR_FILLED * filled, fg=tuple(theme["hud"]["hp"]))
        console.print(x + filled, 2, BAR_EMPTY * (settings.content_w - filled), fg=(70, 52, 56))
    else:
        console.print(x, 1, strings["hud_hp_dead"], fg=tuple(theme["hud"]["dead_tag"]))

    if level:
        console.print(
            x,
            4,
            strings["hud_level"].format(
                level=level.current_level, xp=level.current_xp, next=level.experience_to_next_level
            ),
            fg=tuple(theme["hud"]["xp"]),
        )

    floor_number = engine.gamemap.floor_number
    console.print(
        x,
        7,
        strings["hud_floor"].format(
            region=engine.content.region_name_for_floor(floor_number),
            mountain=engine.content.mountain_for_floor(floor_number),
        ),
        fg=tuple(theme["hud"]["floor"]),
    )

    inventory = player.inventory
    if inventory:
        console.print(
            x, 9, strings["hud_inventory"].format(count=len(inventory.items), cap=inventory.capacity), fg=(180, 180, 190)
        )

    _render_hints(console, engine, strings, theme)

    engine.message_log.render(console, start_y=settings.divider_row + 1)


def _render_hints(console: tcod.console.Console, engine: "Engine", strings, theme) -> None:
    """上下文按键提示：站在山径/可拾取/低血有药时，在属性区空行动态显示。"""
    player = engine.player
    gamemap = engine.gamemap
    here = (player.x, player.y)

    hints = []
    if here == gamemap.downstairs_xy:
        hints.append((">", strings["hint_descend"]))
    elif here == gamemap.upstairs_xy and gamemap.floor_number > 1:
        hints.append(("<", strings["hint_ascend"]))
    item_here = gamemap.get_item_at(player.x, player.y)
    if item_here is not None:
        hints.append(("G", strings["hint_pickup"].format(item=item_here.name)))
    fighter = player.fighter
    if fighter and 0 < fighter.hp / fighter.max_hp < 0.45:
        from consumable import HealConsumable

        if any(getattr(i, "consumable", None).__class__ is HealConsumable for i in player.inventory.items):
            hints.append(("I", strings["hint_heal"]))

    hint_color = tuple(theme["ui"]["frame"])
    content_x = engine.settings.content_x
    for i, (key, label) in enumerate(reversed(hints[:3])):
        row = 10 - i * 2  # 行 10/8/6，最新的提示最靠下
        console.print(content_x, row, key, fg=(255, 226, 130))
        console.print(content_x + 2, row, label, fg=hint_color)


def render_inventory_menu(console: tcod.console.Console, engine: "Engine") -> None:
    """行囊覆盖菜单：字母选择使用。居中于地图区。"""
    strings = engine.content.strings
    theme = engine.content.theme
    items: List[Item] = list(engine.player.inventory.items)

    map_cols = engine.settings.map_cols
    map_rows = engine.settings.map_rows
    menu_width = min(40, map_cols - 4)
    menu_height = len(items) + 4
    x = (map_cols - menu_width) // 2
    y = (map_rows - menu_height) // 2

    console.draw_frame(
        x=x,
        y=y,
        width=menu_width,
        height=menu_height,
        title=f" {strings['inventory_title']} ",
        clear=True,
        fg=tuple(theme["ui"]["frame"]),
        bg=tuple(theme["background"]),
    )

    letters = "abcdefghij"
    for i, item in enumerate(items):
        letter = letters[i] if i < len(letters) else " "
        console.print(x + 2, y + 2 + i, f"{letter}) {item.name}", fg=item.color)


def render_game_over(console: tcod.console.Console, engine: "Engine") -> None:
    strings = engine.content.strings
    theme = engine.content.theme
    text = strings["game_over_hint"]
    x = max(0, (engine.settings.map_cols - len(text)) // 2)
    console.print(x, engine.settings.map_rows - 2, text, fg=tuple(theme["hud"]["dead_tag"]))
