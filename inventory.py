"""行囊组件（无容量上限：拾取/炼制不再因满包受阻）。"""

from __future__ import annotations

import typing

from base_component import BaseComponent

if typing.TYPE_CHECKING:
    from item import Item  # noqa: F401


class Inventory(BaseComponent):
    def __init__(self) -> None:
        self.items: list = []

    def add(self, item) -> None:
        """入囊：材料与既有同类堆叠合并，其余直接追加（无上限）。"""
        if item.is_material:
            for existing in self.items:
                if existing.is_material and existing.name == item.name:
                    existing.stack += item.stack
                    return
        self.items.append(item)

    def count_material(self, item_id: str, content) -> int:
        """行囊中指定材料 id 的堆叠总数（按 items.json 定义比对）。"""
        total = 0
        for existing in self.items:
            if existing.is_material and content.items.get(item_id) is not None:
                if existing.char == content.items[item_id]["char"] and existing.name == content._(
                    content.items[item_id]["name"]
                ):
                    total += existing.stack
        return total

    def take_material(self, item_id: str, count: int, content) -> int:
        """从行囊扣减指定材料（跨堆叠），返回实际扣减数。"""
        definition = content.items.get(item_id)
        if definition is None:
            return 0
        remaining = count
        for existing in list(self.items):
            if remaining <= 0:
                break
            if existing.is_material and existing.char == definition["char"] and existing.name == content._(definition["name"]):
                take = min(existing.stack, remaining)
                existing.stack -= take
                remaining -= take
                if existing.stack <= 0:
                    self.items.remove(existing)
        return count - remaining
