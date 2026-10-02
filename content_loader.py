"""内容加载器：把 data/content/*.json 转成游戏实体。

设计约束：
- 代码不含任何内容数值；数值、文案、投放权重全部在 JSON。
- 组件按 JSON 里的 type 字符串从各模块的注册表分发；未知类型报错并指明出处。
- 加载时做 schema 校验，坏数据在启动瞬间失败，绝不在对局中途崩。
- hexagrams.json / crafting.json 为周易、天工开物系统的占位数据，此版本
  仅校验可读，不消费——将来接入时在本文件增加对应构建函数即可。
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

from ai import AI_TYPES
from consumable import CONSUMABLE_TYPES
from entity import Actor, Item
from fighter import Fighter
from inventory import Inventory
from level import Level
from paths import resource_path

CONTENT_DIR = "data/content"


class ContentError(Exception):
    """内容数据不合法。"""


def _load_json(path: Path) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise ContentError(f"无法读取内容文件 {path}: {exc}") from exc


def _require(mapping: dict, key: str, owner: str) -> Any:
    if key not in mapping:
        raise ContentError(f"{owner} 缺少必需字段 '{key}'")
    return mapping[key]


def _rgb(value: Any, owner: str) -> tuple:
    if not (isinstance(value, (list, tuple)) and len(value) == 3):
        raise ContentError(f"{owner} 的 color 必须是 [R, G, B]")
    return tuple(int(c) for c in value)


class Content:
    """已加载的全部内容数据 + 实体工厂。整个进程加载一次。"""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

        monsters_raw = _load_json(directory / "monsters.json")
        items_raw = _load_json(directory / "items.json")
        spawn_raw = _load_json(directory / "spawn_tables.json")
        self.strings: Dict[str, str] = {
            k: v for k, v in _load_json(directory / "strings.json").items() if not k.startswith("_")
        }

        self.player_def: dict = _load_json(directory / "player.json")
        self.monsters: Dict[str, dict] = {
            k: v for k, v in monsters_raw.items() if not k.startswith("_")
        }
        self.items: Dict[str, dict] = {k: v for k, v in items_raw.items() if not k.startswith("_")}
        self.spawn_monsters: List[dict] = spawn_raw["monsters"]
        self.spawn_items: List[dict] = spawn_raw["items"]
        self.per_room: dict = spawn_raw["per_room"]

        self._validate()

    # ---- 校验 ----

    def _validate(self) -> None:
        for mid, mdef in self.monsters.items():
            _require(mdef, "name", f"怪物 {mid}")
            _require(mdef, "char", f"怪物 {mid}")
            _rgb(mdef["color"], f"怪物 {mid}")
            comps = _require(mdef, "components", f"怪物 {mid}")
            fighter = _require(comps, "fighter", f"怪物 {mid}")
            for field_name in ("hp", "power", "defense", "xp_reward"):
                _require(fighter, field_name, f"怪物 {mid}.fighter")
            ai_type = _require(_require(comps, "ai", f"怪物 {mid}"), "type", f"怪物 {mid}.ai")
            if ai_type not in AI_TYPES:
                raise ContentError(
                    f"怪物 {mid} 的 ai.type '{ai_type}' 未注册，可用：{sorted(AI_TYPES)}"
                )
        for iid, idef in self.items.items():
            _require(idef, "name", f"物品 {iid}")
            _require(idef, "char", f"物品 {iid}")
            _rgb(idef["color"], f"物品 {iid}")
            cons = _require(idef, "consumable", f"物品 {iid}")
            ctype = _require(cons, "type", f"物品 {iid}.consumable")
            if ctype not in CONSUMABLE_TYPES:
                raise ContentError(
                    f"物品 {iid} 的 consumable.type '{ctype}' 未注册，可用：{sorted(CONSUMABLE_TYPES)}"
                )
        for kind, table, pool in (
            ("monsters", self.spawn_monsters, self.monsters),
            ("items", self.spawn_items, self.items),
        ):
            for entry in table:
                if entry["id"] not in pool:
                    raise ContentError(f"投放表 {kind} 引用了不存在的 id '{entry['id']}'")
                if entry["weight"] <= 0:
                    raise ContentError(f"投放表 {kind} 中 {entry['id']} 的 weight 必须为正")
        for floor in range(1, 20):
            if not self.monster_ids_for_floor(floor):
                raise ContentError(f"第 {floor} 层没有任何可投放怪物")
            if not self.item_ids_for_floor(floor):
                raise ContentError(f"第 {floor} 层没有任何可投放物品")

    # ---- 投放 ----

    @staticmethod
    def _pick_ids(table: List[dict], floor: int) -> List[str]:
        matched = [
            (e["id"], e["weight"])
            for e in table
            if e["min_floor"] <= floor and (e["max_floor"] is None or floor <= e["max_floor"])
        ]
        return [i for i, _ in matched]

    def monster_ids_for_floor(self, floor: int) -> List[str]:
        return self._pick_ids(self.spawn_monsters, floor)

    def item_ids_for_floor(self, floor: int) -> List[str]:
        return self._pick_ids(self.spawn_items, floor)

    def random_monster_id(self, floor: int, rng: random.Random) -> str:
        matched = [
            (e["id"], e["weight"])
            for e in self.spawn_monsters
            if e["min_floor"] <= floor and (e["max_floor"] is None or floor <= e["max_floor"])
        ]
        ids, weights = zip(*matched)
        return rng.choices(ids, weights=weights, k=1)[0]

    def random_item_id(self, floor: int, rng: random.Random) -> str:
        matched = [
            (e["id"], e["weight"])
            for e in self.spawn_items
            if e["min_floor"] <= floor and (e["max_floor"] is None or floor <= e["max_floor"])
        ]
        ids, weights = zip(*matched)
        return rng.choices(ids, weights=weights, k=1)[0]

    # ---- 实体工厂 ----

    def build_monster(self, monster_id: str, gamemap, x: int, y: int) -> Actor:
        mdef = self.monsters[monster_id]
        fighter_data = mdef["components"]["fighter"]
        ai_data = mdef["components"]["ai"]
        actor = Actor(
            gamemap=gamemap,
            x=x,
            y=y,
            char=mdef["char"],
            color=_rgb(mdef["color"], f"怪物 {monster_id}"),
            name=mdef["name"],
            blocks_movement=True,
            tags=list(mdef.get("tags", [])),
            lore=mdef.get("lore", ""),
        )
        actor.fighter = Fighter(
            hp=fighter_data["hp"],
            power=fighter_data["power"],
            defense=fighter_data["defense"],
            xp_reward=fighter_data.get("xp_reward", 0),
        )
        actor.fighter.parent = actor
        actor.ai = AI_TYPES[ai_data["type"]]()
        actor.ai.parent = actor
        return actor

    def build_item(self, item_id: str, gamemap, x: int, y: int) -> Item:
        idef = self.items[item_id]
        cons_data = idef["consumable"]
        item = Item(
            gamemap=gamemap,
            x=x,
            y=y,
            char=idef["char"],
            color=_rgb(idef["color"], f"物品 {item_id}"),
            name=idef["name"],
            tags=list(idef.get("tags", [])),
            lore=idef.get("lore", ""),
        )
        consumable_cls = CONSUMABLE_TYPES[cons_data["type"]]
        kwargs = {k: v for k, v in cons_data.items() if k != "type"}
        item.consumable = consumable_cls(**kwargs)
        item.consumable.parent = item
        return item

    def build_player(self, gamemap, x: int, y: int) -> Actor:
        pdef = self.player_def
        fighter_data = _require(pdef, "fighter", "player.json")
        level_data = _require(pdef, "level", "player.json")
        inv_data = _require(pdef, "inventory", "player.json")
        player = Actor(
            gamemap=gamemap,
            x=x,
            y=y,
            char=pdef["char"],
            color=_rgb(pdef["color"], "player.json"),
            name=pdef["name"],
            blocks_movement=True,
            tags=list(pdef.get("tags", [])),
        )
        player.fighter = Fighter(
            hp=fighter_data["hp"],
            power=fighter_data["power"],
            defense=fighter_data["defense"],
        )
        player.fighter.parent = player
        player.level = Level(
            base_xp=level_data["base_xp"],
            step_xp=level_data["step_xp"],
            bonuses=level_data["per_level"],
        )
        player.level.parent = player
        player.inventory = Inventory(capacity=inv_data["capacity"])
        player.inventory.parent = player
        return player


def load_content() -> Content:
    return Content(resource_path(CONTENT_DIR))
