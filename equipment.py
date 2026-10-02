"""装备组件：五槽（兵/甲/履/佩/冠），加成与词条聚合。

装备 Item 定义在 items.json 的 equipment 节（slot/bonuses/affixes），
由 content_loader 构建成 EquippedItem 挂到 Item 上；Actor 侧挂 Equipment
管理槽位。战斗数值聚合在 fighter.py 读取 Equipment.bonuses()。
"""

from __future__ import annotations

import typing

import exceptions
from base_component import BaseComponent

if typing.TYPE_CHECKING:
    from entity import Item

SLOT_ORDER = ("weapon", "armor", "boots", "amulet", "helm")


class EquippedItem:
    """装备数据组件（挂在 Item 上）：槽位 + 基础加成 + 词条。"""

    def __init__(self, slot: str, bonuses: dict | None = None, affixes: list | None = None) -> None:
        self.slot = slot
        self.bonuses = dict(bonuses or {})
        self.affixes = list(affixes or [])

    def affix_summary(self) -> dict:
        """词条 id -> 叠加值。"""
        summary: dict[str, int] = {}
        for affix in self.affixes:
            summary[affix["id"]] = summary.get(affix["id"], 0) + int(affix["value"])
        return summary


class Equipment(BaseComponent):
    """玩家装备栏：五槽互换管理 + 聚合查询。"""

    def __init__(self) -> None:
        self.slots: dict[str, "Item | None"] = dict.fromkeys(SLOT_ORDER)

    def equip(self, item: "Item") -> "Item | None":
        """装备一件（物品须在行囊中）；被顶替的旧件返回给调用方放回行囊。"""
        gear = item.equipment
        if gear is None:
            raise exceptions.Impossible("not equipment")
        replaced = self.slots[gear.slot]
        self.slots[gear.slot] = item
        inventory = self.parent.inventory
        if inventory is not None and item in inventory.items:
            inventory.items.remove(item)
        return replaced

    def unequip_slot(self, slot: str) -> "Item | None":
        """卸下槽位，返回该物品（调用方负责放回行囊）。"""
        item = self.slots.get(slot)
        if item is not None:
            self.slots[slot] = None
        return item

    def is_equipped(self, item: "Item") -> bool:
        return item in self.equipped_items

    @property
    def equipped_items(self) -> list:
        return [item for item in self.slots.values() if item is not None]

    def bonuses(self) -> dict[str, int]:
        """全部已装备件的基础加成求和：power/defense/max_hp/max_mp。"""
        totals: dict[str, int] = {}
        for item in self.equipped_items:
            for key, value in item.equipment.bonuses.items():
                totals[key] = totals.get(key, 0) + int(value)
        return totals

    def bonus(self, key: str) -> int:
        return self.bonuses().get(key, 0)

    def affix(self, affix_id: str) -> int:
        """指定词条 id 的叠加值（按技能 tag 加伤/减耗等）。"""
        return sum(
            item.equipment.affix_summary().get(affix_id, 0) for item in self.equipped_items
        )
