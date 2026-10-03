"""引擎：持有玩家、地图、消息日志与特效；驱动回合推进与楼层切换。

回合状态机：玩家动作成功 → 玩家侧状态结算（buff 递减 / 蛊毒 DOT / 契约兽
时限）→ 敌对与友方单位依次行动（行动前结算 DOT 与眩晕）→ 刷新视野。
"""

from __future__ import annotations

import random
from typing import Optional, Tuple

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
        # 两级地图模型：大世界常驻 + 秘境按 (realm_id, depth) 缓存
        self.realms: dict = {}  # realm_id -> {depth: GameMap}
        self.current_realm: Optional[str] = None
        self.realm_cleared: set = set()  # 已封印（通关）的秘境 id
        self.world_return_xy: Tuple[int, int] = (0, 0)  # 出秘境回世界的落点（入口坐标）
        self.active_page = 0  # 技能页：0 主职业 / 1 副职业（Tab 切换）
        # 大世界旅行：Shift+方向 连续行走；None = 未在旅行
        self.traveling: Optional[Tuple[int, int]] = None
        self.visited_regions: set = set()  # 已踏入过的区域 id（首入叙事）
        self.known_gates: set = set()  # 曾进入过视野的秘境之门坐标（山海图卷标记）

        # 玩家实体在世界生成后创建一次，此后跨地图复用（保留状态）
        self.player = None  # type: ignore[assignment]
        self.world: GameMap = worldgen.generate_world(self, self.rng)
        self.gamemap: GameMap = self.world
        self.player = content.build_player(self.world, *self.world.spawn_xy, class_ids)
        self.update_fov()
        self.message_log.add_message(content.strings["welcome"], "system")

    @classmethod
    def _restore(cls, engine: "Engine", content, settings, data: dict) -> None:
        """从存档重建引擎状态（save_manager.load_engine 调用）。"""
        import save_manager

        engine.content = content
        engine.settings = settings
        engine.message_log = MessageLog(
            x=settings.content_x,
            width=settings.content_w,
            height=settings.log_height,
            theme_messages=content.theme["messages"],
        )
        engine.effects = Effects(content.theme["effects"])
        engine.rng = random.Random()
        engine.game_over = False
        engine.realms = {}
        engine.current_realm = None
        engine.realm_cleared = set(data.get("realm_cleared", []))
        engine.world_return_xy = tuple(data.get("world_return_xy", (0, 0)))
        engine.active_page = data.get("active_page", 0)
        engine.traveling = None
        engine.visited_regions = set(data.get("visited_regions", []))
        engine.known_gates = {tuple(g) for g in data.get("known_gates", [])}

        engine.world = save_manager._restore_map(engine, data["world"])
        engine.gamemap = engine.world
        engine.player = save_manager._restore_player(engine, data["player"])
        for rid, floors in data.get("realms", {}).items():
            engine.realms[rid] = {}
            for depth_str, map_data in floors.items():
                engine.realms[rid][int(depth_str)] = save_manager._restore_map(engine, map_data)

        current = data.get("current", {})
        if current.get("map_type") == "realm" and current.get("realm_id"):
            rid = current["realm_id"]
            floor = engine.realms.get(rid, {}).get(int(current.get("realm_depth", 1)))
            if floor is not None:
                engine.gamemap = floor
                engine.current_realm = rid
        # 玩家实体归属转移到当前地图（build_player 时挂在世界）
        px, py = engine.player.x, engine.player.y
        engine.player.place(engine.gamemap, px, py)

        for m in data.get("messages", []):
            from message_log import Message

            msg = Message(m["text"], m.get("kind", "info"))
            msg.count = m.get("count", 1)
            engine.message_log.messages.append(msg)
        if engine.current_realm is not None:
            # 读档回到秘境：补一条回程指引（存档里的旧消息没有）
            engine.message_log.add_message(content.strings["realm_enter_hint"], "info")
        engine.update_fov()

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
        if self.gamemap.map_type == "world":
            self._check_region_enter()
            self._check_known_gates()

    def _check_known_gates(self) -> None:
        """视野内的秘境之门记入山海图卷（永久标记，M 键查看）。"""
        gamemap = self.gamemap
        for entity in gamemap.entities:
            if "realm_gate" in entity.tags and gamemap.visible[entity.x, entity.y]:
                self.known_gates.add((entity.x, entity.y))

    def _check_region_enter(self) -> None:
        """首次踏入新区域：游历叙事（世界专属）。"""
        gamemap = self.gamemap
        if gamemap.region_ids is None:
            return
        region = self.content.regions[int(gamemap.region_ids[self.player.x, self.player.y])]
        if region["id"] in self.visited_regions:
            return
        self.visited_regions.add(region["id"])
        self.message_log.add_message(
            self.content.strings["region_first_enter"].format(
                intro=self.content._(region["intro"]), region=self.content._(region["name"])
            ),
            "system",
        )
        self.autosave()  # 探索里程碑存档（大世界仅秘境事件存档的补充）

    # ---- 大世界旅行 ----

    def travel_step(self) -> None:
        """旅行连走一步：撞阻/发现敌踪·物品·秘境之门/踏入新界 即停。"""
        from actions import BumpAction

        if self.traveling is None or not self.player.is_alive:
            self.traveling = None
            return
        dx, dy = self.traveling
        strings = self.content.strings
        x0, y0 = self.player.x, self.player.y
        hp0 = self.player.fighter.hp

        def visible_hostiles() -> int:
            """视野内且贴近（≤8 格）的敌对异兽——旅行只在真正有威胁时停下。"""
            from math import hypot

            return sum(
                1
                for actor in self.gamemap.actors
                if actor.team == "wild"
                and self.gamemap.visible[actor.x, actor.y]
                and hypot(actor.x - x0, actor.y - y0) <= 8.0
            )

        enemies_before = visible_hostiles()
        self.handle_action(BumpAction(self.player, dx, dy))
        if self.game_over or not self.player.is_alive:
            self.traveling = None
            return
        moved = (self.player.x, self.player.y) != (x0, y0)
        if not moved:
            self.message_log.add_message(strings["travel_stop_blocked"], "info")
            self.traveling = None
            return
        if self.player.fighter.hp < hp0:
            self.traveling = None  # 途中遇袭
            return
        if visible_hostiles() > enemies_before:
            self.message_log.add_message(strings["travel_stop_enemy"], "warn")
            self.traveling = None
            return
        item = self.gamemap.get_item_at(self.player.x, self.player.y)
        if item is not None:
            self.message_log.add_message(strings["travel_stop_item"].format(item=item.name), "info")
            self.traveling = None
            return
        if self.gamemap.get_realm_gate_at(self.player.x, self.player.y) is not None:
            self.message_log.add_message(strings["travel_stop_gate"], "info")
            self.traveling = None

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
        """参悟/修习技能（不消耗回合）。

        初学：前置检查 + 消耗技能点 cost（1-2 点）；升级：每级 1 点，
        直至 SKILL_MAX_LEVEL 满级。每升一重境界获得 1 技能点。
        """
        import skills as skills_module

        player = self.player
        strings = self.content.strings
        skill = self.content.skills[skill_id]
        level = int(player.skill_levels.get(skill_id, 0))
        if level >= skills_module.SKILL_MAX_LEVEL:
            raise exceptions.Impossible(strings["learn_max"])
        if level == 0:
            missing = [
                self.content._(self.content.skills[r]["name"])
                for r in skill.get("requires", [])
                if r not in player.learned_skills
            ]
            if missing:
                raise exceptions.Impossible(
                    strings["learn_locked"].format(missing="、".join(missing))
                )
            cost = int(skill.get("cost", 1))  # 初学费用（大招 2 点）
        else:
            cost = 1  # 升级每级 1 点
        if player.skill_points < cost:
            raise exceptions.Impossible(strings["learn_no_points"])
        player.skill_points -= cost
        player.skill_levels[skill_id] = level + 1
        name = self.content._(skill["name"])
        if level == 0:
            self.message_log.add_message(strings["learn_ok"].format(skill=name), "levelup")
        else:
            self.message_log.add_message(
                strings["learn_upgrade"].format(skill=name, level=level + 1), "levelup"
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

    def roll_material_drop(self, source) -> None:
        """异兽死亡按 tags 掉炼制材料；BOSS 额外必掉魔核。"""
        if source is None or getattr(source, "summon_ttl", None) is not None:
            return
        drops: list = []
        if "boss" in getattr(source, "tags", []):
            drops.append("mat_demon_core")
        material_id = self.content.roll_material_drop(getattr(source, "tags", []), self.rng)
        if material_id is not None:
            drops.append(material_id)
        for mid in drops:
            item = self.content.build_item(mid, self.gamemap, source.x, source.y)
            self.message_log.add_message(
                self.content.strings["material_drop"].format(
                    monster=source.name, item=item.name
                ),
                "loot",
            )

    # ---- 秘境流转 ----

    def enter_realm(self, realm_id: str, return_xy: Tuple[int, int]) -> None:
        """踏入秘境第 1 层；缓存存在则复用（保留探索过的层）。"""
        self.world_return_xy = return_xy
        floors = self.realms.setdefault(realm_id, {})
        if 1 in floors:
            self.gamemap = floors[1]
            self.player.place(self.gamemap, *self.gamemap.upstairs_xy)
        else:
            self.gamemap = self._generate_realm_floor(realm_id, 1)
        self.current_realm = realm_id
        self.effects.clear()
        self.update_fov()
        self.autosave()

    def exit_realm(self) -> None:
        """从秘境回世界，落在入口坐标；按配额补撒世界资源点（灵草/矿脉复苏）。"""
        if self.current_realm is None:
            return
        self.realms.setdefault(self.current_realm, {})[self.gamemap.realm_depth] = self.gamemap
        self.gamemap = self.world
        self.player.place(self.world, *self.world_return_xy)
        self.current_realm = None
        self.effects.clear()
        self._replenish_world_nodes()
        self.update_fov()
        self.autosave()

    def _replenish_world_nodes(self) -> None:
        """补撒世界资源点至 crafting.nodes 的 world_target 配额。"""
        from worldgen import scatter_resource_nodes

        counts: dict = {}
        for node_id, node in self.content.craft_nodes.items():
            target = int(node.get("world_target", 0))
            existing = sum(
                1
                for e in self.world.entities
                if "resource_node" in e.tags and node_id in e.tags
            )
            if existing < target:
                counts[node_id] = target - existing
        if counts:
            scatter_resource_nodes(self.world, self.content, self.rng, counts)

    def autosave(self) -> None:
        """进出秘境与换层时自动存档（死亡即删档的 roguelike 铁律下安全）。"""
        import save_manager

        if self.player is not None and self.player.is_alive and not self.game_over:
            save_manager.save_game(self)

    def _generate_realm_floor(self, realm_id: str, depth: int) -> GameMap:
        realm_def = self.content.realm_def(realm_id)
        difficulty = self.content.realm_difficulty(realm_id, depth)
        is_boss_floor = depth >= int(realm_def["depth"])
        return procgen.generate_dungeon(
            self,
            difficulty,
            self.rng,
            realm_id=realm_id,
            realm_depth=depth,
            boss_id=realm_def["boss"] if is_boss_floor else None,
        )

    def next_floor(self) -> None:
        """秘境内沿山径下行一层（难度递增，下行真气全复）。"""
        realm_id = self.gamemap.realm_id
        depth = self.gamemap.realm_depth
        if realm_id is None or depth >= int(self.content.realm_def(realm_id)["depth"]):
            return  # 已是最深层（BOSS 层无下行山径，防御性兜底）
        floors = self.realms.setdefault(realm_id, {})
        floors[depth] = self.gamemap
        if depth + 1 in floors:
            self.gamemap = floors[depth + 1]
            self.player.place(self.gamemap, *self.gamemap.upstairs_xy)
        else:
            self.gamemap = self._generate_realm_floor(realm_id, depth + 1)
        self.effects.clear()
        if self.player.is_alive:
            # 层层深入，气脉与山川共鸣，真气全复
            self.player.fighter.mp = self.player.fighter.max_mp
        self.update_fov()
        self.autosave()

    def previous_floor(self) -> None:
        """秘境内回上层；已在第 1 层则回世界。"""
        if self.gamemap.realm_depth <= 1:
            self.exit_realm()
            return
        realm_id = self.gamemap.realm_id
        above = self.realms.get(realm_id, {}).get(self.gamemap.realm_depth - 1)
        if above is None:
            raise exceptions.Impossible(self.content.strings["no_floor_above"])
        self.realms.setdefault(realm_id, {})[self.gamemap.realm_depth] = self.gamemap
        self.gamemap = above
        self.player.place(self.gamemap, *self.gamemap.downstairs_xy)
        self.effects.clear()
        self.update_fov()

    def on_boss_slain(self, boss) -> None:
        """BOSS 陨落：保底掉宝 + 封印秘境入口。"""
        if self.current_realm is None:
            return
        strings = self.content.strings
        realm_id = self.current_realm
        self.realm_cleared.add(realm_id)
        # 保底掉宝：高于本层难度一档的装备
        difficulty = self.content.realm_difficulty(realm_id, self.gamemap.realm_depth)
        item_id = self.content.random_equipment_id(difficulty + 4, self.rng)
        if item_id is not None:
            item = self.content.build_item(item_id, self.gamemap, boss.x, boss.y)
            self.message_log.add_message(
                strings["realm_boss_drop"].format(boss=boss.name, item=item.name), "loot"
            )
        self.message_log.add_message(
            strings["realm_boss_slain"].format(boss=boss.name), "levelup"
        )
        # 世界入口封印：换图块/颜色，标记不可再入
        for entity in self.world.entities:
            if realm_id in entity.tags and "realm_gate" in entity.tags:
                entity.art = "realm_gate_sealed"
                entity.tags.append("sealed")
                entity.color = (110, 104, 124)
                entity.name = entity.name + strings["realm_sealed_suffix"]
        self.effects.spawn_aoe_ring(boss.x, boss.y, 3.0)

    def apply_layout(self) -> None:
        """显示设置变更后应用新几何：仅更新日志参数。

        地图尺寸与视口已解耦（摄像机适配），进度完整保留。
        """
        log = self.message_log
        log.x = self.settings.content_x
        log.width = self.settings.content_w
        log.height = self.settings.log_height
        log.scroll_offset = 0
