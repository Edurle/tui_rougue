"""程序化秘境地牢生成：随机房间 + L 形走廊 + 按投放表填充怪物与物品。

生成参数（尺寸、数量）为机制常量；投放什么由 spawn_tables.json 决定。
地牢尺寸与屏幕视口解耦（渲染层摄像机适配任意地图大小）。
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, Iterator, List, Optional, Tuple

import tile_types
from game_map import GameMap

if TYPE_CHECKING:
    from engine import Engine

MAX_ROOMS = 10
ROOM_MIN_SIZE = 6
ROOM_MAX_SIZE = 8
# 秘境地牢固定尺寸（大于等于最大视口，保证探索感）
DUNGEON_WIDTH = 44
DUNGEON_HEIGHT = 30


class Rect:
    def __init__(self, x: int, y: int, width: int, height: int) -> None:
        self.x1 = x
        self.y1 = y
        self.x2 = x + width
        self.y2 = y + height

    @property
    def center(self) -> Tuple[int, int]:
        return (self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2

    def intersects(self, other: "Rect") -> bool:
        return (
            self.x1 <= other.x2
            and self.x2 >= other.x1
            and self.y1 <= other.y2
            and self.y2 >= other.y1
        )

    def inner(self):
        for x in range(self.x1 + 1, self.x2):
            for y in range(self.y1 + 1, self.y2):
                yield x, y

    def random_inner(self, rng: random.Random) -> Tuple[int, int]:
        return rng.randint(self.x1 + 1, self.x2 - 1), rng.randint(self.y1 + 1, self.y2 - 1)


def tunnel_between(start: Tuple[int, int], end: Tuple[int, int], rng: random.Random) -> Iterator[Tuple[int, int]]:
    """L 形走廊，先横后竖或先竖后横随机。"""
    x1, y1 = start
    x2, y2 = end
    if rng.random() < 0.5:
        corner_x, corner_y = x2, y1
    else:
        corner_x, corner_y = x1, y2
    for x, y in _walk_line(x1, y1, corner_x, corner_y):
        yield x, y
    for x, y in _walk_line(corner_x, corner_y, x2, y2):
        yield x, y


def _walk_line(x1: int, y1: int, x2: int, y2: int) -> Iterator[Tuple[int, int]]:
    x_step = 1 if x1 < x2 else -1
    y_step = 1 if y1 < y2 else -1
    x, y = x1, y1
    yield x, y
    while x != x2:
        x += x_step
        yield x, y
    while y != y2:
        y += y_step
        yield x, y


def generate_dungeon(
    engine: "Engine",
    floor_number: int,
    rng: random.Random,
    width: Optional[int] = None,
    height: Optional[int] = None,
    realm_id: Optional[str] = None,
    realm_depth: int = 1,
    boss_id: Optional[str] = None,
) -> GameMap:
    """生成秘境地牢一层。floor_number 语义 = 投放难度（统一难度轴）。

    boss_id 非空时为最深层：最后房间中央盘踞 BOSS，不设下行山径。
    """
    content = engine.content
    width = DUNGEON_WIDTH if width is None else width
    height = DUNGEON_HEIGHT if height is None else height
    gamemap = GameMap(
        engine,
        width,
        height,
        floor_number=floor_number,
        map_type="realm",
        realm_id=realm_id,
        realm_depth=realm_depth,
    )
    if realm_id is not None:
        gamemap.theme_key = content.realm_def(realm_id)["theme"]

    rooms: List[Rect] = []
    player_start = None

    for _ in range(MAX_ROOMS):
        room_w = rng.randint(ROOM_MIN_SIZE, ROOM_MAX_SIZE)
        room_h = rng.randint(ROOM_MIN_SIZE, ROOM_MAX_SIZE)
        x = rng.randint(1, gamemap.width - room_w - 2)
        y = rng.randint(1, gamemap.height - room_h - 2)
        new_room = Rect(x, y, room_w, room_h)

        if any(new_room.intersects(room) for room in rooms):
            continue

        for px, py in new_room.inner():
            gamemap.terrain[px, py] = tile_types.T_FLOOR

        if rooms:
            for px, py in tunnel_between(rooms[-1].center, new_room.center, rng):
                gamemap.terrain[px, py] = tile_types.T_FLOOR
        else:
            player_start = new_room.center

        _populate_room(gamemap, new_room, floor_number, content, rng, skip_first=not rooms)
        rooms.append(new_room)

    gamemap.refresh_tile_flags()

    player_x, player_y = player_start  # type: ignore[misc]
    engine.player.place(gamemap, player_start[0], player_start[1])
    gamemap.upstairs_xy = player_start  # 上行山径在抵达点（出生房间中心）

    if boss_id is not None:
        # BOSS 层：末房清场后中央盘踞 BOSS，无下行山径
        boss_room = rooms[-1]
        for entity in list(gamemap.entities):
            if entity is engine.player:
                continue
            if (
                boss_room.x1 <= entity.x <= boss_room.x2
                and boss_room.y1 <= entity.y <= boss_room.y2
            ):
                gamemap.entities.discard(entity)
        bx, by = boss_room.center
        content.build_monster(boss_id, gamemap, bx, by)
        gamemap.downstairs_xy = (-1, -1)
    else:
        stairs_x, stairs_y = rooms[-1].center
        gamemap.downstairs_xy = (stairs_x, stairs_y)

    # ---- 资源点（灵草/矿脉，走上去按 G 采集）----
    from worldgen import scatter_resource_nodes

    realm_counts = {
        node_id: int(node.get("realm_per_floor", 0))
        for node_id, node in content.craft_nodes.items()
    }
    scatter_resource_nodes(gamemap, content, rng, realm_counts)

    gamemap.rebuild_wall_glyphs()

    return gamemap


def _populate_room(
    gamemap: GameMap,
    room: Rect,
    floor_number: int,
    content,
    rng: random.Random,
    skip_first: bool,
) -> None:
    if not skip_first:  # 出生房间不放怪，给玩家喘息
        monster_cfg = content.per_room["monsters"]
        if rng.random() < monster_cfg["chance"]:
            for _ in range(rng.randint(monster_cfg["min"], monster_cfg["max"])):
                _place_at(gamemap, room, rng, content.random_monster_id(floor_number, rng), content.build_monster)
    item_cfg = content.per_room["items"]
    if rng.random() < item_cfg["chance"]:
        for _ in range(rng.randint(item_cfg["min"], item_cfg["max"])):
            _place_at(gamemap, room, rng, content.random_item_id(floor_number, rng), content.build_item)


def _place_at(gamemap: GameMap, room: Rect, rng: random.Random, entity_id: str, builder) -> None:
    for _ in range(16):  # 尝试若干次找空位，找不到就放弃该实体
        x, y = room.random_inner(rng)
        if gamemap.tiles["walkable"][x, y] and not gamemap.get_blocking_entity_at(x, y):
            builder(entity_id, gamemap, x, y)
            return
