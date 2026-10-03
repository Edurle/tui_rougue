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


class HealMpConsumable(Consumable):
    """回气散：恢复真气。"""

    def __init__(self, amount: int) -> None:
        self.amount = amount

    def activate(self, action: "ItemAction") -> None:
        strings = self.engine.content.strings
        player = self.engine.player
        if player.fighter.mp >= player.fighter.max_mp:
            raise exceptions.Impossible(strings["mp_full"])
        restored = player.fighter.restore_mp(self.amount)
        self.engine.message_log.add_message(
            strings["heal_mp_used"].format(amount=restored), "heal"
        )
        self.engine.effects.spawn_mp(player.x, player.y, restored)
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


class CleanseConsumable(Consumable):
    """解毒丹：清除自身蛊毒。"""

    def activate(self, action: "ItemAction") -> None:
        strings = self.engine.content.strings
        player = self.engine.player
        if not player.fighter.poisoned:
            raise exceptions.Impossible(strings["cleanse_no_poison"])
        player.fighter.dot = [0, 0]
        self.engine.message_log.add_message(strings["cleanse_used"], "heal")
        self.engine.effects.spawn_heal(player.x, player.y, 0)
        self.consume()


class BuffItemConsumable(Consumable):
    """药丹/符箓：临时提升攻或防（走 fighter 的回合 buff 状态机）。"""

    def __init__(self, stat: str, amount: int, turns: int) -> None:
        self.stat = stat
        self.amount = amount
        self.turns = turns

    def activate(self, action: "ItemAction") -> None:
        strings = self.engine.content.strings
        player = self.engine.player
        player.fighter.apply_buff(self.stat, self.amount, self.turns)
        key = f"buff_item_{self.stat}"
        self.engine.message_log.add_message(
            strings[key].format(amount=self.amount, turns=self.turns), "buff"
        )
        self.engine.effects.spawn_buff(player.x, player.y)
        self.consume()


class StunAreaConsumable(Consumable):
    """定身符：视野内全体敌人神魂受震。"""

    def __init__(self, turns: int, radius: int = 12) -> None:
        self.turns = turns
        self.radius = radius

    def activate(self, action: "ItemAction") -> None:
        strings = self.engine.content.strings
        engine = self.engine
        targets = [
            actor
            for actor in engine.gamemap.actors
            if actor.team == "wild"
            and actor.is_alive
            and engine.gamemap.visible[actor.x, actor.y]
            and actor.distance_to(engine.player) <= self.radius
        ]
        if not targets:
            raise exceptions.Impossible(strings["lightning_no_target"])
        for target in targets:
            target.fighter.apply_stun(self.turns)
            engine.effects.spawn_stun(target.x, target.y)
        engine.message_log.add_message(
            strings["talisman_stun"].format(count=len(targets)), "lightning"
        )
        self.consume()


CONSUMABLE_TYPES = {
    "heal": HealConsumable,
    "heal_mp": HealMpConsumable,
    "lightning": LightningConsumable,
    "cleanse": CleanseConsumable,
    "buff_item": BuffItemConsumable,
    "stun_area": StunAreaConsumable,
}
