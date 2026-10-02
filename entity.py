"""实体：地图上一切可见之物。

Entity —— 无交互之物（地形装饰等）
Actor  —— 战斗单位（玩家、异兽），挂 Fighter/AI/Level/Inventory 组件
Item   —— 物品，挂 Consumable 组件

组件一律由 content_loader 按数据定义挂载，本模块不含内容数值。
"""

from __future__ import annotations

import typing
from typing import List, Optional, Tuple

if typing.TYPE_CHECKING:
    from ai import BaseAI
    from consumable import Consumable
    from engine import Engine
    from equipment import EquippedItem
    from equipment import Equipment as EquipmentComponent
    from fighter import Fighter
    from game_map import GameMap
    from inventory import Inventory
    from level import Level


class Entity:
    def __init__(
        self,
        gamemap: Optional["GameMap"] = None,
        x: int = 0,
        y: int = 0,
        char: str = "?",
        color: Tuple[int, int, int] = (255, 255, 255),
        name: str = "<无名之物>",
        blocks_movement: bool = False,
        tags: Optional[List[str]] = None,
        lore: str = "",
        art: Optional[str] = None,
    ) -> None:
        self.x = x
        self.y = y
        self.char = char
        self.color = color
        self.name = name
        self.blocks_movement = blocks_movement
        self.tags = tags or []
        self.lore = lore
        self.art = art
        self.gamemap = gamemap
        if gamemap:
            gamemap.entities.add(self)

    def place(self, gamemap: "GameMap", x: int, y: int) -> None:
        """移动到指定位置；跨层（下楼）时转移所属地图。"""
        self.x = x
        self.y = y
        if gamemap is not self.gamemap:
            if self.gamemap:
                self.gamemap.entities.discard(self)
            self.gamemap = gamemap
            gamemap.entities.add(self)

    def distance_to(self, other: "Entity") -> float:
        from math import hypot

        return hypot(other.x - self.x, other.y - self.y)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} '{self.name}' at ({self.x},{self.y})>"


class Actor(Entity):
    def __init__(
        self,
        *,
        char: str = "?",
        color=(255, 255, 255),
        name="<无名之物>",
        team: str = "wild",
        **kwargs,
    ) -> None:
        super().__init__(char=char, color=color, name=name, **kwargs)
        self.fighter: Optional["Fighter"] = None
        self.ai: Optional["BaseAI"] = None
        self.level: Optional["Level"] = None
        self.inventory: Optional["Inventory"] = None
        self.equipment: Optional["EquipmentComponent"] = None
        # 阵营："player"（玩家与召唤兽）/"wild"（异兽）；AI 据此选取敌对目标
        self.team = team
        # 普攻附带元素（thunder/fire/poison）：命中按目标抗性折算（数据注入）
        self.attack_tags: list = []
        # 双职业与技能（玩家专用；召唤兽仅用到 team/summon_ttl）
        self.class_ids: tuple = ()
        self.skill_points: int = 0
        self.learned_skills: set = set()
        # 召唤时限（None=非召唤）；到 0 由引擎移除
        self.summon_ttl: Optional[int] = None

    @property
    def is_alive(self) -> bool:
        return self.fighter is not None


class Item(Entity):
    def __init__(self, *, char: str = "?", color=(255, 255, 255), name="<无名之物>", **kwargs) -> None:
        super().__init__(char=char, color=color, name=name, **kwargs)
        self.consumable: Optional["Consumable"] = None
        self.equipment: Optional["EquippedItem"] = None
