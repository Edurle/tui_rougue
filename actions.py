"""动作系统：玩家/异兽回合中发生的一切"意图"。

动作执行成功即推进一个回合（随后敌人行动）；无法执行时抛 Impossible，
异常消息作为提示展示给玩家。新系统（占卜、合成等）将来以新 Action 子类接入。
"""

from __future__ import annotations

import typing

import exceptions
from inventory import InventoryFull

if typing.TYPE_CHECKING:
    from engine import Engine
    from entity import Actor, Item


class Action:
    def perform(self, engine: "Engine") -> None:
        raise NotImplementedError()


class EscapeAction(Action):
    def perform(self, engine: "Engine") -> None:
        raise SystemExit()


class WaitAction(Action):
    def perform(self, engine: "Engine") -> None:
        pass


class ActionWithDirection(Action):
    def __init__(self, entity: "Actor", dx: int, dy: int) -> None:
        self.entity = entity
        self.dx = dx
        self.dy = dy

    @property
    def dest_xy(self) -> tuple[int, int]:
        return self.entity.x + self.dx, self.entity.y + self.dy

    @typing.no_type_check
    def target_actor(self) -> "Actor | None":
        return self.entity.gamemap.get_actor_at(*self.dest_xy)


class MeleeAction(ActionWithDirection):
    def perform(self, engine: "Engine") -> None:
        target = self.target_actor()
        if target is None or not target.is_alive:
            return
        self.entity.fighter.attack(target.fighter)


class MovementAction(ActionWithDirection):
    def perform(self, engine: "Engine") -> None:
        dest_x, dest_y = self.dest_xy
        if not self.entity.gamemap.in_bounds(dest_x, dest_y):
            return
        if not self.entity.gamemap.tiles["walkable"][dest_x, dest_y]:
            return
        if self.entity.gamemap.get_blocking_entity_at(dest_x, dest_y):
            return
        self.entity.x = dest_x
        self.entity.y = dest_y


class BumpAction(ActionWithDirection):
    """走向一格：有敌人则攻击，否则移动。"""

    def perform(self, engine: "Engine") -> None:
        target = self.target_actor()
        if target is not None and target.is_alive:
            return MeleeAction(self.entity, self.dx, self.dy).perform(engine)
        return MovementAction(self.entity, self.dx, self.dy).perform(engine)


class PickupAction(Action):
    def __init__(self, entity: "Actor") -> None:
        self.entity = entity

    def perform(self, engine: "Engine") -> None:
        strings = engine.content.strings
        item = engine.gamemap.get_item_at(self.entity.x, self.entity.y)
        if item is None:
            raise exceptions.Impossible(strings["no_item_here"])
        try:
            self.entity.inventory.add(item)
        except InventoryFull:
            raise exceptions.Impossible(strings["inventory_full"].format(item=item.name))
        engine.gamemap.entities.discard(item)
        # 注意：不清空 item.gamemap——行囊中的物品组件仍需经它回溯到 engine
        engine.effects.spawn_pickup(self.entity.x, self.entity.y)
        engine.message_log.add_message(strings["pickup"].format(item=item.name), "loot")


class ItemAction(Action):
    def __init__(self, entity: "Actor", item: "Item") -> None:
        self.entity = entity
        self.item = item

    def perform(self, engine: "Engine") -> None:
        if self.item.consumable is None:
            return
        self.item.consumable.activate(self)


class TakeStairsAction(Action):
    """山径：站在下行山径（金）上按 > 下行，站在上行山径（青）上按 < 上行。"""

    def __init__(self, entity: "Actor", direction: str = "down") -> None:
        self.entity = entity
        self.direction = direction

    def perform(self, engine: "Engine") -> None:
        strings = engine.content.strings
        content = engine.content
        here = (self.entity.x, self.entity.y)
        if self.direction == "down":
            if here != engine.gamemap.downstairs_xy:
                raise exceptions.Impossible(strings["not_on_stairs"])
            engine.next_floor()
            floor = engine.gamemap.floor_number
            engine.message_log.add_message(
                strings["descend"].format(
                    region=content.region_name_for_floor(floor), mountain=content.mountain_for_floor(floor)
                ),
                "descend",
            )
        else:
            if here != engine.gamemap.upstairs_xy:
                raise exceptions.Impossible(strings["not_on_up_stairs"])
            engine.previous_floor()
            floor = engine.gamemap.floor_number
            engine.message_log.add_message(
                strings["ascend"].format(
                    region=content.region_name_for_floor(floor), mountain=content.mountain_for_floor(floor)
                ),
                "descend",
            )
