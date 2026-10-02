"""物品效果组件（可消耗物）。

注册表 CONSUMABLE_TYPES 供 content_loader 分发：数据里写
"consumable": {"type": "heal", "amount": 12}。
新效果 = 新类 + 注册 + 数据引用。
"""

from __future__ import annotations

import typing

import exceptions
from base_component import BaseComponent

if typing.TYPE_CHECKING:
    from actions import ItemAction
    from entity import Actor


class Consumable(BaseComponent):
    def activate(self, action: "ItemAction") -> None:
        raise NotImplementedError()

    def consume(self) -> None:
        """使用后从行囊移除。"""
        item = self.parent
        inventory = self.engine.player.inventory
        if item in inventory.items:
            inventory.items.remove(item)


class HealConsumable(Consumable):
    def __init__(self, amount: int) -> None:
        self.amount = amount

    def activate(self, action: "ItemAction") -> None:
        strings = self.engine.content.strings
        player = self.engine.player
        if player.fighter.hp >= player.fighter.max_hp:
            raise exceptions.Impossible(strings["heal_full"])
        healed = player.fighter.heal(self.amount)
        self.engine.message_log.add_message(strings["heal_used"].format(amount=healed), "heal")
        self.engine.effects.spawn_heal(player.x, player.y, healed)
        self.consume()


class LightningConsumable(Consumable):
    def __init__(self, damage: int, max_range: int) -> None:
        self.damage = damage
        self.max_range = max_range

    def activate(self, action: "ItemAction") -> None:
        strings = self.engine.content.strings
        engine = self.engine
        target: "Actor | None" = None
        closest_distance = self.max_range + 0.5
        for actor in engine.gamemap.actors:
            if actor is engine.player or not actor.is_alive:
                continue
            if not engine.gamemap.visible[actor.x, actor.y]:
                continue
            distance = actor.distance_to(engine.player)
            if distance <= self.max_range and distance < closest_distance:
                target = actor
                closest_distance = distance
        if target is None:
            raise exceptions.Impossible(strings["lightning_no_target"])
        engine.message_log.add_message(
            strings["lightning_used"].format(target=target.name, damage=self.damage), "lightning"
        )
        bolt_color = tuple(engine.content.theme["messages"]["lightning"])
        engine.effects.spawn_lightning(target.x, target.y, self.damage, bolt_color)
        target.fighter.hp -= self.damage
        self.consume()


CONSUMABLE_TYPES = {
    "heal": HealConsumable,
    "lightning": LightningConsumable,
}
