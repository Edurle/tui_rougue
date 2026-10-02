"""战斗组件：气血/真气、攻防聚合（基础+buff+装备词条）、状态机与死亡处理。

聚合规则：
- max_hp / max_mp / power / defense = base_* + 装备 bonuses + buff（power/defense）
- 外部直写（测试与旧代码）视为重设基础值：hp setter 语义保持 clamp+死亡判定
- buff（攻/防）、蛊毒 DOT、眩晕 = 回合状态机，由引擎在回合边界调用 tick_*
- 抗性：元素（thunder/fire/poison）按百分比减伤（下限 1 点）；stun 抗性
  （"定力"）缩短眩晕时长。来源 = 怪物自身数据 + 玩家装备词条，上限 80%
"""

from __future__ import annotations

import random

from base_component import BaseComponent

RESIST_KINDS = ("thunder", "fire", "poison", "stun")
RESIST_DAMAGE_KINDS = ("thunder", "fire", "poison")
RESIST_CAP = 80


class Fighter(BaseComponent):
    def __init__(
        self,
        hp: int,
        power: int,
        defense: int,
        xp_reward: int = 0,
        max_mp: int = 0,
        resistances: dict | None = None,
    ) -> None:
        self.base_max_hp = hp
        self._hp = hp
        self._dead = False
        self.base_power = power
        self.base_defense = defense
        self.base_max_mp = max_mp
        self._mp = max_mp
        self.xp_reward = xp_reward
        self.base_resistances: dict[str, int] = dict(resistances or {})
        # 回合状态：buffs[stat] = [amount, turns]；dot = [damage, turns]
        self.buffs: dict[str, list[int]] = {}
        self.dot: list[int] = [0, 0]
        self.stun_turns = 0

    # ---- 装备聚合 ----

    def _gear_bonus(self, key: str) -> int:
        parent = getattr(self, "parent", None)
        equipment = getattr(parent, "equipment", None)
        if equipment is None:
            return 0
        return equipment.bonus(key)

    # ---- 聚合属性 ----

    @property
    def max_hp(self) -> int:
        return self.base_max_hp + self._gear_bonus("max_hp")

    @max_hp.setter
    def max_hp(self, value: int) -> None:
        self.base_max_hp = value

    @property
    def max_mp(self) -> int:
        return self.base_max_mp + self._gear_bonus("max_mp")

    @max_mp.setter
    def max_mp(self, value: int) -> None:
        self.base_max_mp = value

    @property
    def power(self) -> int:
        return self.base_power + self.buff_amount("power") + self._gear_bonus("power")

    @power.setter
    def power(self, value: int) -> None:
        self.base_power = value

    @property
    def defense(self) -> int:
        return self.base_defense + self.buff_amount("defense") + self._gear_bonus("defense")

    @defense.setter
    def defense(self, value: int) -> None:
        self.base_defense = value

    # ---- 当前值 ----

    @property
    def hp(self) -> int:
        return self._hp

    @hp.setter
    def hp(self, value: int) -> None:
        self._hp = max(0, min(value, self.max_hp))
        if self._hp == 0 and not self._dead:
            self._dead = True
            self.die()

    @property
    def mp(self) -> int:
        return self._mp

    @mp.setter
    def mp(self, value: int) -> None:
        self._mp = max(0, min(value, self.max_mp))

    def heal(self, amount: int) -> int:
        actual = min(amount, self.max_hp - self._hp)
        self._hp += actual
        return actual

    def clamp_vitals(self) -> None:
        """装备变动导致上限变化后收敛当前值（卸甲后气血不再超出上限）。"""
        self._hp = min(self._hp, self.max_hp)
        self._mp = min(self._mp, self.max_mp)

    def restore_mp(self, amount: int) -> int:
        actual = min(amount, self.max_mp - self._mp)
        self._mp += actual
        return actual

    # ---- 抗性 ----

    def resistance(self, kind: str) -> int:
        """指定抗性（0-RESIST_CAP）：怪物自身数据 + 玩家装备词条聚合。"""
        value = self.base_resistances.get(kind, 0)
        equipment = getattr(getattr(self, "parent", None), "equipment", None)
        if equipment is not None:
            value += equipment.affix(f"resist_{kind}")
        return min(RESIST_CAP, value)

    def mitigate_incoming(self, damage: int, tags) -> int:
        """按命中的元素抗性折算伤害：取 tags 中最高抗性，下限 1 点。"""
        resist = max(
            (self.resistance(t) for t in tags if t in RESIST_DAMAGE_KINDS), default=0
        )
        if resist <= 0:
            return damage
        return max(1, int(round(damage * (100 - resist) / 100)))

    # ---- 状态机 ----

    def apply_buff(self, stat: str, amount: int, turns: int) -> None:
        """同属性重复施加：数值叠加、时长刷新。"""
        current = self.buffs.get(stat)
        if current is None:
            self.buffs[stat] = [amount, turns]
        else:
            current[0] += amount
            current[1] = turns

    def buff_amount(self, stat: str) -> int:
        entry = self.buffs.get(stat)
        return entry[0] if entry else 0

    def tick_buffs(self) -> bool:
        """回合边界递减；返回是否有 buff 到期（用于提示）。"""
        expired = False
        for stat in list(self.buffs):
            entry = self.buffs[stat]
            entry[1] -= 1
            if entry[1] <= 0:
                del self.buffs[stat]
                expired = True
        return expired

    def apply_poison(self, damage: int, turns: int) -> None:
        """蛊毒施加：后到的毒覆盖先前的；每跳伤害吃目标毒抗（下限 1）。"""
        self.dot = [self.mitigate_incoming(damage, ["poison"]), turns]

    @property
    def poisoned(self) -> bool:
        return self.dot[1] > 0

    def tick_poison(self) -> int:
        """结算本回合毒伤并递减时长；返回实际伤害（0=无毒）。"""
        damage, turns = self.dot
        if turns <= 0 or damage <= 0:
            return 0
        self.dot[1] = turns - 1
        return damage

    def apply_stun(self, turns: int) -> None:
        """施加眩晕：定力（stun 抗性）按比例缩短时长，可为 0（完全抵抗）。"""
        resist = self.resistance("stun")
        turns = int(turns * (100 - resist) / 100)
        if turns <= 0:
            return
        self.stun_turns = max(self.stun_turns, turns)

    # ---- 战斗 ----

    def is_player(self) -> bool:
        return self.parent is self.engine.player

    def attack(self, target: "Fighter") -> None:
        """伤害 = 攻 - 防 + [-1, 2] 浮动，下限 0；附带元素（attack_tags）吃目标抗性。"""
        damage = self.power - target.defense + random.randint(-1, 2)
        element_tags = [t for t in getattr(self.parent, "attack_tags", []) if t in RESIST_DAMAGE_KINDS]
        if element_tags:
            damage = target.mitigate_incoming(damage, element_tags)
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
            # 元素爪击命中玩家且玩家有对应抗性时给一行提示（装备构筑的正反馈）
            if target.is_player() and element_tags:
                resisted = max(target.resistance(t) for t in element_tags)
                if resisted > 0:
                    element_name = strings[f"element_{element_tags[0]}"]
                    log.add_message(
                        strings["attack_element_notice"].format(
                            attacker=self.parent.name, element=element_name
                        ),
                        "combat_blocked",
                    )
            if not target.parent.is_alive:
                self.engine.trigger_kill_heal(self.parent)
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
            import save_manager

            save_manager.delete_save()  # 陨落即删档（roguelike 铁律）
            return
        if getattr(self.parent, "summon_ttl", None) is not None:
            # 契约兽力竭：化光消散，不留尸骸不掉落
            log.add_message(strings["summon_fade"].format(name=self.parent.name), "summon")
            self.engine.effects.spawn_summon(self.parent.x, self.parent.y)
            self.engine.gamemap.entities.discard(self.parent)
            self.parent.fighter = None
            return
        log.add_message(strings["monster_dies"].format(name=self.parent.name), "kill")
        if self.engine.player.level and self.engine.player.is_alive:
            self.engine.player.level.add_xp(self.xp_reward)
        self.engine.effects.spawn_pickup(self.parent.x, self.parent.y)
        self.engine.roll_drop(self.parent.x, self.parent.y, source=self.parent)
        if "boss" in getattr(self.parent, "tags", []):
            self.engine.on_boss_slain(self.parent)
        self.parent.char = "%"
        self.parent.color = tuple(theme["corpse_color"])
        self.parent.name = strings["corpse_name"].format(name=self.parent.name)
        self.parent.blocks_movement = False
        self.parent.ai = None
        self.parent.art = "corpse"
        self.parent.fighter = None
