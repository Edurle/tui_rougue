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
            return self._gather(engine)
        try:
            self.entity.inventory.add(item)
        except InventoryFull:
            raise exceptions.Impossible(strings["inventory_full"].format(item=item.name))
        engine.gamemap.entities.discard(item)
        # 注意：不清空 item.gamemap——行囊中的物品组件仍需经它回溯到 engine
        if item.is_material and item.stack > 1:
            engine.message_log.add_message(
                strings["pickup_stack"].format(item=item.name, count=item.stack), "loot"
            )
        else:
            engine.message_log.add_message(strings["pickup"].format(item=item.name), "loot")
        engine.effects.spawn_pickup(self.entity.x, self.entity.y)

    def _gather(self, engine: "Engine") -> None:
        """采集脚下的资源点（灵草丛/矿脉），产出材料直接入囊。"""
        strings = engine.content.strings
        node = engine.gamemap.get_resource_node_at(self.entity.x, self.entity.y)
        if node is None:
            raise exceptions.Impossible(strings["no_item_here"])
        node_kind = next(t for t in node.tags if t != "resource_node")
        yields = engine.content.craft_nodes[node_kind]["yields"]
        count = engine.rng.randint(int(yields["min"]), int(yields["max"]))
        material = engine.content.build_item(yields["id"], engine.gamemap, node.x, node.y)
        material.stack = count
        try:
            self.entity.inventory.add(material)
        except InventoryFull:
            engine.gamemap.entities.discard(material)
            raise exceptions.Impossible(strings["inventory_full"].format(item=material.name))
        engine.gamemap.entities.discard(material)
        engine.gamemap.entities.discard(node)
        engine.effects.spawn_pickup(self.entity.x, self.entity.y)
        engine.message_log.add_message(
            strings["gather_ok"].format(item=material.name, count=count), "loot"
        )


class ItemAction(Action):
    def __init__(self, entity: "Actor", item: "Item") -> None:
        self.entity = entity
        self.item = item

    def perform(self, engine: "Engine") -> None:
        if self.item.consumable is None:
            return
        self.item.consumable.activate(self)


class CastSkillAction(Action):
    """施展当前页第 slot 槽技能（1-8 → slot 0-7）。需目标时抛 NeedTarget。"""

    def __init__(self, entity: "Actor", slot: int, target=None) -> None:
        self.entity = entity
        self.slot = slot
        self.target = target

    def perform(self, engine: "Engine") -> None:
        engine.execute_skill(self.slot, target=self.target)


class EquipAction(Action):
    """装备行囊中的一件（被顶替的旧件自动回行囊）。"""

    def __init__(self, entity: "Actor", item: "Item") -> None:
        self.entity = entity
        self.item = item

    def perform(self, engine: "Engine") -> None:
        strings = engine.content.strings
        equipment = self.entity.equipment
        if equipment is None or self.item.equipment is None:
            raise exceptions.Impossible(strings["no_item_here"])
        replaced = equipment.equip(self.item)
        if replaced is not None:
            self.entity.inventory.add(replaced)
        self.entity.fighter.clamp_vitals()
        engine.message_log.add_message(
            strings["equip_on"].format(item=self.item.name), "loot"
        )


class UnequipAction(Action):
    """卸下指定装备槽，物品回行囊。"""

    def __init__(self, entity: "Actor", slot: str) -> None:
        self.entity = entity
        self.slot = slot

    def perform(self, engine: "Engine") -> None:
        strings = engine.content.strings
        equipment = self.entity.equipment
        item = equipment.unequip_slot(self.slot) if equipment is not None else None
        if item is None:
            raise exceptions.Impossible(strings["no_item_here"])
        try:
            self.entity.inventory.add(item)
        except InventoryFull:
            equipment.equip(item)  # 放不回去，原样穿回
            raise exceptions.Impossible(strings["inventory_full"].format(item=item.name))
        self.entity.fighter.clamp_vitals()
        engine.message_log.add_message(strings["equip_off"].format(item=item.name), "loot")


class TakeStairsAction(Action):
    """山径交互：大世界上 = 踏入秘境之门（>）；秘境内 = 层间移动（> 深入 / < 回返）。

    秘境第 1 层的上行山径（<）即出口，回世界入口坐标。
    """

    def __init__(self, entity: "Actor", direction: str = "down") -> None:
        self.entity = entity
        self.direction = direction

    def perform(self, engine: "Engine") -> None:
        strings = engine.content.strings
        gamemap = engine.gamemap
        here = (self.entity.x, self.entity.y)

        if gamemap.map_type == "world":
            if self.direction != "down":
                raise exceptions.Impossible(strings["not_on_up_stairs"])
            gate = gamemap.get_realm_gate_at(*here)
            if gate is None:
                raise exceptions.Impossible(strings["not_on_stairs"])
            if "sealed" in gate.tags:
                raise exceptions.Impossible(strings["realm_sealed"])
            realm_id = next(t for t in gate.tags if t not in ("realm_gate", "sealed"))
            engine.known_gates.add(here)  # 踏上门槛即记入山海图卷
            engine.enter_realm(realm_id, here)
            realm_def = engine.content.realm_def(realm_id)
            engine.message_log.add_message(
                strings["realm_enter"].format(
                    realm=engine.content.realm_name(realm_id),
                    intro=engine.content._(realm_def["intro"]),
                ),
                "descend",
            )
            return

        # ---- 秘境内 ----
        if self.direction == "down":
            if here != gamemap.downstairs_xy:
                raise exceptions.Impossible(strings["not_on_stairs"])
            engine.next_floor()
            engine.message_log.add_message(strings["realm_descend"], "descend")
        else:
            if here != gamemap.upstairs_xy:
                raise exceptions.Impossible(strings["not_on_up_stairs"])
            was_first_floor = gamemap.realm_depth <= 1
            engine.previous_floor()
            if was_first_floor:
                engine.message_log.add_message(strings["realm_exit"], "descend")
            else:
                engine.message_log.add_message(strings["realm_ascend"], "descend")
