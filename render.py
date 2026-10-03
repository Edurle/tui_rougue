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


# terrain id → 字符/明暗色查找表（按 theme+配色主题缓存，内容加载一次）
_TERRAIN_LUT_CACHE: dict = {}  # (id(theme), theme_key) -> (ch_lut, light_lut, dark_lut)


def _terrain_luts(theme: dict, palette_key=None):
    cache_key = (id(theme), palette_key)
    if cache_key in _TERRAIN_LUT_CACHE:
        return _TERRAIN_LUT_CACHE[cache_key]
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
    # 秘境配色主题：覆盖地面/石壁的明暗色
    palette = theme.get("realm_themes", {}).get(palette_key) if palette_key else None
    if palette is not None:
        light_lut[tile_types.T_FLOOR] = np.array(palette["floor_light"], dtype=np.float64)
        dark_lut[tile_types.T_FLOOR] = np.array(palette["floor_dark"], dtype=np.float64)
        light_lut[tile_types.T_WALL] = np.array(palette["wall_light"], dtype=np.float64)
        dark_lut[tile_types.T_WALL] = np.array(palette["wall_dark"], dtype=np.float64)
    luts = (ch_lut, light_lut, dark_lut)
    _TERRAIN_LUT_CACHE[cache_key] = luts
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

    ch_lut, light_lut, dark_lut = _terrain_luts(theme, gamemap.theme_key)
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
    if gamemap.map_type == "realm" and gamemap.realm_id:
        location = strings["hud_realm"].format(
            realm=content.realm_name(gamemap.realm_id), depth=gamemap.realm_depth
        )
    elif gamemap.map_type == "world" and gamemap.region_ids is not None:
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
    if gamemap.map_type == "world":
        gate = gamemap.get_realm_gate_at(*here)
        if gate is not None:
            if "sealed" not in gate.tags:
                hints.append((">", strings["hint_enter_realm"].format(name=gate.name)))
    else:
        if here == gamemap.downstairs_xy:
            hints.append((">", strings["hint_descend"]))
        elif here == gamemap.upstairs_xy:
            if gamemap.realm_depth <= 1:
                hints.append(("<", strings["hint_realm_exit"]))
            else:
                hints.append(("<", strings["hint_realm_ascend"]))
    item_here = gamemap.get_item_at(player.x, player.y)
    if item_here is not None:
        hints.append(("G", strings["hint_pickup"].format(item=item_here.name)))
    else:
        node_here = gamemap.get_resource_node_at(player.x, player.y)
        if node_here is not None:
            hints.append(("G", strings["hint_gather"].format(name=node_here.name)))
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


def render_inventory_menu(console: tcod.console.Console, engine: "Engine", handler=None) -> None:
    """行囊覆盖菜单：物品区（滚动窗口，字母 使用/装备）+ 装备区（数字 卸下）。

    物品无上限：超出视口时按光标滚动，字母 a-j 映射到当前可视的前十件。
    """
    strings = engine.content.strings
    theme = engine.content.theme
    items: List[Item] = list(engine.player.inventory.items)
    equipment = engine.player.equipment
    slot_items = [equipment.slots.get(slot) if equipment else None for slot in SLOT_ORDER]

    map_cols = engine.settings.map_cols
    map_rows = engine.settings.map_rows
    # 菜单总高上限：装备区 5 行 + 计数行 + 边框 4 行 + 至少 3 行物品
    max_listed = max(3, map_rows - 5 - 1 - 4 - 3)
    listed = min(len(items), max_listed)
    scroll = 0
    cursor = -1
    if handler is not None:
        cursor = handler.cursor
        scroll = handler.list_scroll(items, listed)

    menu_width = min(40, map_cols - 2)
    menu_height = listed + len(SLOT_ORDER) + 5
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
    for i in range(listed):
        global_index = scroll + i
        item = items[global_index]
        letter = letters[i] if i < len(letters) else " "
        mark = ">" if cursor == global_index else " "
        # 滚动指示：窗口上方还有更多
        if i == 0 and scroll > 0:
            mark = "↑"
        if i == listed - 1 and scroll + listed < len(items):
            letter = letter if letter != " " else "↓"
        color = item.color if item.equipment is None else COLOR_EQUIP
        label = item.name + (f"×{item.stack}" if item.is_material and item.stack > 1 else "")
        console.print(x + 2, row, f"{mark}{letter}) {label}", fg=tuple(color))
        row += 1
    row += 1
    console.print(x + 2, row, strings["hud_inventory"].format(count=len(items)), fg=(160, 160, 170))
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
    shown = class_ids if primary is not None else [c for c in class_ids if c != primary]

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


