"""引擎：持有玩家、地图、消息日志与特效；驱动回合推进与楼层切换。

回合状态机：玩家动作成功 → 玩家侧状态结算（buff 递减 / 蛊毒 DOT / 契约兽
时限）→ 敌对与友方单位依次行动（行动前结算 DOT 与眩晕）→ 刷新视野。
"""

from __future__ import annotations

import random

import exceptions
import procgen
import skills as skills_module
import worldgen
from content_loader import DEFAULT_CLASS_IDS
from effects import Effects
from game_map import GameMap
from message_log import MessageLog

MONSTER_DROP_CHANCE = 0.22  # 异兽死亡掉落装备概率（机制常量；掉什么由数据决定）


class Engine:
    def __init__(self, content, settings, class_ids: tuple = DEFAULT_CLASS_IDS) -> None:
        self.content = content
        self.settings = settings
        self.message_log = MessageLog(
            x=settings.content_x,
            width=settings.content_w,
            height=settings.log_height,
            theme_messages=content.theme["messages"],
        )
        self.effects = Effects(content.theme["effects"])
        self.rng = random.Random()
        self.game_over = False
        self.floors: dict = {}  # 楼层历史：floor_number -> GameMap，支持上行返回
        self.active_page = 0  # 技能页：0 主职业 / 1 副职业（Tab 切换）

        # 玩家实体在世界生成后创建一次，此后跨地图复用（保留状态）
        self.player = None  # type: ignore[assignment]
        self.world: GameMap = worldgen.generate_world(self, self.rng)
        self.gamemap: GameMap = self.world
        self.player = content.build_player(self.world, *self.world.spawn_xy, class_ids)
        self.update_fov()
        self.message_log.add_message(content.strings["welcome"], "system")

    # ---- 回合推进 ----

    def handle_action(self, action) -> None:
        """执行玩家动作：成功则结算状态、敌人行动并刷新视野；失败则提示原因。"""
        self.message_log.scroll_offset = 0  # 采取行动即回到日志底部
        try:
            action.perform(self)
        except exceptions.Impossible as exc:
            self.message_log.add_message(str(exc), "warn")
            return  # 非法动作不消耗回合
        # NeedTarget 等控制流异常向上冒泡给主循环切输入模式
        if not self.game_over:
            self.end_player_turn()
        if not self.game_over:
            self.handle_enemy_turns()
        self.update_fov()

    def end_player_turn(self) -> None:
        """玩家回合结束：蛊毒 DOT、buff 递减、契约兽时限。"""
        player = self.player
        fighter = player.fighter
        strings = self.content.strings
        if fighter is None:
            return
        if fighter.poisoned:
            damage = fighter.tick_poison()
            if damage:
                fighter.hp -= damage
                self.effects.spawn_poison_tick(player.x, player.y, damage)
                self.message_log.add_message(
                    strings["poison_tick"].format(name=player.name, damage=damage), "warn"
                )
                if not player.is_alive:
                    return
            if not fighter.poisoned:
                self.message_log.add_message(
                    strings["poison_fade"].format(name=player.name), "info"
                )
        if fighter.tick_buffs():
            self.message_log.add_message(strings["buff_fade"], "info")
        # 契约兽时限递减
        for actor in list(self.gamemap.actors):
            if actor.summon_ttl is not None and actor is not player:
                actor.summon_ttl -= 1
                if actor.summon_ttl <= 0:
                    self.message_log.add_message(
                        strings["summon_fade"].format(name=actor.name), "summon"
                    )
                    self.effects.spawn_summon(actor.x, actor.y)
                    self.gamemap.entities.discard(actor)

    def handle_enemy_turns(self) -> None:
        for actor in self.gamemap.actors:
            if actor is self.player or not actor.is_alive or actor.ai is None:
                continue
            if self.game_over:
                return
            try:
                self._settle_actor_turn(actor)
            except exceptions.Impossible:
                pass  # 敌人的非法行动静默跳过

    def _settle_actor_turn(self, actor) -> None:
        """单个非玩家单位行动前结算 DOT 与眩晕，再执行 AI。"""
        strings = self.content.strings
        fighter = actor.fighter
        if fighter.poisoned:
            damage = fighter.tick_poison()
            if damage:
                fighter.hp -= damage
                self.effects.spawn_poison_tick(actor.x, actor.y, damage)
                self.message_log.add_message(
                    strings["poison_tick"].format(name=actor.name, damage=damage), "warn"
                )
                if not actor.is_alive:
                    return
            if not fighter.poisoned:
                self.message_log.add_message(
                    strings["poison_fade"].format(name=actor.name), "info"
                )
        if fighter.stun_turns > 0:
            fighter.stun_turns -= 1
            self.effects.spawn_stun(actor.x, actor.y)
            self.message_log.add_message(strings["stunned_tick"].format(name=actor.name), "info")
            return  # 眩晕：跳过本回合
        actor.ai.perform()

    def update_fov(self) -> None:
        self.gamemap.update_fov(self.player.x, self.player.y)

    # ---- 技能 ----

    def execute_skill(self, slot: int, target=None, page: int | None = None) -> None:
        """按当前页槽位施展技能；需目标时抛 NeedTarget 由输入层接管。"""
        player = self.player
        strings = self.content.strings
        if not player.is_alive:
            raise exceptions.Impossible(strings["hud_hp_dead"])
        page_index = self.active_page if page is None else page
        class_id = player.class_ids[page_index]
        skill = self.content.skill_for_slot(class_id, slot)
        if skill is None:
            return
        if skill["id"] not in player.learned_skills:
            raise exceptions.Impossible(strings["not_learned"])
        skills_module.cast(self, player, skill, target)

    def learn_skill(self, skill_id: str) -> None:
        """参悟技能（不消耗回合）：前置、点数检查。"""
        player = self.player
        strings = self.content.strings
        skill = self.content.skills[skill_id]
        if skill_id in player.learned_skills:
            raise exceptions.Impossible(strings["already_learned"])
        missing = [
            self.content._(self.content.skills[r]["name"])
            for r in skill.get("requires", [])
            if r not in player.learned_skills
        ]
        if missing:
            raise exceptions.Impossible(
                strings["learn_locked"].format(missing="、".join(missing))
            )
        cost = int(skill.get("cost", 1))
        if player.skill_points < cost:
            raise exceptions.Impossible(strings["learn_no_points"])
        player.skill_points -= cost
        player.learned_skills.add(skill_id)
        self.message_log.add_message(
            strings["learn_ok"].format(skill=self.content._(skill["name"])), "levelup"
        )

    # ---- 掉落 ----

    def trigger_kill_heal(self, player) -> None:
        """装备「弑回血」词条：击杀敌对单位时回血（普攻与技能共用）。"""
        equipment = getattr(player, "equipment", None)
        if equipment is None:
            return
        amount = equipment.affix("kill_heal")
        if amount > 0 and player.is_alive:
            healed = player.fighter.heal(amount)
            if healed:
                self.effects.spawn_heal(player.x, player.y, healed)

    def roll_drop(self, x: int, y: int, source=None) -> None:
        """异兽死亡掉落：22% 概率按层抽取装备（tier 门槛见 content_loader）。"""
        if source is not None and getattr(source, "summon_ttl", None) is not None:
            return  # 契约兽消散不掉落
        if self.rng.random() >= MONSTER_DROP_CHANCE:
            return
        item_id = self.content.random_equipment_id(self.gamemap.floor_number, self.rng)
        if item_id is None:
            return
        item = self.content.build_item(item_id, self.gamemap, x, y)
        monster_name = source.name if source is not None else item.name
        self.message_log.add_message(
            self.content.strings["monster_drop"].format(
                monster=monster_name, item=item.name
            ),
            "loot",
        )

    # ---- 楼层 ----

    def next_floor(self) -> None:
        self.floors[self.gamemap.floor_number] = self.gamemap
        next_number = self.gamemap.floor_number + 1
        if next_number in self.floors:
            self.gamemap = self.floors[next_number]
            self.player.place(self.gamemap, *self.gamemap.upstairs_xy)
        else:
            self.gamemap = procgen.generate_dungeon(self, next_number, self.rng)
        self.effects.clear()
        if self.player.is_alive:
            # 抵达新山：气脉与山川共鸣，真气全复
            self.player.fighter.mp = self.player.fighter.max_mp
        self.update_fov()

    def previous_floor(self) -> None:
        if self.gamemap.floor_number <= 1:
            return
        above = self.floors.get(self.gamemap.floor_number - 1)
        if above is None:
            # 楼层历史已清空（如改过显示设置），来路不存在——给提示而非崩溃
            raise exceptions.Impossible(self.content.strings["no_floor_above"])
        self.floors[self.gamemap.floor_number] = self.gamemap
        self.gamemap = above
        self.player.place(self.gamemap, *self.gamemap.downstairs_xy)
        self.effects.clear()
        self.update_fov()

    def apply_layout(self) -> None:
        """显示设置变更后应用新几何：仅更新日志参数。

        地图尺寸与视口已解耦（摄像机适配），进度完整保留。
        """
        log = self.message_log
        log.x = self.settings.content_x
        log.width = self.settings.content_w
        log.height = self.settings.log_height
        log.scroll_offset = 0
