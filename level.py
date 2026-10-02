"""修为（等级）组件：经验获取与自动升级。

升级加成数值由 data/content/player.json 驱动（max_hp/max_mp/power/defense/
skill_points），作用于 fighter 的基础值（base_*），装备与 buff 由聚合层叠加。
"""

from __future__ import annotations

from base_component import BaseComponent


class Level(BaseComponent):
    def __init__(
        self,
        current_level: int = 1,
        current_xp: int = 0,
        base_xp: int = 0,
        step_xp: int = 100,
        bonuses: dict | None = None,
    ) -> None:
        self.current_level = current_level
        self.current_xp = current_xp
        self.base_xp = base_xp
        self.step_xp = step_xp
        self.bonuses = bonuses or {}

    @property
    def experience_to_next_level(self) -> int:
        return self.base_xp + self.current_level * self.step_xp

    @property
    def requires_level_up(self) -> bool:
        return self.current_xp > self.experience_to_next_level

    def add_xp(self, xp: int) -> None:
        if xp == 0 or self.parent is not self.engine.player:
            # 修为成长只对玩家生效（异兽击杀只得经验不升级）
            return
        self.current_xp += xp
        strings = self.engine.content.strings
        self.engine.message_log.add_message(strings["gain_xp"].format(xp=xp), "xp")
        while self.requires_level_up:
            self.current_level += 1
            self._apply_level_up()

    def _apply_level_up(self) -> None:
        parent = self.parent
        fighter = parent.fighter
        strings = self.engine.content.strings
        gained_hp = self.bonuses.get("max_hp", 0)
        fighter.base_max_hp += gained_hp
        fighter.heal(gained_hp)
        gained_mp = self.bonuses.get("max_mp", 0)
        fighter.base_max_mp += gained_mp
        fighter.restore_mp(gained_mp)
        fighter.base_power += self.bonuses.get("power", 0)
        fighter.base_defense += self.bonuses.get("defense", 0)
        parent.skill_points += self.bonuses.get("skill_points", 0)
        self.engine.message_log.add_message(
            strings["level_up"].format(level=self.current_level), "levelup"
        )
        self.engine.effects.spawn_level_up(parent.x, parent.y)