# ---- 开始界面 / 设置界面 ----


def render_title_menu(console, content, settings, cursor: int, has_save: bool) -> None:
    """开始界面：标题 + 主菜单（新游历/继续游历/设置/离开）。"""
    strings = content.strings
    theme = content.theme

    console.clear(fg=(236, 236, 240), bg=tuple(theme["background"]))
    map_cols = settings.map_cols
    map_rows = settings.map_rows

    # 标题区：山形装饰 + 游名 + 副标题
    center_x = map_cols // 2
    title = strings["window_title"]
    tagline = strings["title_menu_tagline"]
    peak_line = "▲▲▲▲▲▲▲▲▲"
    console.print(max(0, center_x - len(peak_line) // 2), max(2, map_rows // 2 - 7), peak_line, fg=(122, 202, 190))
    console.print(max(0, center_x - len(title) // 2), max(3, map_rows // 2 - 6), title, fg=(255, 222, 130))
    console.print(max(0, center_x - len(tagline) // 2), max(4, map_rows // 2 - 5), tagline, fg=(150, 150, 160))

    items = ("new", "continue", "settings", "quit")
    labels = {
        "new": strings["title_menu_new"],
        "continue": strings["title_menu_continue"],
        "settings": strings["title_menu_settings"],
        "quit": strings["title_menu_quit"],
    }
    enabled = {"new": True, "continue": has_save, "settings": True, "quit": True}

    row = map_rows // 2 + 1
    for i, item in enumerate(items):
        mark = "►" if i == cursor else " "
        active = enabled[item]
        color = COLOR_NAME if (i == cursor and active) else (110, 110, 118)
        console.print(center_x - 10, row, f"{mark} {labels[item]}", fg=color)
        row += 2
    hint = strings["title_menu_hint"]
    console.print(max(0, center_x - len(hint) // 2), map_rows - 2, hint, fg=(130, 130, 140))


def render_settings_menu(console, content, settings, cursor: int) -> None:
    """设置界面：语言/画面/信息板（←→ 即时调整），Esc 返回。"""
    strings = content.strings
    theme = content.theme

    console.clear(fg=(236, 236, 240), bg=tuple(theme["background"]))
    map_cols = settings.map_cols
    map_rows = settings.map_rows

    menu_width = min(40, map_cols - 4)
    menu_height = 10
    x = max(0, (map_cols - menu_width) // 2)
    y = max(0, (map_rows - menu_height) // 2)
    console.draw_frame(
        x=x, y=y, width=menu_width, height=menu_height,
        title=f" {strings['settings_headline']} ",
        clear=True,
        fg=tuple(theme["ui"]["frame"]),
        bg=tuple(theme["background"]),
    )

    current_lang = settings.lang or content.lang
    rows = [
        (strings["settings_lang"], strings.get(f"lang_{current_lang}", current_lang)),
        (strings["settings_map"], strings[f"size_{settings.map_size}"]),
        (strings["settings_sidebar"], strings[f"size_{settings.sidebar_size}"]),
        (strings["settings_back"], ""),
    ]
    row = y + 2
    for i, (label, value) in enumerate(rows):
        mark = "►" if i == cursor else " "
        color = COLOR_NAME if i == cursor else (150, 150, 158)
        console.print(x + 2, row, f"{mark} {label}"[: menu_width - 11], fg=color)
        if value:
            value_color = (122, 202, 190) if i == cursor else (140, 140, 150)
            console.print(x + menu_width - len(value) - 3, row, value, fg=value_color)
        row += 1
    # 操作提示 + 已保存（截断保护）
    console.print(x + 2, y + menu_height - 3, strings["settings_hint"][: menu_width - 4], fg=(130, 130, 140))
    console.print(x + 2, y + menu_height - 2, strings["settings_saved"][: menu_width - 4], fg=(120, 200, 160))


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


def _assess_threat(player, target) -> str:
    """按双方攻防估算互换刀数：low=稳操胜券 / mid=五五开 / high=凶多吉少。"""
    from math import ceil

    my_dmg = max(1, player.fighter.power - target.fighter.defense)
    its_dmg = max(0, target.fighter.power - player.fighter.defense)
    my_hits = ceil(target.fighter.hp / my_dmg)
    its_hits = ceil(player.fighter.hp / its_dmg) if its_dmg > 0 else 99
    ratio = its_hits / max(1, my_hits)
    if ratio < 0.9:
        return "high"
    if ratio < 1.4:
        return "mid"
    return "low"


_KIND_TAG_COLORS = {"boss": (255, 222, 130)}


def _kind_badges(strings, target) -> list:
    """种类标签（首领/鸟/兽/蛇/龙），按已知 tags 映射。"""
    badges = []
    for tag in ("boss", "dragon", "serpent", "bird", "beast"):
        if tag in getattr(target, "tags", []):
            key = f"kind_{tag}"
            if key in strings:
                badges.append((strings[key], _KIND_TAG_COLORS.get(tag, (160, 172, 186))))
    return badges


def _target_corner_markers(console, tx: int, ty: int, map_cols: int, map_rows: int) -> None:
    """当前查看目标的四角框（比反色更醒目，不越界）。"""
    color = (255, 226, 130)
    corners = (
        (tx - 1, ty - 1, "┌"), (tx + 1, ty - 1, "┐"),
        (tx - 1, ty + 1, "└"), (tx + 1, ty + 1, "┘"),
    )
    for cx, cy, glyph in corners:
        if 0 <= cx < map_cols and 0 <= cy < map_rows:
            console.print(cx, cy, glyph, fg=color)


def render_examine_card(console, engine, target, handler=None) -> None:
    """查看模式属性卡：目标清单 + 血条/威胁/距离 + 抗性/爪击 + 典故（L 展开）。

    卡片自动避开目标格；目标格反色 + 四角框高亮。
    """
    strings = engine.content.strings
    theme = engine.content.theme
    from fighter import RESIST_KINDS

    map_cols = engine.settings.map_cols
    map_rows = engine.settings.map_rows

    # 目标格高亮（反色 + 四角框），坐标换算到视口
    off_x, off_y = viewport_offset(engine)
    tx, ty = target.x + off_x, target.y + off_y
    if 0 <= tx < map_cols and 0 <= ty < map_rows:
        cell = console.rgb[tx, ty]
        console.print(tx, ty, chr(int(cell["ch"])), fg=(16, 12, 8), bg=(255, 226, 130))
        _target_corner_markers(console, tx, ty, map_cols, map_rows)

    fighter = target.fighter
    show_lore = getattr(handler, "show_lore", True) if handler is not None else True
    lore_lines = _wrap_cjk(target.lore, width=32) if show_lore else []

    # 内容行数
    inner = 3  # 气血行 + 属性行 + 威胁行
    resist_parts = [
        strings[f"resist_{kind}"].format(v=fighter.resistance(kind)).replace("+", "")
        for kind in RESIST_KINDS
        if fighter is not None and fighter.resistance(kind) > 0
    ]
    inner += 1  # 抗性行
    element_names = [strings[f"element_{t}"] for t in target.attack_tags]
    if element_names:
        inner += 1
    if lore_lines:
        inner += 1 + len(lore_lines)  # 空行 + lore 折行
    else:
        inner += 1  # [L] 典故提示行

    menu_width = min(36, map_cols - 2)
    menu_height = inner + 4
    # 避让目标格：居中若遮挡则左右让位，再不行下移
    x = max(0, (map_cols - menu_width) // 2)
    y = max(0, (map_rows - menu_height) // 2)
    if x - 1 <= tx < x + menu_width + 1 and y - 1 <= ty < y + menu_height + 1:
        x = max(0, tx - menu_width - 2)  # 目标左侧
        if x + menu_width > map_cols - 1 or (x - 1 <= tx and tx < x + menu_width + 1):
            x = min(map_cols - menu_width - 1, tx + 3)  # 目标右侧
        if x < 0 or (x - 1 <= tx and tx < x + menu_width + 1):
            x = max(0, (map_cols - menu_width) // 2)
            y = min(map_rows - menu_height - 1, ty + 3)  # 目标下方
            if y - 1 <= ty and ty < y + menu_height + 1:
                y = max(0, ty - menu_height - 2)  # 目标上方

    badges = _kind_badges(strings, target)
    title = target.name + ("·" + "·".join(b[0] for b in badges) if badges else "")
    console.draw_frame(
        x=x, y=y, width=menu_width, height=menu_height,
        title=f" {title} ",
        clear=True,
        fg=tuple(theme["ui"]["frame"]),
        bg=tuple(theme["background"]),
    )

    row = y + 2
    bar_w = max(8, menu_width - 18)
    # 气血：百分比条 + 数值
    filled = round(bar_w * fighter.hp / max(1, fighter.max_hp))
    console.print(x + 2, row, strings["hud_hp"].format(hp=fighter.hp, max_hp=fighter.max_hp)[: menu_width - bar_w - 4], fg=tuple(theme["hud"]["hp"]))
    console.print(x + menu_width - bar_w - 2, row, BAR_FILLED * filled + BAR_EMPTY * (bar_w - filled), fg=tuple(theme["hud"]["hp"]))
    row += 1
    console.print(
        x + 2, row,
        strings["examine_stats"].format(
            hp=fighter.hp, max_hp=fighter.max_hp, power=fighter.power,
            defense=fighter.defense, xp=fighter.xp_reward,
        )[: menu_width - 4],
        fg=COLOR_NAME,
    )
    row += 1
    # 威胁 + 距离
    threat = _assess_threat(engine.player, target)
    threat_colors = {"high": (244, 96, 96), "mid": (255, 222, 130), "low": (122, 232, 190)}
    dist = int(engine.player.distance_to(target))
    threat_text = strings[f"threat_{threat}"]
    line = f"{strings['examine_threat_label']} {threat_text}   {strings['examine_dist']} {dist}"
    console.print(x + 2, row, line, fg=threat_colors[threat])
    row += 1
    # 抗性
    if resist_parts:
        console.print(x + 2, row, strings["examine_resist"].format(resists=" ".join(resist_parts)), fg=(150, 200, 160))
    else:
        console.print(x + 2, row, strings["examine_no_resist"], fg=(150, 150, 158))
    row += 1
    if element_names:
        console.print(x + 2, row, strings["examine_attack"].format(elements="、".join(element_names)), fg=(240, 160, 110))
        row += 1
    if lore_lines:
        row += 1  # 典故前空行
        for line in lore_lines:
            console.print(x + 2, row, line[: menu_width - 4], fg=(168, 168, 178))
            row += 1
    else:
        console.print(x + 2, row, strings["examine_lore_show"], fg=(130, 130, 140))

    # 目标清单（多目标时）：卡片上方竖排
    targets = list(handler.targets) if handler is not None else []
    if len(targets) > 1:
        list_h = len(targets) + 2
        list_y = y - list_h - 1
        if list_y < 0:
            list_y = min(map_rows - list_h, y + menu_height + 1)
        if 0 <= list_y and list_y + list_h <= map_rows:
            console.draw_frame(
                x=x, y=list_y, width=menu_width, height=list_h,
                title=f" {strings['examine_targets']} ",
                clear=True,
                fg=tuple(theme["ui"]["frame"]),
                bg=tuple(theme["background"]),
            )
            for i, t in enumerate(targets[:9]):  # 清单最多 9 项（数字键 1-9 直达）
                current = (i == handler.index % len(targets))
                mini = 6
                mini_filled = round(mini * t.fighter.hp / max(1, t.fighter.max_hp))
                mark = "►" if current else " "
                number = str(i + 1) if i < 9 else " "
                color = COLOR_NAME if current else (150, 150, 158)
                console.print(x + 2, list_y + 1 + i, f"{mark}{number} {t.name}"[: menu_width - mini - 6], fg=color)
                console.print(
                    x + menu_width - mini - 2, list_y + 1 + i,
                    BAR_FILLED * mini_filled + BAR_EMPTY * (mini - mini_filled),
                    fg=tuple(theme["hud"]["hp"]) if current else (90, 60, 60),
                )

    # 底部按键提示
    hint = strings["examine_hint_full"]
    console.print(max(0, (map_cols - len(hint)) // 2), map_rows - 1, hint, fg=(130, 130, 140))


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


# ---- 天工开物（C：炼制界面）----


def render_craft_menu(console: tcod.console.Console, engine: "Engine", page: int, cursor: int) -> None:
    """炼制界面：丹/器/符三页（Tab 切换），配方 + 材料需求着色 + 行囊材料摘要。"""
    import craft

    strings = engine.content.strings
    content = engine.content
    theme = engine.content.theme
    recipes = craft.recipes_of_kind(content, craft.CRAFT_KINDS[page])

    map_cols = engine.settings.map_cols
    map_rows = engine.settings.map_rows
    menu_width = min(52, map_cols - 2)
    menu_height = min(map_rows - 2, max(12, len(recipes) * 2 + 8))
    x = max(0, (map_cols - menu_width) // 2)
    y = max(0, (map_rows - menu_height) // 2)

    page_names = (
        strings["craft_page_alchemy"],
        strings["craft_page_forge"],
        strings["craft_page_talisman"],
    )
    console.draw_frame(
        x=x,
        y=y,
        width=menu_width,
        height=menu_height,
        title=f" {strings['craft_title']} ",
        clear=True,
        fg=tuple(theme["ui"]["frame"]),
        bg=tuple(theme["background"]),
    )
    header = " · ".join(
        (f"[{name}]" if i == page else name) for i, name in enumerate(page_names)
    )
    console.print(x + 2, y + 1, header, fg=COLOR_HEADER)
    console.print(
        x + 2, y + 2,
        strings["craft_hint"].format(count=len(recipes))[: menu_width - 4],
        fg=(150, 150, 158),
    )

    row = y + 4
    for i, recipe in enumerate(recipes[: menu_height - 7]):
        mark = ">" if i == cursor else " "
        name = content._(recipe["name"])
        output = content.items[recipe["output"]["id"]]
        requirements = craft.recipe_requirements(engine, recipe)
        craftable = all(ok for *_, ok in requirements)
        line_color = COLOR_NAME if craftable else COLOR_SKILL_LOCKED
        console.print(x + 2, row, f"{mark}{name} → {content._(output['name'])}", fg=line_color)
        # 材料需求行：绿 ✓ / 红 ✗
        parts = []
        for _, mat_name, need, have, ok in requirements:
            parts.append(f"{mat_name} {have}/{need}")
        detail = "  " + "  ".join(parts)
        console.print(x + 2, row + 1, detail[: menu_width - 4], fg=(150, 200, 160))
        row += 2

    # 行囊材料摘要（底部一行）
    summary_parts = []
    for iid in sorted(craft.materials_of(content)):
        have = engine.player.inventory.count_material(iid, content)
        if have > 0:
            summary_parts.append(f"{content._(content.items[iid]['name'])}{have}")
    summary = strings["craft_materials"] + "：" + (" ".join(summary_parts) if summary_parts else "—")
    console.print(x + 2, y + menu_height - 2, summary[: menu_width - 4], fg=(170, 170, 180))


# ---- 山海图卷（M：世界地图）----

# 块采样时各地形的显示优先级（桥最高：渡口是导航关键）
_MAP_PROMINENCE = {
    tile_types.T_BRIDGE: 12,
    tile_types.T_SNOW: 11,
    tile_types.T_MOUNTAIN: 10,
    tile_types.T_ABYSS: 9,
    tile_types.T_WATER: 8,
    tile_types.T_RIVER: 7,
    tile_types.T_FOREST: 6,
    tile_types.T_HILL: 5,
    tile_types.T_SHORE: 3,
    tile_types.T_PLAIN: 2,
    tile_types.T_FLOOR: 1,
    tile_types.T_WALL: 1,
}


def render_world_map_overlay(console: tcod.console.Console, engine: "Engine") -> None:
    """山海图卷：世界已探索区域缩略图 + 名山/秘境之门/玩家/视口标记。"""
    world = engine.world
    content = engine.content
    strings = content.strings
    theme = content.theme
    map_cols = engine.settings.map_cols
    map_rows = engine.settings.map_rows

    _, light_lut, dark_lut = _terrain_luts(theme)
    ch_lut, _, _ = _terrain_luts(theme)
    prominence = np.zeros(tile_types.N_TERRAINS, dtype=np.int8)
    for tid, score in _MAP_PROMINENCE.items():
        prominence[tid] = score

    # 标题 + 图例占顶部两行，图本体居中
    head = 2
    avail_w = max(4, map_cols - 2)
    avail_h = max(4, map_rows - head - 1)
    scale = max(1, -(-world.width // avail_w), -(-world.height // avail_h))
    tw = -(-world.width // scale)
    th = -(-world.height // scale)
    ox = max(0, (map_cols - tw) // 2)
    oy = head + max(0, (map_rows - head - th) // 2)

    console.draw_frame(
        x=0, y=0, width=map_cols, height=map_rows,
        title=f" {strings['world_map_title']} ",
        clear=True,
        fg=tuple(theme["ui"]["frame"]),
        bg=tuple(theme["background"]),
    )
    console.print(
        max(1, (map_cols - len(strings["world_map_legend"]) * 1) // 2), 1,
        strings["world_map_legend"], fg=(150, 150, 160),
    )

    # 块采样：图格 (gx, gy) ← 世界 scale×scale 块内 explored 的最显著地形
    explored = world.explored
    terrain = world.terrain
    for gy in range(th):
        for gx in range(tw):
            x0, y0 = gx * scale, gy * scale
            x1 = min(world.width, x0 + scale)
            y1 = min(world.height, y0 + scale)
            block_explored = explored[x0:x1, y0:y1]
            if not block_explored.any():
                continue
            block_terrain = terrain[x0:x1, y0:y1]
            scores = prominence[block_terrain] * block_explored
            flat = np.argmax(scores)
            tid = block_terrain.flatten()[flat]
            color = dark_lut[tid]
            # 提亮一档让图卷可读（记忆色偏暗）
            bright = np.clip(color.astype(np.float64) * 1.6, 0, 255).astype(np.uint8)
            console.print(ox + gx, oy + gy, chr(int(ch_lut[tid])), fg=tuple(int(c) for c in bright))

    # 名山地标（其所在格已被探索）
    for lm in world.landmarks:
        if explored[lm["x"], lm["y"]]:
            console.print(ox + lm["x"] // scale, oy + lm["y"] // scale, "◈", fg=(255, 222, 130))

    # 已知秘境之门（进入过视野即永久标记；封印后灰显）
    sealed_gates = {
        (e.x, e.y): "sealed" in e.tags for e in world.entities if "realm_gate" in e.tags
    }
    for gx_, gy_ in engine.known_gates:
        sealed = sealed_gates.get((gx_, gy_), False)
        console.print(
            ox + gx_ // scale, oy + gy_ // scale, "Ω",
            fg=(110, 104, 124) if sealed else (176, 138, 240),
        )

    # 当前视口范围（≥3 格宽时画框，否则仅玩家标记）
    cam_x, cam_y = camera_origin(world, engine.player, map_cols, map_rows)
    vx0, vy0 = cam_x // scale, cam_y // scale
    vx1 = min(tw - 1, (cam_x + map_cols - 1) // scale)
    vy1 = min(th - 1, (cam_y + map_rows - 1) // scale)
    frame_color = (214, 196, 120)
    if vx1 - vx0 >= 2 and vy1 - vy0 >= 2:
        for x in range(vx0, vx1 + 1):
            console.print(ox + x, oy + vy0, "─", fg=frame_color)
            console.print(ox + x, oy + vy1, "─", fg=frame_color)
        for y in range(vy0, vy1 + 1):
            console.print(ox + vx0, oy + y, "│", fg=frame_color)
            console.print(ox + vx1, oy + y, "│", fg=frame_color)
        console.print(ox + vx0, oy + vy0, "┌", fg=frame_color)
        console.print(ox + vx1, oy + vy0, "┐", fg=frame_color)
        console.print(ox + vx0, oy + vy1, "└", fg=frame_color)
        console.print(ox + vx1, oy + vy1, "┘", fg=frame_color)

    # 玩家（最上层）
    console.print(
        ox + engine.player.x // scale, oy + engine.player.y // scale, "@", fg=(255, 255, 255)
    )
