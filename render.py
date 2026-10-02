"""渲染：向量化地图（邻接墙+光照+脉动）、图块实体、特效层、右侧信息板。

布局由 engine.settings 动态决定（画面/信息板两档大中小独立调节）：
- 第 0~divider_col-1 列：地牢 map_cols x map_rows
- 第 divider_col 列：鎏金竖分隔线
- 其右：信息板四段自适应——属性区 → 技能区（页眉+8 槽）→ 装备区（5 槽）
  → 分隔线 + 事件日志；紧凑档（≤26 行）技能两列压缩、保日志 ≥5 行
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, List, Tuple

import numpy as np
import tcod

from entity import Actor, Item
from equipment import SLOT_ORDER
from settings import sidebar_layout
from tileset_art import art_codepoint

if TYPE_CHECKING:
    from engine import Engine

BAR_FILLED = "▓"
BAR_EMPTY = "░"

COLOR_NAME = (238, 238, 244)
COLOR_SKILL_READY = (255, 222, 130)
COLOR_SKILL_NOMP = (205, 95, 95)
COLOR_SKILL_LOCKED = (110, 110, 118)
COLOR_EQUIP = (182, 202, 222)
COLOR_HEADER = (222, 190, 120)


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


# ---- 信息板 ----


def _skill_state_color(engine, skill: dict) -> Tuple[int, int, int]:
    player = engine.player
    if skill["id"] not in player.learned_skills:
        return COLOR_SKILL_LOCKED
    import skills as skills_module

    if player.fighter.mp < skills_module.mp_cost(player, skill):
        return COLOR_SKILL_NOMP
    return COLOR_SKILL_READY


def _render_sidebar(console: tcod.console.Console, engine: "Engine") -> None:
    theme = engine.content.theme
    strings = engine.content.strings
    content = engine.content
    player = engine.player
    settings = engine.settings
    layout = sidebar_layout(settings.total_rows)

    frame_color = tuple(theme["ui"]["frame"])
    for y in range(settings.total_rows):
        console.print(settings.divider_col, y, "│", fg=frame_color)
    for x in range(settings.content_x, console.width):
        console.print(x, layout["divider"], "─", fg=frame_color)

    x = settings.content_x
    w = settings.content_w
    fighter = player.fighter
    level = player.level

    # 名字 + 职业页眉第一段
    console.print(x, 0, player.name, fg=COLOR_NAME)

    if fighter:
        hp_text = strings["hud_hp"].format(hp=fighter.hp, max_hp=fighter.max_hp)
        console.print(x, 1, hp_text, fg=tuple(theme["hud"]["hp"]))
        filled = round(w * fighter.hp / fighter.max_hp)
        console.print(x, 2, BAR_FILLED * filled, fg=tuple(theme["hud"]["hp"]))
        console.print(x + filled, 2, BAR_EMPTY * (w - filled), fg=(70, 52, 56))

        mp_text = strings["hud_mp"].format(mp=fighter.mp, max_mp=fighter.max_mp)
        console.print(x, layout["mp_row"], mp_text, fg=(120, 226, 232))
        if layout["mp_bar"]:
            filled = round(w * fighter.mp / max(1, fighter.max_mp))
            console.print(x, layout["mp_row"] + 1, BAR_FILLED * filled, fg=(120, 226, 232))
            console.print(
                x + filled, layout["mp_row"] + 1, BAR_EMPTY * (w - filled), fg=(50, 58, 66)
            )
    else:
        console.print(x, 1, strings["hud_hp_dead"], fg=tuple(theme["hud"]["dead_tag"]))

    if level:
        console.print(
            x,
            layout["level_row"],
            strings["hud_level"].format(
                level=level.current_level, xp=level.current_xp, next=level.experience_to_next_level
            ),
            fg=tuple(theme["hud"]["xp"]),
        )

    floor_number = engine.gamemap.floor_number
    console.print(
        x,
        layout["floor_row"],
        strings["hud_floor"].format(
            region=content.region_name_for_floor(floor_number),
            mountain=content.mountain_for_floor(floor_number),
        ),
        fg=tuple(theme["hud"]["floor"]),
    )

    _render_hints(console, engine, strings, theme, layout)
    _render_skills(console, engine, layout)
    _render_equipment(console, engine, layout)

    engine.message_log.render(console, start_y=layout["divider"] + 1)


def _render_hints(console, engine, strings, theme, layout) -> None:
    """上下文按键提示：紧凑档单行取最新，完整档两行。"""
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
    shown = hints[-2:]  # 最多两条：最新在下（hint_row），较早的在其上
    for i, (key, label) in enumerate(reversed(shown)):
        row = layout["hint_row"] - i
        console.print(content_x, row, key, fg=(255, 226, 130))
        console.print(content_x + 2, row, label, fg=hint_color)


def _render_skills(console, engine, layout) -> None:
    """技能区：页眉（职业·Tab·剩余点）+ 8 槽行（紧凑两列）。"""
    strings = engine.content.strings
    content = engine.content
    player = engine.player
    if not player.class_ids:
        return
    x = engine.settings.content_x
    page = engine.active_page
    class_id = player.class_ids[page]
    other_id = player.class_ids[1 - page]
    page_tpl = strings["hud_main_page"] if page == 0 else strings["hud_second_page"]
    header = page_tpl.format(name=content.class_name(class_id)) + "·" + strings[
        "hud_skills_points"
    ].format(points=player.skill_points)
    if not layout["compact"]:
        header += f"·{content.class_name(other_id)}"
    console.print(x, layout["skill_header"], header, fg=COLOR_HEADER)

    skills_list = content.skills_for_class(class_id)
    first = layout["skill_first"]
    for i, skill in enumerate(skills_list[:8]):
        name = content._(skill["name"])
        color = _skill_state_color(engine, skill)
        key = str(skill["slot"])
        if layout["skill_two_cols"]:
            row = first + i // 2
            col = x + (i % 2) * (engine.settings.content_w // 2)
            console.print(col, row, f"{key}{name}", fg=color)
        else:
            row = first + i
            import skills as skills_module

            cost = skills_module.mp_cost(player, skill)
            console.print(x, row, f"{key} {name}", fg=color)
            cost_text = strings["skill_mp_cost"].format(mp=cost)
            if skill["effect"].get("hp_cost"):
                cost_text += f"-{skill['effect']['hp_cost']}"
            console.print(
                x + engine.settings.content_w - len(cost_text) - 1, row, cost_text, fg=color
            )


def _render_equipment(console, engine, layout) -> None:
    """装备区：五槽（兵/甲/履/佩/冠）+ 件名 + 加成摘要。"""
    strings = engine.content.strings
    player = engine.player
    x = engine.settings.content_x
    equipment = player.equipment
    if equipment is None:
        return
    for i, slot in enumerate(SLOT_ORDER):
        row = layout["equip_first"] + i
        slot_name = strings[f"slot_{slot}"]
        item = equipment.slots.get(slot)
        if item is None:
            console.print(x, row, f"{slot_name} {strings['slot_empty']}", fg=COLOR_SKILL_LOCKED)
            continue
        summary = _bonus_summary(strings, item)
        console.print(x, row, f"{slot_name} {item.name}", fg=COLOR_EQUIP)
        if summary:
            console.print(
                x + engine.settings.content_w - len(summary) - 1, row, summary, fg=(150, 200, 160)
            )


def _bonus_summary(strings, item) -> str:
    parts = []
    gear = item.equipment
    bon_map = {"power": "bon_power", "defense": "bon_defense", "max_hp": "bon_max_hp", "max_mp": "bon_max_mp"}
    for key, skey in bon_map.items():
        value = gear.bonuses.get(key, 0)
        if value:
            parts.append(strings[skey].format(v=value))
    return " ".join(parts)


# ---- 覆盖层菜单 ----


def render_inventory_menu(console: tcod.console.Console, engine: "Engine", cursor: int = -1) -> None:
    """行囊覆盖菜单：物品区（字母 使用/装备）+ 装备区（数字 卸下）。居中于地图区。"""
    strings = engine.content.strings
    theme = engine.content.theme
    items: List[Item] = list(engine.player.inventory.items)
    equipment = engine.player.equipment
    slot_items = [equipment.slots.get(slot) if equipment else None for slot in SLOT_ORDER]

    map_cols = engine.settings.map_cols
    map_rows = engine.settings.map_rows
    menu_width = min(40, map_cols - 2)
    menu_height = len(items) + len(SLOT_ORDER) + 5
    x = max(0, (map_cols - menu_width) // 2)
    y = max(0, (map_rows - menu_height) // 2)

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
    row = y + 2
    for i, item in enumerate(items):
        letter = letters[i] if i < len(letters) else " "
        mark = ">" if cursor == i else " "
        color = item.color if item.equipment is None else COLOR_EQUIP
        console.print(x + 2, row, f"{mark}{letter}) {item.name}", fg=tuple(color))
        row += 1
    row += 1
    console.print(x + 2, row, strings["hud_inventory"].format(
        count=len(items), cap=engine.player.inventory.capacity), fg=(160, 160, 170))
    row += 1
    for i, item in enumerate(slot_items):
        slot_name = strings[f"slot_{SLOT_ORDER[i]}"]
        if item is None:
            text = f" {i + 1}) {slot_name} {strings['slot_empty']}"
            console.print(x + 2, row, text, fg=COLOR_SKILL_LOCKED)
        else:
            mark = ">" if cursor == len(items) + i else " "
            summary = _bonus_summary(strings, item)
            console.print(x + 2, row, f"{mark}{i + 1}) {slot_name} {item.name}", fg=COLOR_EQUIP)
            if summary:
                console.print(x + menu_width - len(summary) - 2, row, summary, fg=(150, 200, 160))
        row += 1


def render_skill_learn_menu(console: tcod.console.Console, engine: "Engine", page: int, cursor: int) -> None:
    """参悟界面（K）：双职业分页技能树；✓ 已学 / · 可学 / × 前置未齐。"""
    strings = engine.content.strings
    theme = engine.content.theme
    content = engine.content
    player = engine.player
    class_id = player.class_ids[page]
    skills_list = content.skills_for_class(class_id)

    map_cols = engine.settings.map_cols
    map_rows = engine.settings.map_rows
    menu_width = min(44, map_cols - 2)
    menu_height = len(skills_list) + 5
    x = max(0, (map_cols - menu_width) // 2)
    y = max(0, (map_rows - menu_height) // 2)

    console.draw_frame(
        x=x,
        y=y,
        width=menu_width,
        height=menu_height,
        title=f" {strings['learn_title']} ",
        clear=True,
        fg=tuple(theme["ui"]["frame"]),
        bg=tuple(theme["background"]),
    )
    header = f"{content.class_name(class_id)} · {strings['hud_skills_points'].format(points=player.skill_points)}"
    console.print(x + 2, y + 1, header, fg=COLOR_HEADER)

    row = y + 3
    for i, skill in enumerate(skills_list):
        name = content._(skill["name"])
        learned = skill["id"] in player.learned_skills
        missing = [
            content._(content.skills[r]["name"])
            for r in skill.get("requires", [])
            if r not in player.learned_skills
        ]
        mark = ">" if i == cursor else " "
        if learned:
            state = strings["learn_mark_known"]
            color = COLOR_SKILL_READY
            detail = ""
        elif not missing:
            state = strings["learn_mark_ready"]
            color = COLOR_NAME
            cost = int(skill.get("cost", 1))
            detail = f" {cost}pt" if cost > 1 else ""
        else:
            state = strings["learn_mark_locked"]
            color = COLOR_SKILL_LOCKED
            detail = " " + strings["learn_req"].format(names="、".join(missing))
        line = f"{mark}{skill['slot']} {state} {name}{detail}"
        console.print(x + 2, row, line[: menu_width - 3], fg=color)
        row += 1


def render_class_select(console, content, settings, primary, cursor) -> None:
    """开局双职业选择界面（两段）。"""
    strings = content.strings
    theme = content.theme
    title = (
        strings["class_select_secondary"] if primary else strings["class_select_primary"]
    )
    class_ids = list(content.classes.keys())
    shown = class_ids if primary is None else [c for c in class_ids if c != primary]

    map_cols = settings.map_cols
    map_rows = settings.map_rows
    menu_width = min(46, map_cols - 2)
    menu_height = len(shown) + 5
    x = max(0, (map_cols - menu_width) // 2)
    y = max(0, (map_rows - menu_height) // 2)

    console.draw_frame(
        x=x,
        y=y,
        width=menu_width,
        height=menu_height,
        title=f" {title} ",
        clear=True,
        fg=tuple(theme["ui"]["frame"]),
        bg=tuple(theme["background"]),
    )
    if primary is not None:
        chosen = f"{strings['hud_main_page'].format(name=content.class_name(primary))}"
        console.print(x + 2, y + 1, chosen, fg=COLOR_HEADER)

    row = y + 3
    for i, cid in enumerate(shown):
        cdef = content.classes[cid]
        mark = "►" if i == cursor else " "
        stats = strings["class_select_stats"].format(
            hp=cdef["hp"], pow=cdef["power"], **{"def": cdef["defense"], "mp": cdef["mp"]}
        )
        name = content.class_name(cid)
        color = COLOR_NAME if i == cursor else (150, 150, 158)
        console.print(x + 2, row, f"{mark} {name}", fg=color)
        console.print(x + 16, row, stats, fg=(160, 190, 200) if i == cursor else (120, 130, 138))
        row += 1
    # 选中项简介
    if shown:
        desc = content._(content.classes[shown[cursor % len(shown)]]["desc"])
        console.print(x + 2, y + menu_height - 2, desc[: menu_width - 4], fg=(170, 170, 180))


def render_targeting_overlay(console: tcod.console.Console, engine: "Engine", target, skill: dict) -> None:
    """瞄准态：目标格反色高亮 + 信息板顶部目标信息。"""
    strings = engine.content.strings
    import skills as skills_module

    tx, ty = target.x, target.y
    if 0 <= tx < engine.settings.map_cols and 0 <= ty < engine.settings.map_rows:
        cell = console.rgb[tx, ty]
        console.print(tx, ty, chr(int(cell["ch"])), fg=(16, 12, 8), bg=(255, 226, 130))
    damage = skills_module.compute_damage(engine.player, skill)
    info = strings["targeting_info"].format(name=target.name, hp=target.fighter.hp, damage=damage)
    console.print(engine.settings.content_x, 0, info[: engine.settings.content_w], fg=(255, 226, 130))
    console.print(
        engine.settings.content_x, 1,
        strings["targeting_title"].format(skill=engine.content._(skill["name"]))[: engine.settings.content_w],
        fg=(170, 170, 180),
    )


def render_direction_overlay(console: tcod.console.Console, engine: "Engine", skill: dict, dx: int, dy: int) -> None:
    """择向态：落点预览高亮 + 信息板提示。"""
    strings = engine.content.strings
    import skills as skills_module

    landing = skills_module.teleport_landing(engine, engine.player, skill, dx, dy)
    lx, ly = landing
    if 0 <= lx < engine.settings.map_cols and 0 <= ly < engine.settings.map_rows:
        cell = console.rgb[lx, ly]
        console.print(lx, ly, chr(int(cell["ch"])), fg=(255, 226, 130), bg=(90, 80, 40))
    console.print(
        engine.settings.content_x, 0,
        strings["direction_title"].format(skill=engine.content._(skill["name"]))[: engine.settings.content_w],
        fg=(255, 226, 130),
    )


def render_game_over(console: tcod.console.Console, engine: "Engine") -> None:
    strings = engine.content.strings
    theme = engine.content.theme
    text = strings["game_over_hint"]
    x = max(0, (engine.settings.map_cols - len(text)) // 2)
    console.print(x, engine.settings.map_rows - 2, text, fg=tuple(theme["hud"]["dead_tag"]))
