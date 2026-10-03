"""大世界（山海大陆）生成：噪声地形 + 区域环带 + 河流雕刻 + 深渊 + 名山。

空间布局（契合《山海经》"大荒在四海之外"）：
- 中山经居中（出生，最安全），四方按方位四象限划分南/西/北/东山经
- 大荒经为最外围环带，深渊裂谷集中于此
- 区域边界以噪声山脊为屏障、留山口通行；河流自山间发源注入湖泊
- 生成后 BFS 验证各区域锚点连通，不通则凿径/架桥

生成参数为机制常量；区域/难度/名山由 regions.json 决定。
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, List, Optional, Tuple

import numpy as np

import tile_types
from game_map import GameMap

if TYPE_CHECKING:
    from engine import Engine

WORLD_WIDTH = 240
WORLD_HEIGHT = 150
WORLD_FOV_RADIUS = 14

# 地形阈值（elevation/moisture 归一化 0-1）
ELEV_SNOW = 0.86
ELEV_MOUNTAIN = 0.70
ELEV_HILL = 0.56
ELEV_WATER = 0.30
MOIST_FOREST = 0.62

# 区域环带（归一化椭圆距离 d：中心 0，角落最大 √2）
CENTER_RADIUS = 0.38  # 内圈 = 中山经
RIDGE_INNER = 0.41  # 内山脊环带中心
RIDGE_INNER_WIDTH = 0.055
OUTER_RADIUS = 0.86  # 外圈之外 = 大荒经
RIDGE_OUTER = 0.855  # 外山脊环带中心
RIDGE_OUTER_WIDTH = 0.06

# 世界边界围栏（强制山脉圈住世界）
WORLD_MARGIN = 2

# 河流与投放（机制常量）
RIVER_SOURCES = 9
RIVER_BRIDGE_EVERY = 9  # 河流每隔 N 格架桥，保证可渡
MONSTER_DENSITY = 1 / 320  # 每 N 可走格一只游荡异兽（低密度，旅行可绕行）
CENTER_MONSTER_DENSITY = 1 / 700  # 中山经腹地更安宁
ITEM_DENSITY = 1 / 500
SPAWN_CLEAR_RADIUS = 2  # 出生点安全清场半径
SPAWN_SAFE_RADIUS = 18  # 出生点曼哈顿距离内不投放任何异兽
LANDMARK_MIN_GAP = 16  # 名山之间的最小间距


def _smoothstep(t: np.ndarray) -> np.ndarray:
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3 - 2 * t)


def _band(dist: np.ndarray, center: float, width: float) -> np.ndarray:
    """距环带中心的平滑隶属度：带内 1、带边 0。"""
    return 1.0 - _smoothstep(np.abs(dist - center) / width)


def _value_noise(w: int, h: int, rng: random.Random, cell: int) -> np.ndarray:
    """低分辨率随机网格 + 双线性插值 + 平滑，输出 0-1。"""
    gw = max(2, w // cell + 2)
    gh = max(2, h // cell + 2)
    grid = np.array([[rng.random() for _ in range(gw)] for _ in range(gh)], dtype=np.float64)
    # 双线性放大到 (h, w)
    ys = np.linspace(0, gh - 1, h)
    xs = np.linspace(0, gw - 1, w)
    y0 = np.floor(ys).astype(int)
    x0 = np.floor(xs).astype(int)
    y1 = np.minimum(y0 + 1, gh - 1)
    x1 = np.minimum(x0 + 1, gw - 1)
    fy = (ys - y0)[:, None]
    fx = (xs - x0)[None, :]
    top = grid[y0][:, x0] * (1 - fx) + grid[y0][:, x1] * fx
    bottom = grid[y1][:, x0] * (1 - fx) + grid[y1][:, x1] * fx
    return top * (1 - fy) + bottom * fy


def _blur(field: np.ndarray, passes: int = 2) -> np.ndarray:
    """3x3 均值模糊（np.roll 环绕近似，世界四周是围栏山，边界影响可忽略）。"""
    out = field.copy()
    for _ in range(passes):
        out = (
            out
            + np.roll(out, 1, axis=0)
            + np.roll(out, -1, axis=0)
            + np.roll(out, 1, axis=1)
            + np.roll(out, -1, axis=1)
        ) / 5.0
    return out


def _fbm(w: int, h: int, rng: random.Random, cells: Tuple[int, ...]) -> np.ndarray:
    """多倍频值噪声叠加（先粗后细），归一化 0-1。输出 (w, h) 与地图索引一致。"""
    fields = []
    for cell in cells:
        noise = _blur(_value_noise(w, h, rng, cell), passes=max(1, cell // 8))
        fields.append(noise)
    combined = fields[0]
    for finer in fields[1:]:
        combined = combined * 0.55 + finer * 0.45
    lo, hi = combined.min(), combined.max()
    normalized = (combined - lo) / max(1e-9, hi - lo)
    return normalized.T  # (h, w) → (w, h)


def region_grid(w: int, h: int, content) -> Tuple[np.ndarray, List[dict]]:
    """每格所属区域 id（regions.json 顺序索引）。"""
    ordered = content.regions
    by_zone = {r["zone"]: i for i, r in enumerate(ordered)}
    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
    xs = np.arange(w, dtype=np.float32)
    ys = np.arange(h, dtype=np.float32)
    nx = (xs - cx) / (w / 2.0)
    ny = (ys - cy) / (h / 2.0)
    dist = np.hypot(nx[None, :], ny[:, None])  # (h, w)

    grid = np.full((h, w), by_zone["outer"], dtype=np.uint8)
    mid = dist < OUTER_RADIUS
    grid[~mid] = by_zone["outer"]
    # 四象限（相对中心：y 大为南）
    south_north = np.abs(ny[:, None]) > np.abs(nx[None, :])
    south = mid & south_north & (ny[:, None] > 0)
    north = mid & south_north & (ny[:, None] <= 0)
    east = mid & (~south_north) & (nx[None, :] > 0)
    west = mid & (~south_north) & (nx[None, :] <= 0)
    center = dist < CENTER_RADIUS
    grid[south] = by_zone["south"]
    grid[north] = by_zone["north"]
    grid[east] = by_zone["east"]
    grid[west] = by_zone["west"]
    grid[center] = by_zone["center"]
    return grid.T, ordered  # 转置为 (w, h) 与地图索引一致


def _carve_river(terrain: np.ndarray, elev: np.ndarray, rng: random.Random, source: Tuple[int, int]) -> None:
    """自高处沿最陡下降雕刻一条河（宽 1），入湖/抵界即止。"""
    w, h = terrain.shape
    x, y = source
    visited = set()
    bridge_countdown = RIVER_BRIDGE_EVERY
    for _ in range(400):
        if not (0 < x < w - 1 and 0 < y < h - 1):
            return
        if (x, y) in visited:
            return
        visited.add((x, y))
        if terrain[x, y] in (tile_types.T_WATER, tile_types.T_ABYSS):
            return
        if terrain[x, y] == tile_types.T_RIVER:
            return  # 并入已有水系
        terrain[x, y] = tile_types.T_RIVER
        bridge_countdown -= 1
        if bridge_countdown <= 0 and terrain[x, y] == tile_types.T_RIVER:
            terrain[x, y] = tile_types.T_BRIDGE
            bridge_countdown = RIVER_BRIDGE_EVERY
        # 8 邻域最低者；平地随机下坡避免死锁
        best = None
        best_e = elev[x, y]
        candidates = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                nx_, ny_ = x + dx, y + dy
                if not (0 < nx_ < w - 1 and 0 < ny_ < h - 1):
                    continue
                candidates.append((elev[nx_, ny_], nx_, ny_))
                if elev[nx_, ny_] < best_e:
                    best_e = elev[nx_, ny_]
                    best = (nx_, ny_)
        if best is None:
            rng.shuffle(candidates)
            if not candidates:
                return
            best = (candidates[0][1], candidates[0][2])
        x, y = best


_WALKABLE_TERRAINS = (
    tile_types.T_PLAIN,
    tile_types.T_FOREST,
    tile_types.T_HILL,
    tile_types.T_BRIDGE,
    tile_types.T_SHORE,
)


def _flood_reachable(terrain: np.ndarray, spawn: Tuple[int, int]) -> np.ndarray:
    """从出生点 8 邻域泛洪的可走区域（一次 BFS，连通性验证用）。"""
    w, h = terrain.shape
    walkable = np.isin(terrain, _WALKABLE_TERRAINS)
    reached = np.zeros((w, h), dtype=bool)
    sx, sy = spawn
    if not (0 <= sx < w and 0 <= sy < h) or not walkable[sx, sy]:
        return reached
    reached[sx, sy] = True
    stack = [(sx, sy)]
    while stack:
        x, y = stack.pop()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                nx_, ny_ = x + dx, y + dy
                if 0 <= nx_ < w and 0 <= ny_ < h and not reached[nx_, ny_] and walkable[nx_, ny_]:
                    reached[nx_, ny_] = True
                    stack.append((nx_, ny_))
    return reached


def _carve_line(terrain: np.ndarray, start: Tuple[int, int], target: Tuple[int, int]) -> None:
    """直线凿径：山/雪 → 丘，水/河 → 桥（连通性兜底）。"""
    walkable_ids = set(_WALKABLE_TERRAINS)
    x, y = start
    tx, ty = target
    for _ in range(max(abs(tx - x), abs(ty - y)) * 2 + 1):
        if x == tx and y == ty:
            return
        dx = (tx > x) - (tx < x)
        dy = (ty > y) - (ty < y)
        x, y = x + dx, y + dy
        if terrain[x, y] not in walkable_ids:
            terrain[x, y] = (
                tile_types.T_BRIDGE
                if terrain[x, y] in (tile_types.T_WATER, tile_types.T_RIVER, tile_types.T_ABYSS)
                else tile_types.T_HILL
            )


def _ensure_connectivity(terrain: np.ndarray, spawn: Tuple[int, int], anchors: List[Tuple[int, int]]) -> None:
    """验证锚点可达；不可达则向出生点方向直线凿径，最多补 3 轮。"""
    for _ in range(3):
        reached = _flood_reachable(terrain, spawn)
        unreachable = [(x, y) for x, y in anchors if not reached[x, y]]
        if not unreachable:
            return
        for anchor in unreachable:
            _carve_line(terrain, anchor, spawn)


def generate_world(engine: "Engine", rng: random.Random) -> GameMap:
    content = engine.content
    w, h = WORLD_WIDTH, WORLD_HEIGHT
    gamemap = GameMap(
        engine,
        w,
        h,
        floor_number=0,
        map_type="world",
        default_terrain=tile_types.T_PLAIN,
    )
    gamemap.fov_radius = WORLD_FOV_RADIUS

    # ---- 1. 区域网格 ----
    region_ids, regions = region_grid(w, h, content)
    gamemap.region_ids = region_ids

    # ---- 2. 高度/湿度/裂谷噪声 ----
    elev = _fbm(w, h, rng, cells=(40, 16, 7))
    moist = _fbm(w, h, rng, cells=(28, 11))

    # ---- 3. 山脊环带抬升（区域屏障，噪声留山口）----
    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
    xs = np.arange(w, dtype=np.float32)
    ys = np.arange(h, dtype=np.float32)
    nx = (xs - cx) / (w / 2.0)
    ny = (ys - cy) / (h / 2.0)
    dist = np.hypot(nx[None, :], ny[:, None]).T  # (w, h)
    ridge = np.maximum(_band(dist, RIDGE_INNER, RIDGE_INNER_WIDTH), _band(dist, RIDGE_OUTER, RIDGE_OUTER_WIDTH))
    gaps = _fbm(w, h, rng, cells=(22, 9))
    elev = elev * (1.0 - 0.85 * ridge) + ridge * (0.30 + 0.70 * gaps)

    # ---- 4. 生物群系映射 ----
    terrain = np.zeros((w, h), dtype=np.uint8)
    terrain[elev >= ELEV_SNOW] = tile_types.T_SNOW
    terrain[(elev >= ELEV_MOUNTAIN) & (elev < ELEV_SNOW)] = tile_types.T_MOUNTAIN
    terrain[(elev >= ELEV_HILL) & (elev < ELEV_MOUNTAIN)] = tile_types.T_HILL
    terrain[elev < ELEV_WATER] = tile_types.T_WATER
    rest = terrain == 0
    terrain[rest & (moist >= MOIST_FOREST)] = tile_types.T_FOREST
    terrain[rest & (moist < MOIST_FOREST)] = tile_types.T_PLAIN

    # ---- 5. 深渊裂谷（大荒经专属）----
    outer_mask = region_ids == [i for i, r in enumerate(regions) if r["zone"] == "outer"][0]
    rift = _fbm(w, h, rng, cells=(30, 12))
    abyss_mask = outer_mask & (rift > 0.68) & (elev < ELEV_HILL)
    terrain[abyss_mask] = tile_types.T_ABYSS

    # ---- 6. 河流（山顶发源，注入湖泊）----
    mountain_peaks = [
        (int(x), int(y))
        for x, y in zip(*np.where(terrain == tile_types.T_MOUNTAIN))
    ]
    rng.shuffle(mountain_peaks)
    peaks_sorted = sorted(mountain_peaks[: RIVER_SOURCES * 6], key=lambda p: -elev[p[0], p[1]])
    for source in peaks_sorted[:RIVER_SOURCES]:
        _carve_river(terrain, elev, rng, source)

    # ---- 7. 水岸滩涂（水旁的平原 → 岸）----
    water = terrain == tile_types.T_WATER
    near_water = np.zeros((w, h), dtype=bool)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            near_water |= np.roll(np.roll(water, dx, axis=0), dy, axis=1)
    shore_mask = near_water & (terrain == tile_types.T_PLAIN)
    # 环回边界引入的伪邻居排除：边界一律不作滩涂
    shore_mask[:WORLD_MARGIN, :] = shore_mask[-WORLD_MARGIN:, :] = False
    shore_mask[:, :WORLD_MARGIN] = shore_mask[:, -WORLD_MARGIN:] = False
    terrain[shore_mask] = tile_types.T_SHORE

    # ---- 8. 世界边界围栏 ----
    terrain[:WORLD_MARGIN, :] = tile_types.T_MOUNTAIN
    terrain[-WORLD_MARGIN:, :] = tile_types.T_MOUNTAIN
    terrain[:, :WORLD_MARGIN] = tile_types.T_MOUNTAIN
    terrain[:, -WORLD_MARGIN:] = tile_types.T_MOUNTAIN

    # ---- 9. 出生点（区域中心可走格，安全清场）----
    spawn = _find_spawn(terrain, w // 2, h // 2, rng)
    for dx in range(-SPAWN_CLEAR_RADIUS, SPAWN_CLEAR_RADIUS + 1):
        for dy in range(-SPAWN_CLEAR_RADIUS, SPAWN_CLEAR_RADIUS + 1):
            x, y = spawn[0] + dx, spawn[1] + dy
            if 0 < x < w - 1 and 0 < y < h - 1:
                if terrain[x, y] in (tile_types.T_WATER, tile_types.T_RIVER, tile_types.T_ABYSS):
                    terrain[x, y] = tile_types.T_BRIDGE
                elif terrain[x, y] in (tile_types.T_MOUNTAIN, tile_types.T_SNOW):
                    terrain[x, y] = tile_types.T_HILL

    # ---- 10. 名山地标 + 连通锚点 ----
    landmarks = _place_landmarks(terrain, region_ids, regions, content, rng)
    gamemap.landmarks = landmarks
    anchors = [(lm["x"], lm["y"]) for lm in landmarks]
    for i, region in enumerate(regions):
        anchor = _find_spawn(
            terrain,
            *(
                _region_center_hint(region["zone"], w, h, dist)
            ),
            rng,
        )
        anchors.append(anchor)
    _ensure_connectivity(terrain, spawn, anchors)

    gamemap.terrain = terrain
    gamemap.refresh_tile_flags()

    # ---- 11. 投放：游荡异兽与散落物品 ----
    _populate_world(gamemap, content, rng, spawn)

    # ---- 12. 秘境入口（可达约束 + 按区域难度控制远近）----
    reached = _flood_reachable(terrain, spawn)
    _place_realm_gates(gamemap, content, rng, spawn, reached)

    gamemap.spawn_xy = spawn
    return gamemap


def _place_realm_gates(
    gamemap: GameMap, content, rng: random.Random, spawn: Tuple[int, int], reached: np.ndarray
) -> None:
    """把 realms.json 的秘境入口撒到所属区域的可达格上。

    距离约束：难度越高的区域，入口离出生点越远（18 + 基础难度*3 曼哈顿距离）。
    """
    placed: List[Tuple[int, int]] = []
    region_index = {r["id"]: i for i, r in enumerate(content.regions)}
    for rid, realm in content.realms.items():
        idx = region_index[realm["region"]]
        base = int(content.regions[idx]["base_difficulty"])
        min_dist = 18 + base * 3  # 难度越高入口离出生点越远（按世界尺寸校准）
        mask = (
            (gamemap.region_ids == idx)
            & reached
            & gamemap.tiles["walkable"]
        )
        xs, ys = np.where(mask)
        coords = [
            (int(x), int(y))
            for x, y in zip(xs.tolist(), ys.tolist())
            if abs(x - spawn[0]) + abs(y - spawn[1]) >= min_dist
        ]
        if not coords:  # 兜底：放宽距离约束
            coords = [(int(x), int(y)) for x, y in zip(xs.tolist(), ys.tolist())]
        rng.shuffle(coords)
        for x, y in coords:
            if all(abs(x - px) + abs(y - py) >= 12 for px, py in placed):
                content.build_realm_gate(rid, gamemap, x, y)
                placed.append((x, y))
                break


def _region_center_hint(zone: str, w: int, h: int, dist: np.ndarray) -> Tuple[int, int]:
    """区域连通锚点的大致位置。"""
    cx, cy = w // 2, h // 2
    if zone == "center":
        return cx, cy
    if zone == "outer":
        return w // 2, WORLD_MARGIN + 6
    dx, dy = {
        "south": (0, 1),
        "north": (0, -1),
        "east": (1, 0),
        "west": (-1, 0),
    }[zone]
    rx = int(cx + dx * w * 0.28)
    ry = int(cy + dy * h * 0.28)
    return max(3, min(w - 4, rx)), max(3, min(h - 4, ry))


def _find_spawn(terrain: np.ndarray, x: int, y: int, rng: random.Random) -> Tuple[int, int]:
    """从 (x, y) 螺旋向外找第一个可走格。"""
    w, h = terrain.shape
    walkable = {
        tile_types.T_PLAIN,
        tile_types.T_FOREST,
        tile_types.T_HILL,
        tile_types.T_SHORE,
        tile_types.T_BRIDGE,
    }
    if 0 <= x < w and 0 <= y < h and terrain[x, y] in walkable:
        return x, y
    for radius in range(1, max(w, h)):
        for _ in range(24):
            ox = rng.randint(-radius, radius)
            oy = rng.randint(-radius, radius)
            nx_, ny_ = x + ox, y + oy
            if 0 < nx_ < w - 1 and 0 < ny_ < h - 1 and terrain[nx_, ny_] in walkable:
                return nx_, ny_
    return x, y


def _place_landmarks(terrain, region_ids, regions, content, rng) -> List[dict]:
    """每区域挑海拔最高的山峰作为名山（保持间距），取 regions.json 山名。"""
    landmarks: List[dict] = []
    for idx, region in enumerate(regions):
        want = int(region.get("mountain_count", 3))
        peaks = [
            (int(x), int(y))
            for x, y in zip(*np.where((terrain == tile_types.T_MOUNTAIN) & (region_ids == idx)))
        ]
        if not peaks:  # 区域山太少（噪声波动）——放宽到雪峰
            peaks = [
                (int(x), int(y))
                for x, y in zip(*np.where((terrain == tile_types.T_SNOW) & (region_ids == idx)))
            ]
        rng.shuffle(peaks)
        chosen: List[Tuple[int, int]] = []
        for name_index in range(len(region["mountains"])):
            if len(chosen) >= want:
                break
            for peak in peaks:
                if all(abs(peak[0] - c[0]) + abs(peak[1] - c[1]) >= LANDMARK_MIN_GAP for c in chosen) and all(
                    abs(peak[0] - l["x"]) + abs(peak[1] - l["y"]) >= LANDMARK_MIN_GAP for l in landmarks
                ):
                    chosen.append(peak)
                    break
            else:
                break  # 本区山峰找完了
            landmarks.append(
                {
                    "x": chosen[-1][0],
                    "y": chosen[-1][1],
                    "region_id": region["id"],
                    "name": content._(region["mountains"][name_index]),
                }
            )
    return landmarks


def _populate_world(gamemap: GameMap, content, rng: random.Random, spawn: Tuple[int, int]) -> None:
    """按区域难度低密度投放游荡异兽与散落物品。出生点附近不放怪。"""
    terrain = gamemap.terrain
    walkable_mask = np.isin(terrain, _WALKABLE_TERRAINS)
    xs, ys = np.where(walkable_mask)
    coords = list(zip(xs.tolist(), ys.tolist()))
    rng.shuffle(coords)

    center_index = next(
        (i for i, r in enumerate(content.regions) if r["zone"] == "center"), 0
    )

    def difficulty_at(x: int, y: int) -> int:
        idx = int(gamemap.region_ids[x, y])
        return int(content.regions[idx]["base_difficulty"])

    monsters_left = max(6, int(len(coords) * MONSTER_DENSITY))
    items_left = max(4, int(len(coords) * ITEM_DENSITY))
    for x, y in coords:
        if monsters_left <= 0 and items_left <= 0:
            break
        near_spawn = abs(x - spawn[0]) + abs(y - spawn[1]) <= SPAWN_SAFE_RADIUS
        in_center = int(gamemap.region_ids[x, y]) == center_index
        monster_budget = CENTER_MONSTER_DENSITY if in_center else MONSTER_DENSITY
        # 按区域密度预算节流：中心区投放更稀
        if monsters_left > 0 and not near_spawn and rng.random() < (monster_budget / MONSTER_DENSITY) * 0.7:
            content.build_monster(
                content.random_monster_id(difficulty_at(x, y), rng), gamemap, x, y
            )
            monsters_left -= 1
        elif items_left > 0 and not near_spawn:
            content.build_item(content.random_item_id(difficulty_at(x, y), rng), gamemap, x, y)
            items_left -= 1
