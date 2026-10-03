"""存档系统：JSON + numpy base64（地图数组）+ 内容 id 重建（实体动态态覆盖）。

- 存：世界全图（terrain/explored/区域/名山）+ 秘境层缓存 + 玩家全状态 +
  封印/已访区域 + 当前上下文 + 消息日志尾部
- 读：load_engine() 从存档重建 Engine（内容 id 重建实体，再覆盖动态状态）
- 铁律：死亡删档；版本不匹配拒绝读取
- 时机：F5 手动 / 进出秘境与换层 autosave / 启动"继续游历"
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import numpy as np

import tile_types
from paths import resource_path

if TYPE_CHECKING:
    from engine import Engine

SAVE_VERSION = 1
SAVE_DIR = "saves"
SAVE_FILE = "save.json"
MAX_SAVED_MESSAGES = 30


def save_path() -> Path:
    return resource_path(SAVE_DIR) / SAVE_FILE


def save_exists() -> bool:
    return save_path().exists()


def delete_save() -> None:
    p = save_path()
    if p.exists():
        p.unlink()


# ---- numpy 编解码 ----


def _pack_u8(arr: np.ndarray) -> str:
    """按 F 序（[x,y] 索引约定）打包，与 _unpack_u8 对称。"""
    return base64.b64encode(np.asanyarray(arr, dtype=np.uint8).tobytes(order="F")).decode("ascii")


def _unpack_u8(data: str, shape, dtype=np.uint8) -> np.ndarray:
    raw = np.frombuffer(base64.b64decode(data), dtype=np.uint8)
    return raw.reshape(shape, order="F").astype(dtype)


# ---- 实体序列化 ----


def _serialize_entities(gamemap, content) -> list:
    """地面实体 → 可重建描述（尸体不存，重进地图即消散——简化）。"""
    out = []
    for entity in gamemap.entities:
        tags = getattr(entity, "tags", [])
        if "realm_gate" in tags:
            realm_id = next(t for t in tags if t not in ("realm_gate", "sealed"))
            out.append(
                {
                    "kind": "gate",
                    "realm_id": realm_id,
                    "x": entity.x,
                    "y": entity.y,
                    "sealed": "sealed" in tags,
                }
            )
        elif getattr(entity, "fighter", None) is not None and getattr(entity, "ai", None) is not None:
            # 活体：怪物或召唤兽
            mid = _monster_id_of(entity, content)
            if mid is not None:
                entry = {
                    "kind": "monster",
                    "id": mid,
                    "x": entity.x,
                    "y": entity.y,
                    "hp": entity.fighter.hp,
                    "dot": list(entity.fighter.dot),
                    "stun_turns": entity.fighter.stun_turns,
                    "buffs": {k: list(v) for k, v in entity.fighter.buffs.items()},
                }
                if entity.summon_ttl is not None:
                    entry["summon_ttl"] = entity.summon_ttl
                out.append(entry)
        elif getattr(entity, "consumable", None) is not None or getattr(entity, "equipment", None) is not None:
            iid = _item_id_of(entity, content)
            if iid is not None:
                out.append({"kind": "item", "id": iid, "x": entity.x, "y": entity.y})
        elif getattr(entity, "is_material", False):
            iid = _item_id_of(entity, content)
            if iid is not None:
                out.append(
                    {
                        "kind": "material",
                        "id": iid,
                        "x": entity.x,
                        "y": entity.y,
                        "stack": entity.stack,
                    }
                )
        elif "resource_node" in tags:
            node_id = next(t for t in tags if t != "resource_node")
            out.append({"kind": "node", "node": node_id, "x": entity.x, "y": entity.y})
    return out


def _monster_id_of(entity, content) -> Optional[str]:
    for mid, mdef in content.monsters.items():
        if mdef["char"] == entity.char and content._(mdef["name"]) == entity.name:
            return mid
    return None


def _item_id_of(entity, content) -> Optional[str]:
    for iid, idef in content.items.items():
        if idef["char"] == entity.char and content._(idef["name"]) == entity.name:
            return iid
    return None


def _serialize_map(gamemap, content) -> dict:
    data = {
        "width": gamemap.width,
        "height": gamemap.height,
        "map_type": gamemap.map_type,
        "terrain": _pack_u8(gamemap.terrain),
        "explored": _pack_u8(gamemap.explored.view(np.uint8)),
        "entities": _serialize_entities(gamemap, content),
    }
    if gamemap.map_type == "realm":
        data.update(
            {
                "realm_id": gamemap.realm_id,
                "realm_depth": gamemap.realm_depth,
                "floor_number": gamemap.floor_number,
                "upstairs_xy": list(gamemap.upstairs_xy),
                "downstairs_xy": list(gamemap.downstairs_xy),
            }
        )
    else:
        data.update(
            {
                "region_ids": _pack_u8(gamemap.region_ids),
                "landmarks": gamemap.landmarks,
                "spawn_xy": list(gamemap.spawn_xy),
                "fov_radius": gamemap.fov_radius,
            }
        )
    return data


def _serialize_player(player, content) -> dict:
    fighter = player.fighter
    data = {
        "class_ids": list(player.class_ids),
        "x": player.x,
        "y": player.y,
        "hp": fighter.hp,
        "mp": fighter.mp,
        "base_max_hp": fighter.base_max_hp,
        "base_max_mp": fighter.base_max_mp,
        "base_power": fighter.base_power,
        "base_defense": fighter.base_defense,
        "dot": list(fighter.dot),
        "stun_turns": fighter.stun_turns,
        "buffs": {k: list(v) for k, v in fighter.buffs.items()},
        "level": player.level.current_level,
        "xp": player.level.current_xp,
        "skill_points": player.skill_points,
        "skill_levels": {k: int(v) for k, v in player.skill_levels.items()},
        "inventory": [
            {"id": _item_id_of(i, content), "stack": i.stack} for i in player.inventory.items
        ],
        "equipped": {
            slot: _item_id_of(item, content)
            for slot, item in player.equipment.slots.items()
            if item is not None
        },
    }
    return data


def save_game(engine: "Engine") -> None:
    """把引擎完整状态写入存档文件。"""
    content = engine.content
    realms_data = {
        rid: {str(depth): _serialize_map(gm, content) for depth, gm in floors.items()}
        for rid, floors in engine.realms.items()
    }
    # 当前活动层不在缓存 dict 中（是活动地图），一并存入
    if engine.current_realm is not None and engine.gamemap.map_type == "realm":
        floors = realms_data.setdefault(engine.current_realm, {})
        floors[str(engine.gamemap.realm_depth)] = _serialize_map(engine.gamemap, content)
    data = {
        "version": SAVE_VERSION,
        "world": _serialize_map(engine.world, content),
        "realms": realms_data,
        "player": _serialize_player(engine.player, content),
        "current": {
            "map_type": engine.gamemap.map_type,
            "realm_id": engine.gamemap.realm_id,
            "realm_depth": engine.gamemap.realm_depth,
        },
        "world_return_xy": list(engine.world_return_xy),
        "realm_cleared": sorted(engine.realm_cleared),
        "visited_regions": sorted(engine.visited_regions),
        "known_gates": sorted(tuple(g) for g in engine.known_gates),
        "active_page": engine.active_page,
        "messages": [
            {"text": m.plain_text, "kind": m.kind, "count": m.count}
            for m in engine.message_log.messages[-MAX_SAVED_MESSAGES:]
        ],
    }
    path = save_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


# ---- 读档 ----


def _restore_map(engine, data: dict):
    from game_map import GameMap

    w, h = data["width"], data["height"]
    gamemap = GameMap(
        engine,
        w,
        h,
        floor_number=data.get("floor_number", 1),
        map_type=data["map_type"],
        realm_id=data.get("realm_id"),
        realm_depth=data.get("realm_depth", 1),
        default_terrain=tile_types.T_PLAIN,
    )
    gamemap.terrain = _unpack_u8(data["terrain"], (w, h))
    gamemap.explored = _unpack_u8(data["explored"], (w, h), dtype=np.bool_)
    gamemap.refresh_tile_flags()
    gamemap.rebuild_wall_glyphs()
    if data["map_type"] == "realm":
        gamemap.upstairs_xy = tuple(data["upstairs_xy"])
        gamemap.downstairs_xy = tuple(data["downstairs_xy"])
        if gamemap.realm_id is not None:
            gamemap.theme_key = engine.content.realm_def(gamemap.realm_id)["theme"]
    else:
        gamemap.region_ids = _unpack_u8(data["region_ids"], (w, h))
        gamemap.landmarks = data["landmarks"]
        gamemap.spawn_xy = tuple(data["spawn_xy"])
        gamemap.fov_radius = data.get("fov_radius", 14)
    _restore_entities(engine, gamemap, data["entities"])
    return gamemap


def _restore_entities(engine, gamemap, entities: list) -> None:
    content = engine.content
    for entry in entities:
        kind = entry["kind"]
        if kind == "gate":
            content.build_realm_gate(entry["realm_id"], gamemap, entry["x"], entry["y"], sealed=entry["sealed"])
        elif kind == "item":
            content.build_item(entry["id"], gamemap, entry["x"], entry["y"])
        elif kind == "material":
            material = content.build_item(entry["id"], gamemap, entry["x"], entry["y"])
            material.stack = int(entry.get("stack", 1))
        elif kind == "node":
            content.build_resource_node(entry["node"], gamemap, entry["x"], entry["y"])
        elif kind == "monster":
            actor = content.build_monster(entry["id"], gamemap, entry["x"], entry["y"])
            actor.fighter.hp = entry["hp"]
            actor.fighter.dot = list(entry["dot"])
            actor.fighter.stun_turns = entry["stun_turns"]
            actor.fighter.buffs = {k: list(v) for k, v in entry["buffs"].items()}
            if "summon_ttl" in entry:
                actor.summon_ttl = entry["summon_ttl"]


def _restore_player(engine, data: dict):
    content = engine.content
    player = content.build_player(engine.world, data["x"], data["y"], tuple(data["class_ids"]))
    fighter = player.fighter
    fighter.base_max_hp = data["base_max_hp"]
    fighter.base_max_mp = data["base_max_mp"]
    fighter.base_power = data["base_power"]
    fighter.base_defense = data["base_defense"]
    fighter._hp = data["hp"]
    fighter._mp = data["mp"]
    fighter.dot = list(data["dot"])
    fighter.stun_turns = data["stun_turns"]
    fighter.buffs = {k: list(v) for k, v in data["buffs"].items()}
    player.level.current_level = data["level"]
    player.level.current_xp = data["xp"]
    player.skill_points = data["skill_points"]
    # 新档存 skill_levels（1-10 级）；旧档只有 learned_skills 列表 → 全部视为 1 级
    player.skill_levels = {str(k): int(v) for k, v in data.get("skill_levels", {}).items()}
    for legacy_id in data.get("learned_skills", []):
        player.skill_levels.setdefault(str(legacy_id), 1)
    for entry in data["inventory"]:
        # 新档存 {id, stack}；旧档存纯 id（兼容）
        entry_id = entry["id"] if isinstance(entry, dict) else entry
        if entry_id is None:
            continue
        item = content.build_item(entry_id, engine.world, 0, 0)  # 行囊物品坐标无意义
        engine.world.entities.discard(item)
        item.gamemap = None
        if isinstance(entry, dict) and "material" in content.items.get(entry_id, {}).get("tags", []):
            item.stack = int(entry.get("stack", 1))
        player.inventory.items.append(item)
    for slot, iid in data["equipped"].items():
        if iid is None:
            continue
        item = content.build_item(iid, engine.world, 0, 0)
        engine.world.entities.discard(item)
        item.gamemap = None
        player.equipment.slots[slot] = item
    return player


def load_save_data() -> Optional[dict]:
    path = save_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if data.get("version") != SAVE_VERSION:
        return None
    return data


def load_engine(content, settings) -> Optional["Engine"]:
    """从存档重建 Engine；无存档/版本不符返回 None。"""
    from engine import Engine

    data = load_save_data()
    if data is None:
        return None
    engine = Engine.__new__(Engine)
    Engine._restore(engine, content, settings, data)
    return engine
