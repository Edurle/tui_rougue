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

import tile_types
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


def camera_origin(gamemap, player, map_cols: int, map_rows: int) -> Tuple[int, int]:
    """摄像机：视口左上角对应的地图坐标。玩家居中、贴边 clamp、小图居中。"""
    if gamemap.width <= map_cols:
        cam_x = -(map_cols - gamemap.width) // 2  # 地图小于视口：居中（负值）
    else:
        cam_x = max(0, min(player.x - map_cols // 2, gamemap.width - map_cols))
    if gamemap.height <= map_rows:
        cam_y = -(map_rows - gamemap.height) // 2
    else:
        cam_y = max(0, min(player.y - map_rows // 2, gamemap.height - map_rows))
    return cam_x, cam_y


def viewport_offset(engine: "Engine") -> Tuple[int, int]:
    """地图坐标 → 屏（视口）坐标的总平移：屏幕 = 地图 + offset（含震屏）。"""
    cam_x, cam_y = camera_origin(
        engine.gamemap, engine.player, engine.settings.map_cols, engine.settings.map_rows
    )
    shake_x, shake_y = engine.effects.shake_offset
    return -cam_x + shake_x, -cam_y + shake_y


# terrain id → 字符/明暗色查找表（按 theme 对象缓存，内容加载一次）
_TERRAIN_LUT_CACHE: list = []  # [theme 引用, (ch_lut, light_lut, dark_lut)]


def _terrain_luts(theme: dict):
    if _TERRAIN_LUT_CACHE and _TERRAIN_LUT_CACHE[0] is theme:
        return _TERRAIN_LUT_CACHE[1]
    n = tile_types.N_TERRAINS
    ch_lut = np.zeros(n, dtype=np.int32)
    light_lut = np.zeros((n, 3), dtype=np.float64)
    dark_lut = np.zeros((n, 3), dtype=np.float64)
    terrains = theme["terrains"]
    for tid, tdef in tile_types.TERRAIN_DEFS.items():
        cfg = terrains[tdef.key]
        ch_lut[tid] = ord(cfg["char"])
        light_lut[tid] = np.array(cfg["light"], dtype=np.float64)
        dark_lut[tid] = np.array(cfg["dark"], dtype=np.float64)
    luts = (ch_lut, light_lut, dark_lut)
    _TERRAIN_LUT_CACHE[:] = [theme, luts]
    return luts


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

    off_x, off_y = viewport_offset(engine)
    _render_map(console, engine, factors, off_x, off_y)
    _render_entities(console, engine, factors, off_x, off_y)
    _render_sidebar(console, engine)
    engine.effects.render(console, engine.settings.map_cols, engine.settings.map_rows, off_x, off_y)


def _render_map(
    console: tcod.console.Console, engine: "Engine", factors, off_x: int, off_y: int
) -> None:
    gamemap = engine.gamemap
    theme = engine.content.theme

    terrain = gamemap.terrain
    visible = gamemap.visible
    explored = gamemap.explored
    known = visible | explored
    light = visible
    dark = explored & ~visible

    ch_lut, light_lut, dark_lut = _terrain_luts(theme)
    ch = np.full(terrain.shape, 32, dtype=np.int32)
    ch[known] = ch_lut[terrain[known]]
    # 秘境石壁用邻接线框字符覆盖
    wall_known = (terrain == tile_types.T_WALL) & known
    ch[wall_known] = gamemap.wall_glyphs[wall_known]

    fg = np.zeros(terrain.shape + (3,), dtype=np.float64)
    scaled = factors[..., None]
    fg[light] = light_lut[terrain[light]] * scaled[light]
    fg[dark] = dark_lut[terrain[dark]]

    bg = np.zeros(terrain.shape + (3,), dtype=np.float64)
    bg[...] = np.array(theme["background"], dtype=np.float64)

    flash = engine.effects.hit_flash
    if flash > 0:
        fg[known] = fg[known] * (1 - flash) + np.array([255, 60, 60], dtype=np.float64) * flash
        bg[known] = bg[known] * (1 - flash * 0.6) + np.array([120, 16, 16], dtype=np.float64) * (flash * 0.6)

    sx, sy = gamemap.downstairs_xy
    if gamemap.in_bounds(sx, sy) and known[sx, sy]:
        ch[sx, sy] = art_codepoint("stairs_glow")
        if visible[sx, sy]:
            fg[sx, sy] = np.array(theme["stairs"]["light"], dtype=np.float64) * factors[sx, sy]
        else:
            fg[sx, sy] = np.array(theme["stairs"]["dark"], dtype=np.float64)

    ux, uy = gamemap.upstairs_xy
    if gamemap.in_bounds(ux, uy) and known[ux, uy]:
        ch[ux, uy] = art_codepoint("stairs_glow")
        if visible[ux, uy]:
            fg[ux, uy] = np.array(theme["stairs"]["up_light"], dtype=np.float64) * factors[ux, uy]
        else:
            fg[ux, uy] = np.array(theme["stairs"]["up_dark"], dtype=np.float64)

    width, height = terrain.shape
    map_cols = engine.settings.map_cols
    map_rows = engine.settings.map_rows
    x0, x1 = max(0, off_x), min(map_cols, off_x + width)
    y0, y1 = max(0, off_y), min(map_rows, off_y + height)
    src_x = x0 - off_x
    src_y = y0 - off_y
    span_x = x1 - x0
    span_y = y1 - y0
    region = console.rgb[x0:x1, y0:y1]
    region["ch"] = ch[src_x : src_x + span_x, src_y : src_y + span_y]
    region["fg"] = fg[src_x : src_x + span_x, src_y : src_y + span_y].astype(np.uint8)
    region["bg"] = bg[src_x : src_x + span_x, src_y : src_y + span_y].astype(np.uint8)


def _render_entities(
    console: tcod.console.Console, engine: "Engine", factors, off_x: int, off_y: int
) -> None:
    gamemap = engine.gamemap
    map_cols = engine.settings.map_cols
    map_rows = engine.settings.map_rows
    for entity in sorted(gamemap.entities, key=_render_order):
        if not gamemap.visible[entity.x, entity.y]:
            continue
        sx = entity.x + off_x
        sy = entity.y + off_y
        if not (0 <= sx < map_cols and 0 <= sy < map_rows):
            continue
        f = factors[entity.x, entity.y]
        color = tuple(int(c * f) for c in entity.color)
        glyph = chr(art_codepoint(entity.art)) if entity.art else entity.char
        console.print(sx, sy, glyph, fg=color)


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

    gamemap = engine.gamemap
    if gamemap.map_type == "world" and gamemap.region_ids is not None:
        region = content.regions[int(gamemap.region_ids[player.x, player.y])]
        location = content._(region["name"])
        landmark = gamemap.nearest_landmark(player.x, player.y)
        if landmark is not None:
            location += "·" + landmark["name"]
    else:
        location = strings["hud_floor"].format(
            region=content.region_name("zhongshanjing"), mountain=""
        )
    console.print(
        x,
        layout["floor_row"],
        location,
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


def _affix_summary(strings, item) -> str:
    """词条摘要（行囊菜单宽度足够时显示）：如 耗气-1 / 雷抗+35%。"""
    parts = []
    for affix in item.equipment.affixes:
        key = f"aff_{affix['id']}"
        if key in strings:
            parts.append(strings[key].format(v=affix["value"]))
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
            affixes = _affix_summary(strings, item)
            console.print(x + 2, row, f"{mark}{i + 1}) {slot_name} {item.name}", fg=COLOR_EQUIP)
            detail = (summary + " " + affixes).strip()
            if detail:
                console.print(
                    x + menu_width - len(detail) - 2, row, detail, fg=(150, 200, 160)
                )
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

    off_x, off_y = viewport_offset(engine)
    tx, ty = target.x + off_x, target.y + off_y
    if 0 <= tx < engine.settings.map_cols and 0 <= ty < engine.settings.map_rows:
        cell = console.rgb[tx, ty]
        console.print(tx, ty, chr(int(cell["ch"])), fg=(16, 12, 8), bg=(255, 226, 130))
    # 预计伤害按目标抗性折算后展示，抗性显著时附注
    damage = skills_module.compute_damage(engine.player, skill)
    damage = target.fighter.mitigate_incoming(damage, skill.get("tags", []))
    resist = skills_module.resist_description(engine.content, target, skill)
    info = strings["targeting_info"].format(
        name=target.name, hp=target.fighter.hp, damage=damage, resist=resist
    )
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
    off_x, off_y = viewport_offset(engine)
    lx, ly = landing[0] + off_x, landing[1] + off_y
    if 0 <= lx < engine.settings.map_cols and 0 <= ly < engine.settings.map_rows:
        cell = console.rgb[lx, ly]
        console.print(lx, ly, chr(int(cell["ch"])), fg=(255, 226, 130), bg=(90, 80, 40))
    console.print(
        engine.settings.content_x, 0,
        strings["direction_title"].format(skill=engine.content._(skill["name"]))[: engine.settings.content_w],
        fg=(255, 226, 130),
    )


def render_examine_card(console: tcod.console.Console, engine: "Engine", target) -> None:
    """查看模式属性卡：居中弹窗（属性/抗性/爪击/山海经典故）+ 目标格反色高亮。"""
    strings = engine.content.strings
    theme = engine.content.theme
    from fighter import RESIST_KINDS

    # 地图上目标格高亮（与瞄准态同款反色）
    off_x, off_y = viewport_offset(engine)
    tx, ty = target.x + off_x, target.y + off_y
    if 0 <= tx < engine.settings.map_cols and 0 <= ty < engine.settings.map_rows:
        cell = console.rgb[tx, ty]
        console.print(tx, ty, chr(int(cell["ch"])), fg=(16, 12, 8), bg=(255, 226, 130))

    fighter = target.fighter
    lore_lines = _wrap_cjk(target.lore, width=44)
    inner_lines = 3 + (1 if fighter else 0)
    resist_parts = [
        strings[f"resist_{kind}"].format(v=fighter.resistance(kind)).replace("+", "")
        for kind in RESIST_KINDS
        if fighter is not None and fighter.resistance(kind) > 0
    ]
    inner_lines += 1  # 抗性行：有则列项，无则显示"抗性：无"
    element_names = [strings[f"element_{t}"] for t in target.attack_tags]
    if element_names:
        inner_lines += 1
    if lore_lines:
        inner_lines += 1 + len(lore_lines)  # 空行 + lore 折行

    map_cols = engine.settings.map_cols
    map_rows = engine.settings.map_rows
    menu_width = min(50, map_cols - 2)
    menu_height = inner_lines + 4
    x = max(0, (map_cols - menu_width) // 2)
    y = max(0, (map_rows - menu_height) // 2)

    console.draw_frame(
        x=x,
        y=y,
        width=menu_width,
        height=menu_height,
        title=f" {target.name} · {strings['examine_title']} ",
        clear=True,
        fg=tuple(theme["ui"]["frame"]),
        bg=tuple(theme["background"]),
    )
    row = y + 2
    if fighter:
        console.print(
            x + 2,
            row,
            strings["examine_stats"].format(
                hp=fighter.hp,
                max_hp=fighter.max_hp,
                power=fighter.power,
                defense=fighter.defense,
                xp=fighter.xp_reward,
            )[: menu_width - 4],
            fg=COLOR_NAME,
        )
        row += 1
    if resist_parts:
        console.print(
            x + 2, row, strings["examine_resist"].format(resists=" ".join(resist_parts)),
            fg=(150, 200, 160),
        )
    else:
        console.print(x + 2, row, strings["examine_no_resist"], fg=(150, 150, 158))
    row += 1
    if element_names:
        console.print(
            x + 2,
            row,
            strings["examine_attack"].format(elements="、".join(element_names)),
            fg=(240, 160, 110),
        )
        row += 1
    if lore_lines:
        row += 1  # 典故前空一行
        for line in lore_lines:
            console.print(x + 2, row, line, fg=(168, 168, 178))
            row += 1


def _wrap_cjk(text: str, width: int) -> List[str]:
    """按显示列宽折行（本作 CJK 字符一格宽，直接按字符数折）。"""
    if not text:
        return []
    lines = []
    current = ""
    for ch in text:
        if len(current) + 1 > width:
            lines.append(current)
            current = ch
        else:
            current += ch
    if current:
        lines.append(current)
    return lines


def render_game_over(console: tcod.console.Console, engine: "Engine") -> None:
    strings = engine.content.strings
    theme = engine.content.theme
    text = strings["game_over_hint"]
    x = max(0, (engine.settings.map_cols - len(text)) // 2)
    console.print(x, engine.settings.map_rows - 2, text, fg=tuple(theme["hud"]["dead_tag"]))
