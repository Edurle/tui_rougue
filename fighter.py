"""战斗组件：气血、攻防、经验结算与死亡处理。"""

from __future__ import annotations

import random

from base_component import BaseComponent


class Fighter(BaseComponent):
    def __init__(self, hp: int, power: int, defense: int, xp_reward: int = 0) -> None:
        self.max_hp = hp
        self._hp = hp
        self._dead = False
        self.power = power
        self.defense = defense
        self.xp_reward = xp_reward

    @property
    def hp(self) -> int:
        return self._hp

    @hp.setter
    def hp(self, value: int) -> None:
        self._hp = max(0, min(value, self.max_hp))
        if self._hp == 0 and not self._dead:
            self._dead = True
            self.die()

    def heal(self, amount: int) -> int:
        actual = min(amount, self.max_hp - self._hp)
        self._hp += actual
        return actual

    def is_player(self) -> bool:
        return self.parent is self.engine.player

    def attack(self, target: "Fighter") -> None:
        """伤害 = 攻 - 防 + [-1, 2] 浮动，下限 0。五行生克将来在此处接入。"""
        damage = self.power - target.defense + random.randint(-1, 2)
        strings = self.engine.content.strings
        log = self.engine.message_log
        if damage > 0:
            log.add_message(
                strings["attack_hits"].format(
                    attacker=self.parent.name, target=target.parent.name, damage=damage
                ),
                "combat",
            )
            prev_ratio = target.hp / target.max_hp
            target.hp -= damage
            self.engine.effects.spawn_damage(
                target.parent.x, target.parent.y, damage, is_player_victim=target.is_player()
            )
            if target.is_player() and 0 < target.hp / target.max_hp < 0.3 <= prev_ratio:
                log.add_message(strings["player_hurt_warn"], "warn")
        else:
            log.add_message(
                strings["attack_blocked"].format(
                    attacker=self.parent.name, target=target.parent.name
                ),
                "combat_blocked",
            )

    def die(self) -> None:
        strings = self.engine.content.strings
        theme = self.engine.content.theme
        log = self.engine.message_log
        if self.is_player():
            log.add_message(strings["player_dies"], "death")
            self.parent.char = "%"
            self.parent.color = tuple(theme["player_corpse_color"])
            self.parent.art = "corpse"
            self.parent.fighter = None
            self.engine.game_over = True
            return
        log.add_message(strings["monster_dies"].format(name=self.parent.name), "kill")
        if self.engine.player.level and self.engine.player.is_alive:
            self.engine.player.level.add_xp(self.xp_reward)
        self.engine.effects.spawn_pickup(self.parent.x, self.parent.y)
        self.parent.char = "%"
        self.parent.color = tuple(theme["corpse_color"])
        self.parent.name = strings["corpse_name"].format(name=self.parent.name)
        self.parent.blocks_movement = False
        self.parent.ai = None
        self.parent.art = "corpse"
        self.parent.fighter = None
