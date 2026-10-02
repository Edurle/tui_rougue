"""内容加载器：把 data/content/*.json 转成游戏实体。

设计约束：
- 代码不含任何内容数值；数值、文案、投放权重全部在 JSON。
- 组件按 JSON 里的 type 字符串从各模块的注册表分发；未知类型报错并指明出处。
- 加载时做 schema 校验，坏数据在启动瞬间失败，绝不在对局中途崩。
- classes.json / skills.json 支撑双职业与技能树（DAG、链首、效果类均校验）。
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
from equipment import SLOT_ORDER, EquippedItem
from fighter import Fighter
from inventory import Inventory
from level import Level
from paths import resource_path
from skills import SKILL_EFFECTS
from tileset_art import ART_REGISTRY

CONTENT_DIR = "data/content"

SUPPORTED_LANGS = ("zh_CN", "en_US")
DEFAULT_LANG = "zh_CN"

# 默认双职业（测试/冒烟用；正常流程由职业选择界面传入）
DEFAULT_CLASS_IDS = ("leifa", "fushi")

# 效果类集合中计为"伤害/召唤/控制"的技能（单机铁律：每职业 ≥4）
_OFFENSIVE_EFFECTS = {"damage_nearest", "damage_aoe_self", "poison_dot", "stun_aoe", "summon"}

VALID_BONUS_KEYS = {"power", "defense", "max_hp", "max_mp"}
VALID_AFFIX_IDS = {
    "thunder_damage",
    "aoe_damage",
    "poison_damage",
    "heal_power",
    "mp_cost_reduce",
    "kill_heal",
    "resist_thunder",
    "resist_fire",
    "resist_poison",
    "resist_stun",
}
RESIST_LIMIT = 80
ELEMENTAL_ATTACK_TAGS = {"thunder", "fire", "poison"}


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


class TextResolver:
    """name/lore 等文本字段解析：字符串=全语言同值；dict=按语言取，缺语言回退 zh_CN。"""

    def __init__(self, lang: str) -> None:
        self.lang = lang

    def __call__(self, value: Any) -> str:
        if not isinstance(value, dict):
            return str(value)
        if self.lang in value:
            return str(value[self.lang])
        if DEFAULT_LANG in value:
            return str(value[DEFAULT_LANG])
        return str(next(iter(value.values())))


class Content:
    """已加载的全部内容数据 + 实体工厂。整个进程加载一次。"""

    def __init__(self, directory: Path, lang: str = DEFAULT_LANG) -> None:
        if lang not in SUPPORTED_LANGS:
            raise ContentError(f"不支持的语言 '{lang}'，可用：{SUPPORTED_LANGS}")
        self.lang = lang
        self._ = TextResolver(lang)
        self.directory = directory

        monsters_raw = _load_json(directory / "monsters.json")
        items_raw = _load_json(directory / "items.json")
        spawn_raw = _load_json(directory / "spawn_tables.json")
        classes_raw = _load_json(directory / "classes.json")
        skills_raw = _load_json(directory / "skills.json")

        def load_strings(lang_code: str) -> Dict[str, str]:
            return {
                k: v
                for k, v in _load_json(directory / "strings" / f"{lang_code}.json").items()
                if not k.startswith("_")
            }

        self.strings: Dict[str, str] = load_strings(lang)
        base = load_strings(DEFAULT_LANG)
        for key, value in base.items():
            self.strings.setdefault(key, value)

        self.player_def: dict = _load_json(directory / "player.json")
        self.theme: dict = _load_json(directory / "theme.json")
        self.regions: List[dict] = _load_json(directory / "regions.json")["regions"]
        self.realms: Dict[str, dict] = {
            r["id"]: r for r in _load_json(directory / "realms.json")["realms"]
        }
        self.monsters: Dict[str, dict] = {
            k: v for k, v in monsters_raw.items() if not k.startswith("_")
        }
        self.items: Dict[str, dict] = {k: v for k, v in items_raw.items() if not k.startswith("_")}
        self.classes: Dict[str, dict] = {
            k: v for k, v in classes_raw.items() if not k.startswith("_")
        }
        self.skills: Dict[str, dict] = {
            k: v for k, v in skills_raw.items() if not k.startswith("_")
        }
        self.equip_items: Dict[str, dict] = {
            k: v for k, v in self.items.items() if "equipment" in v
        }
        self.spawn_monsters: List[dict] = spawn_raw["monsters"]
        self.spawn_items: List[dict] = spawn_raw["items"]
        self.per_room: dict = spawn_raw["per_room"]

        self._validate()
        self._validate_theme()
        self._validate_regions()
        self._validate_realms()
        self._validate_classes_skills()

    def _validate_regions(self) -> None:
        valid_zones = {"center", "south", "west", "north", "east", "outer"}
        seen_zones: set = set()
        for region in self.regions:
            for field_name in ("id", "name", "zone", "base_difficulty", "mountains"):
                _require(region, field_name, f"区域 {region.get('id', '?')}")
            if region["zone"] not in valid_zones:
                raise ContentError(
                    f"区域 {region['id']} 的 zone '{region['zone']}' 非法，可用：{sorted(valid_zones)}"
                )
            if region["zone"] in seen_zones:
                raise ContentError(f"区域 {region['id']} 的 zone '{region['zone']}' 与其他区域重复")
            seen_zones.add(region["zone"])
            difficulty = region["base_difficulty"]
            if not isinstance(difficulty, int) or difficulty < 0:
                raise ContentError(f"区域 {region['id']} 的 base_difficulty 必须是非负整数")
            if not region["mountains"]:
                raise ContentError(f"区域 {region['id']} 山名列表为空")
            if not isinstance(region.get("mountain_count", 0), int) or region["mountain_count"] < 1:
                raise ContentError(f"区域 {region['id']} 的 mountain_count 必须是正整数")
        missing = valid_zones - seen_zones
        if missing:
            raise ContentError(f"regions.json 缺少 zone：{sorted(missing)}（六大经须齐备）")

    # ---- 山川游历区域 ----

    def region_by_id(self, region_id: str) -> dict:
        for region in self.regions:
            if region["id"] == region_id:
                return region
        raise ContentError(f"区域 '{region_id}' 不存在")

    def region_name(self, region_id: str) -> str:
        return self._(self.region_by_id(region_id)["name"])

    # ---- 秘境 ----

    def _validate_realms(self) -> None:
        region_ids = {r["id"] for r in self.regions}
        theme_keys = set(self.theme.get("realm_themes", {}))
        for rid, realm in self.realms.items():
            for field_name in ("name", "intro", "theme", "region", "depth", "boss"):
                _require(realm, field_name, f"秘境 {rid}")
            if realm["region"] not in region_ids:
                raise ContentError(f"秘境 {rid} 引用了不存在的区域 '{realm['region']}'")
            if realm["theme"] not in theme_keys:
                raise ContentError(
                    f"秘境 {rid} 的 theme '{realm['theme']}' 未在 theme.realm_themes 配置"
                )
            if not isinstance(realm["depth"], int) or not 2 <= realm["depth"] <= 5:
                raise ContentError(f"秘境 {rid} 的 depth 必须是 2-5 的整数")
            if realm["boss"] not in self.monsters:
                raise ContentError(f"秘境 {rid} 引用了不存在的 BOSS '{realm['boss']}'")
            if "boss" not in self.monsters[realm["boss"]].get("tags", []):
                raise ContentError(f"秘境 {rid} 的 BOSS '{realm['boss']}' 缺少 boss 标签")
        for region_id in region_ids:
            if not any(r["region"] == region_id for r in self.realms.values()):
                raise ContentError(f"区域 {region_id} 没有任何秘境")

    def realm_def(self, realm_id: str) -> dict:
        return self.realms[realm_id]

    def realm_name(self, realm_id: str) -> str:
        return self._(self.realms[realm_id]["name"])

    def realm_difficulty(self, realm_id: str, depth: int) -> int:
        """秘境层难度 = 所属区域基础难度 + (层深-1)*2。"""
        base = int(self.region_by_id(self.realms[realm_id]["region"])["base_difficulty"])
        return base + (depth - 1) * 2

    def build_realm_gate(self, realm_id: str, gamemap, x: int, y: int, sealed: bool = False):
        """秘境入口实体（不挡路，走上去按 > 进入）。"""
        from entity import Entity

        realm = self.realms[realm_id]
        return Entity(
            gamemap=gamemap,
            x=x,
            y=y,
            char="Ω",
            color=(120, 110, 160) if sealed else (170, 130, 230),
            name=self._(realm["name"]),
            blocks_movement=False,
            tags=["realm_gate", realm_id] + (["sealed"] if sealed else []),
            lore=self._(realm["intro"]),
            art="realm_gate_sealed" if sealed else "realm_gate",
        )

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
            for kind, value in mdef.get("resistances", {}).items():
                if kind not in ("thunder", "fire", "poison", "stun"):
                    raise ContentError(
                        f"怪物 {mid} 的抗性类型 '{kind}' 非法，可用：thunder/fire/poison/stun"
                    )
                if not isinstance(value, (int, float)) or not 0 < value <= RESIST_LIMIT:
                    raise ContentError(
                        f"怪物 {mid} 的抗性 {kind}={value} 必须在 (0, {RESIST_LIMIT}] 内"
                    )
            for tag in mdef.get("attack_tags", []):
                if tag not in ELEMENTAL_ATTACK_TAGS:
                    raise ContentError(
                        f"怪物 {mid} 的 attack_tags '{tag}' 非法，可用：{sorted(ELEMENTAL_ATTACK_TAGS)}"
                    )
        for iid, idef in self.items.items():
            _require(idef, "name", f"物品 {iid}")
            _require(idef, "char", f"物品 {iid}")
            _rgb(idef["color"], f"物品 {iid}")
            has_consumable = "consumable" in idef
            has_equipment = "equipment" in idef
            if not has_consumable and not has_equipment:
                raise ContentError(f"物品 {iid} 必须定义 consumable 或 equipment 之一")
            if has_consumable:
                cons = idef["consumable"]
                ctype = _require(cons, "type", f"物品 {iid}.consumable")
                if ctype not in CONSUMABLE_TYPES:
                    raise ContentError(
                        f"物品 {iid} 的 consumable.type '{ctype}' 未注册，可用：{sorted(CONSUMABLE_TYPES)}"
                    )
            if has_equipment:
                gear = idef["equipment"]
                slot = _require(gear, "slot", f"物品 {iid}.equipment")
                if slot not in SLOT_ORDER:
                    raise ContentError(
                        f"物品 {iid} 的装备槽 '{slot}' 非法，可用：{list(SLOT_ORDER)}"
                    )
                for key in gear.get("bonuses", {}):
                    if key not in VALID_BONUS_KEYS:
                        raise ContentError(
                            f"物品 {iid} 的加成键 '{key}' 非法，可用：{sorted(VALID_BONUS_KEYS)}"
                        )
                for affix in gear.get("affixes", []):
                    if affix.get("id") not in VALID_AFFIX_IDS:
                        raise ContentError(
                            f"物品 {iid} 的词条 '{affix.get('id')}' 非法，可用：{sorted(VALID_AFFIX_IDS)}"
                        )
        for pool_name, pool in (("怪物", self.monsters), ("物品", self.items), ("玩家", {"player": self.player_def})):
            for eid, edef in pool.items():
                art = edef.get("art")
                if art is not None and art not in ART_REGISTRY:
                    raise ContentError(
                        f"{pool_name} {eid} 的 art '{art}' 未注册，可用：{sorted(ART_REGISTRY)}"
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
        for difficulty in range(1, 21):
            if not self.monster_ids_for_difficulty(difficulty):
                raise ContentError(f"难度 {difficulty} 没有任何可投放怪物")
            if not self.item_ids_for_difficulty(difficulty):
                raise ContentError(f"难度 {difficulty} 没有任何可投放物品")

    def _validate_classes_skills(self) -> None:
        if len(self.classes) < 2:
            raise ContentError("classes.json 至少需要 2 个职业")
        for cid, cdef in self.classes.items():
            _require(cdef, "name", f"职业 {cid}")
            for field_name in ("hp", "power", "defense", "mp"):
                value = _require(cdef, field_name, f"职业 {cid}")
                if not isinstance(value, int) or value < 0 or (field_name != "defense" and value <= 0):
                    raise ContentError(f"职业 {cid} 的 {field_name} 必须是非负整数（defense 可为 0）")

        for sid, sdef in self.skills.items():
            if sdef.get("class") not in self.classes:
                raise ContentError(f"技能 {sid} 引用了不存在的职业 '{sdef.get('class')}'")
            slot = sdef.get("slot")
            if not isinstance(slot, int) or not 1 <= slot <= 8:
                raise ContentError(f"技能 {sid} 的 slot 必须是 1-8 的整数")
            _require(sdef, "name", f"技能 {sid}")
            eff_type = _require(sdef, "effect", f"技能 {sid}").get("type")
            if eff_type not in SKILL_EFFECTS:
                raise ContentError(
                    f"技能 {sid} 的 effect.type '{eff_type}' 未注册，可用：{sorted(SKILL_EFFECTS)}"
                )
            cost = sdef.get("cost", 1)
            if cost not in (1, 2):
                raise ContentError(f"技能 {sid} 的 cost 必须是 1 或 2")
            for req in sdef.get("requires", []):
                if req not in self.skills:
                    raise ContentError(f"技能 {sid} 的前置 '{req}' 不存在")
                if self.skills[req]["class"] != sdef["class"]:
                    raise ContentError(f"技能 {sid} 的前置 '{req}' 属于其他职业")

        by_class: Dict[str, List[dict]] = {}
        for sid, sdef in self.skills.items():
            by_class.setdefault(sdef["class"], []).append(sdef)
        for cid, skills in by_class.items():
            if len(skills) != 8:
                raise ContentError(f"职业 {cid} 应有 8 个技能，实际 {len(skills)}")
            slots = sorted(s["slot"] for s in skills)
            if slots != list(range(1, 9)):
                raise ContentError(f"职业 {cid} 的 slot 必须恰好覆盖 1-8")
            heads = sum(1 for s in skills if not s["requires"])
            if heads < 2:
                raise ContentError(f"职业 {cid} 的链首技能（无前置）应 ≥2，实际 {heads}")
            offensive = sum(1 for s in skills if s["effect"]["type"] in _OFFENSIVE_EFFECTS)
            if offensive < 4:
                raise ContentError(
                    f"职业 {cid} 的伤害/召唤/控制技能应 ≥4，实际 {offensive}"
                )
            self._assert_skill_dag_acyclic(cid, skills)
        for cid in self.classes:
            if cid not in by_class:
                raise ContentError(f"职业 {cid} 没有任何技能")

    @staticmethod
    def _assert_skill_dag_acyclic(class_id: str, skills: List[dict]) -> None:
        by_id = {f"s_{class_id}_{s['slot']}": s for s in skills}
        state: dict[str, int] = {}  # 0=未访问 1=栈中 2=完成

        def visit(skill_id: str) -> None:
            mark = state.get(skill_id, 0)
            if mark == 1:
                raise ContentError(f"职业 {class_id} 的技能前置关系成环（涉及 {skill_id}）")
            if mark == 2:
                return
            state[skill_id] = 1
            for req in by_id[skill_id].get("requires", []):
                if req in by_id:
                    visit(req)
            state[skill_id] = 2

        for skill_id in by_id:
            visit(skill_id)

    # ---- 职业/技能查询 ----

    def class_name(self, class_id: str) -> str:
        return self._(self.classes[class_id]["name"])

    def skills_for_class(self, class_id: str) -> List[dict]:
        """按 slot 排序的职业技能清单（带 id 注入）。"""
        result = [
            {"id": sid, **sdef} for sid, sdef in self.skills.items() if sdef["class"] == class_id
        ]
        result.sort(key=lambda s: s["slot"])
        return result

    def skill_for_slot(self, class_id: str, slot: int) -> Optional[dict]:
        for sid, sdef in self.skills.items():
            if sdef["class"] == class_id and sdef["slot"] == slot:
                return {"id": sid, **sdef}
        return None

    def _validate_theme(self) -> None:
        import tile_types

        theme = self.theme
        for key in ("background", "tiles", "terrains", "lighting", "stairs", "corpse_color", "player_corpse_color", "hud", "messages"):
            if key not in theme:
                raise ContentError(f"theme.json 缺少必需字段 '{key}'")
        for key in ("floor_light", "floor_dark", "wall_light", "wall_dark"):
            _rgb(theme["tiles"][key], f"theme.tiles.{key}")
        terrains_cfg = theme["terrains"]
        for tdef in tile_types.TERRAIN_DEFS.values():
            if tdef.key not in terrains_cfg:
                raise ContentError(
                    f"theme.terrains 缺少地形 '{tdef.key}'（tile_types 注册表要求全配）"
                )
            cfg = terrains_cfg[tdef.key]
            if not isinstance(cfg.get("char"), str) or not cfg["char"]:
                raise ContentError(f"theme.terrains.{tdef.key}.char 必须是非空字符")
            _rgb(cfg["light"], f"theme.terrains.{tdef.key}.light")
            _rgb(cfg["dark"], f"theme.terrains.{tdef.key}.dark")
        for key in ("inner_radius", "edge_falloff"):
            value = theme["lighting"][key]
            if not isinstance(value, (int, float)) or value < 0:
                raise ContentError(f"theme.lighting.{key} 必须是非负数")
        for key, mapping in (("hud", ("hp", "xp", "floor", "dead_tag")),):
            for sub in mapping:
                _rgb(theme[key][sub], f"theme.{key}.{sub}")
        for key in ("background", "corpse_color", "player_corpse_color", "stairs.light", "stairs.dark"):
            value = theme
            for part in key.split("."):
                value = value[part]
            _rgb(value, f"theme.{key}")
        _rgb(theme["ui"]["frame"], "theme.ui.frame")
        for kind, value in theme["messages"].items():
            _rgb(value, f"theme.messages.{kind}")

    # ---- 投放（统一难度轴）----

    @staticmethod
    def _pick_ids(table: List[dict], difficulty: int) -> List[str]:
        matched = [
            (e["id"], e["weight"])
            for e in table
            if e["min_difficulty"] <= difficulty
            and (e["max_difficulty"] is None or difficulty <= e["max_difficulty"])
        ]
        return [i for i, _ in matched]

    def monster_ids_for_difficulty(self, difficulty: int) -> List[str]:
        return self._pick_ids(self.spawn_monsters, difficulty)

    def item_ids_for_difficulty(self, difficulty: int) -> List[str]:
        return self._pick_ids(self.spawn_items, difficulty)

    def random_monster_id(self, difficulty: int, rng: random.Random) -> str:
        matched = [
            (e["id"], e["weight"])
            for e in self.spawn_monsters
            if e["min_difficulty"] <= difficulty
            and (e["max_difficulty"] is None or difficulty <= e["max_difficulty"])
        ]
        ids, weights = zip(*matched)
        return rng.choices(ids, weights=weights, k=1)[0]

    def random_item_id(self, difficulty: int, rng: random.Random) -> str:
        matched = [
            (e["id"], e["weight"])
            for e in self.spawn_items
            if e["min_difficulty"] <= difficulty
            and (e["max_difficulty"] is None or difficulty <= e["max_difficulty"])
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
            name=self._(mdef["name"]),
            blocks_movement=True,
            tags=list(mdef.get("tags", [])),
            lore=self._(mdef.get("lore", "")),
            art=mdef.get("art"),
        )
        actor.fighter = Fighter(
            hp=fighter_data["hp"],
            power=fighter_data["power"],
            defense=fighter_data["defense"],
            xp_reward=fighter_data.get("xp_reward", 0),
            resistances=mdef.get("resistances"),
        )
        actor.fighter.parent = actor
        actor.ai = AI_TYPES[ai_data["type"]]()
        actor.ai.parent = actor
        actor.attack_tags = list(mdef.get("attack_tags", []))
        return actor

    def build_item(self, item_id: str, gamemap, x: int, y: int) -> Item:
        idef = self.items[item_id]
        item = Item(
            gamemap=gamemap,
            x=x,
            y=y,
            char=idef["char"],
            color=_rgb(idef["color"], f"物品 {item_id}"),
            name=self._(idef["name"]),
            tags=list(idef.get("tags", [])),
            lore=self._(idef.get("lore", "")),
            art=idef.get("art"),
        )
        if "consumable" in idef:
            cons_data = idef["consumable"]
            consumable_cls = CONSUMABLE_TYPES[cons_data["type"]]
            kwargs = {k: v for k, v in cons_data.items() if k != "type"}
            item.consumable = consumable_cls(**kwargs)
            item.consumable.parent = item
        if "equipment" in idef:
            gear_data = idef["equipment"]
            item.equipment = EquippedItem(
                slot=gear_data["slot"],
                bonuses=gear_data.get("bonuses"),
                affixes=gear_data.get("affixes"),
            )
        return item

    def random_equipment_id(self, difficulty: int, rng: random.Random) -> Optional[str]:
        """怪物死亡掉落抽取：tier ≤ difficulty//4+2 的装备池随机一件。"""
        cap = difficulty // 4 + 2
        pool = [
            iid for iid, idef in self.equip_items.items() if int(idef.get("tier", 1)) <= cap
        ]
        if not pool:
            return None
        return rng.choice(sorted(pool))

    def build_player(
        self,
        gamemap,
        x: int,
        y: int,
        class_ids: tuple = DEFAULT_CLASS_IDS,
    ) -> Actor:
        pdef = self.player_def
        level_data = _require(pdef, "level", "player.json")
        inv_data = _require(pdef, "inventory", "player.json")
        if len(class_ids) != 2 or class_ids[0] == class_ids[1]:
            raise ContentError(f"双职业定义非法：{class_ids}")
        for cid in class_ids:
            if cid not in self.classes:
                raise ContentError(f"职业 '{cid}' 不存在于 classes.json")
        primary, secondary = (self.classes[c] for c in class_ids)
        # 双职业合并：主职业全量 + 副职业气血/真气上限各半（向上取整）
        hp = int(primary["hp"]) + (int(secondary["hp"]) + 1) // 2
        mp = int(primary["mp"]) + (int(secondary["mp"]) + 1) // 2
        player = Actor(
            gamemap=gamemap,
            x=x,
            y=y,
            char=pdef["char"],
            color=_rgb(pdef["color"], "player.json"),
            name=self._(pdef["name"]),
            blocks_movement=True,
            tags=list(pdef.get("tags", [])),
            team="player",
        )
        player.class_ids = tuple(class_ids)
        player.skill_points = 2
        player.learned_skills = set()
        player.fighter = Fighter(
            hp=hp,
            power=int(primary["power"]),
            defense=int(primary["defense"]),
            max_mp=mp,
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
        from equipment import Equipment

        player.equipment = Equipment()
        player.equipment.parent = player
        return player

    def build_summon(
        self,
        gamemap,
        x: int,
        y: int,
        *,
        name: str,
        char: str,
        color: tuple,
        hp: int,
        power: int,
        duration: int,
    ) -> Actor:
        """契约兽：玩家阵营，AlliedAI，到时消散（engine 递减 summon_ttl）。"""
        from ai import AlliedAI

        beast = Actor(
            gamemap=gamemap,
            x=x,
            y=y,
            char=char,
            color=color,
            name=name,
            blocks_movement=True,
            team="player",
        )
        beast.fighter = Fighter(hp=hp, power=power, defense=0)
        beast.fighter.parent = beast
        beast.ai = AlliedAI()
        beast.ai.parent = beast
        beast.summon_ttl = duration
        return beast


def load_content(lang: str = DEFAULT_LANG) -> Content:
    return Content(resource_path(CONTENT_DIR), lang=lang)
