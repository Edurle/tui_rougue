"""行囊组件。"""

from __future__ import annotations

import typing

from base_component import BaseComponent

if typing.TYPE_CHECKING:
    from item import Item  # noqa: F401


class InventoryFull(Exception):
    pass


class Inventory(BaseComponent):
    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self.items: list = []

    def add(self, item) -> None:
        if len(self.items) >= self.capacity:
            raise InventoryFull()
        self.items.append(item)
