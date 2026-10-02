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
        attacker_name = self.parent.name
        target_name = target.parent.name
        strings = self.engine.content.strings
        log = self.engine.message_log
        if damage > 0:
            log.add_message(
                strings["attack_hits"].format(attacker=attacker_name, target=target_name, damage=damage),
                (230, 230, 230),
            )
            prev_ratio = target.hp / target.max_hp
            target.hp -= damage
            if target.is_player() and 0 < target.hp / target.max_hp < 0.3 <= prev_ratio:
                log.add_message(strings["player_hurt_warn"], (240, 120, 90))
        else:
            log.add_message(
                strings["attack_blocked"].format(attacker=attacker_name, target=target_name),
                (150, 150, 160),
            )

    def die(self) -> None:
        strings = self.engine.content.strings
        log = self.engine.message_log
        if self.is_player():
            log.add_message(strings["player_dies"], (240, 90, 90))
            self.parent.char = "%"
            self.parent.color = (150, 40, 40)
            self.parent.fighter = None
            self.engine.game_over = True
            return
        log.add_message(strings["monster_dies"].format(name=self.parent.name), (200, 170, 120))
        if self.engine.player.level and self.engine.player.is_alive:
            self.engine.player.level.add_xp(self.xp_reward)
        self.parent.char = "%"
        self.parent.color = (110, 45, 35)
        self.parent.name = strings["corpse_name"].format(name=self.parent.name)
        self.parent.blocks_movement = False
        self.parent.ai = None
        self.parent.fighter = None
