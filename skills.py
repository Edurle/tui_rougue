"""技能系统：效果类注册表 + 统一施放入口。

skills.json 的 effect.type 从 SKILL_EFFECTS 分发（同 consumable/ai 模式）；
新效果 = 新类 + @register + JSON 引用，机制代码零改动。

伤害公式：power + 修为等级 × scale + 装备词条加成（按技能 tags 匹配）。
目标分流：needs_target（单体）→ 输入层进瞄准模式；needs_direction（位移）
→ 择向模式；其余直接释放。
"""

from __future__ import annotations

import math
import typing

import exceptions

if typing.TYPE_CHECKING:
    from engine import Engine
    from entity import Actor

# 技能 tag -> 装备词条 id（加伤/加治疗）
TAG_AFFIX_MAP = {
    "thunder": "thunder_damage",
    "aoe": "aoe_damage",
    "heal": "heal_power",
}

SKILL_EFFECTS: dict[str, "SkillEffect"] = {}


def register(cls):
    """效果类注册装饰器。"""
    instance = cls()
    SKILL_EFFECTS[cls.TYPE] = instance
    return cls


def skill_level(player: "Actor") -> int:
    return player.level.current_level if player.level else 1


def affix_bonus(player: "Actor", skill: dict, *, extra_tags: list | None = None) -> int:
    """按技能 tags 匹配装备词条的加伤总量。"""
    equipment = getattr(player, "equipment", None)
    if equipment is None:
        return 0
    tags = set(skill.get("tags", [])) | set(extra_tags or [])
    total = 0
    for tag, affix_id in TAG_AFFIX_MAP.items():
        if tag in tags:
            total += equipment.affix(affix_id)
    return total


def compute_damage(player: "Actor", skill: dict, effect: dict | None = None) -> int:
    """power + 等级×scale + 词条加成。"""
    eff = effect if effect is not None else skill["effect"]
    raw = eff.get("power", 0) + skill_level(player) * eff.get("scale", 0)
    raw += affix_bonus(player, skill)
    return max(0, int(round(raw)))


def resist_description(content, target: "Actor", skill: dict) -> str:
    """瞄准 UI 用：技能命中元素中目标抗性最高的描述（如"·雷抗+60%"），无则空。"""
    from fighter import RESIST_DAMAGE_KINDS

    best_kind, best_value = None, 0
    for kind in RESIST_DAMAGE_KINDS:
        if kind in skill.get("tags", []):
            value = target.fighter.resistance(kind)
            if value > best_value:
                best_kind, best_value = kind, value
    if best_kind is None:
        return ""
    return "·" + content.strings[f"resist_{best_kind}"].format(v=best_value)


def compute_poison(player: "Actor", skill: dict) -> tuple[int, int]:
    """蛊毒 DOT：(每回合伤害, 回合数)，伤害吃 power/scale/词条。"""
    eff = skill["effect"]
    damage = eff.get("damage", 0) + skill_level(player) * eff.get("scale", 0)
    if "poison" in skill.get("tags", []):
        equipment = getattr(player, "equipment", None)
        if equipment is not None:
            damage += equipment.affix("poison_damage")
    return max(0, int(round(damage))), int(eff.get("turns", 0))


def mp_cost(player: "Actor", skill: dict) -> int:
    """耗气：装备「耗气-N」词条减免，减免后最低 1；0 耗技能保持 0。"""
    base = int(skill.get("mp", 0))
    if base <= 0:
        return 0
    equipment = getattr(player, "equipment", None)
    reduce = equipment.affix("mp_cost_reduce") if equipment is not None else 0
    return max(1, base - reduce)


def aoe_targets(engine: "Engine", player: "Actor", skill: dict, *, radius=None) -> list:
    """以玩家为中心、指定半径内的敌对存活 actor（友方召唤兽不受波及）。"""
    eff = skill["effect"]
    r = eff.get("radius", 1) if radius is None else radius
    targets = []
    for actor in engine.gamemap.actors:
        if actor is player or actor.team == player.team:
            continue
        if math.hypot(actor.x - player.x, actor.y - player.y) <= r + 1e-9:
            targets.append(actor)
    return targets


def visible_enemies(engine: "Engine", player: "Actor") -> list:
    """玩家视野内的敌对 actor，按距离排序（瞄准候选）。"""
    gamemap = engine.gamemap
    enemies = [
        actor
        for actor in gamemap.actors
        if actor.team != player.team and gamemap.visible[actor.x, actor.y]
    ]
    enemies.sort(key=player.distance_to)
    return enemies


def hit_actor(engine: "Engine", player: "Actor", target: "Actor", damage: int, skill: dict) -> None:
    """对目标造成技能伤害：先按技能元素 tags 吃目标抗性折算。"""
    damage = target.fighter.mitigate_incoming(damage, skill.get("tags", []))
    engine.effects.spawn_damage(
        target.x, target.y, damage, is_player_victim=target is engine.player
    )
    target.fighter.hp -= damage
    if not target.is_alive:
        engine.trigger_kill_heal(player)


def apply_skill_poison(engine: "Engine", player: "Actor", target: "Actor", skill: dict,
                       override: tuple | None = None) -> tuple[int, int]:
    damage, turns = override if override else compute_poison(player, skill)
    if damage > 0 and turns > 0:
        target.fighter.apply_poison(damage, turns)
        engine.effects.spawn_poison_mark(target.x, target.y)
    return damage, turns


class SkillEffect:
    """效果基类：perform 内完成表现与结算，不处理耗气（cast 统一处理）。"""

    TYPE = "?"
    needs_target = False
    needs_direction = False

    def perform(self, engine: "Engine", player: "Actor", skill: dict, target=None) -> None:
        raise NotImplementedError()


@register
class DamageNearest(SkillEffect):
    """单体伤害：瞄准指定目标，可多段（hits）、附毒（poison）。"""

    TYPE = "damage_nearest"
    needs_target = True

    def perform(self, engine, player, skill, target=None):
        if target is None:
            raise exceptions.NeedTarget(skill, skill.get("slot", 0))
        strings = engine.content.strings
        eff = skill["effect"]
        damage = compute_damage(player, skill)
        hits = int(eff.get("hits", 1))
        for _ in range(hits):
            if not target.is_alive:
                break
            hit_actor(engine, player, target, damage, skill)
        name = engine.content._(skill["name"])
        if hits > 1:
            engine.message_log.add_message(
                strings["cast_hits"].format(
                    skill=name, hits=hits, target=target.name, damage=damage * hits
                ),
                "combat",
            )
        else:
            engine.message_log.add_message(
                strings["cast_hit"].format(skill=name, target=target.name, damage=damage),
                "combat",
            )
        if target.is_alive and eff.get("poison"):
            pd, pt = eff["poison"]
            apply_skill_poison(engine, player, target, skill, override=(pd, pt))


@register
class DamageAoeSelf(SkillEffect):
    """以自身为中心的 AOE：可附毒（poison）/附眩晕（stun）。"""

    TYPE = "damage_aoe_self"

    def perform(self, engine, player, skill, target=None):
        strings = engine.content.strings
        eff = skill["effect"]
        targets = aoe_targets(engine, player, skill)
        name = engine.content._(skill["name"])
        if not targets:
            raise exceptions.Impossible(strings["no_enemy_sight"])
        damage = compute_damage(player, skill)
        engine.effects.spawn_aoe_ring(player.x, player.y, eff.get("radius", 1))
        for actor in targets:
            hit_actor(engine, player, actor, damage, skill)
            if actor.is_alive:
                if eff.get("poison"):
                    pd, pt = eff["poison"]
                    apply_skill_poison(engine, player, actor, skill, override=(pd, pt))
                if eff.get("stun"):
                    actor.fighter.apply_stun(int(eff["stun"]))
                    engine.effects.spawn_stun(actor.x, actor.y)
        engine.message_log.add_message(
            strings["cast_aoe"].format(skill=name, count=len(targets)), "combat"
        )


@register
class BuffDefense(SkillEffect):
    TYPE = "buff_defense"

    def perform(self, engine, player, skill, target=None):
        strings = engine.content.strings
        eff = skill["effect"]
        player.fighter.apply_buff("defense", eff["amount"], eff["turns"])
        engine.effects.spawn_buff(player.x, player.y)
        engine.message_log.add_message(
            strings["cast_buff_defense"].format(
                skill=engine.content._(skill["name"]), amount=eff["amount"], turns=eff["turns"]
            ),
            "buff",
        )


@register
class BuffPower(SkillEffect):
    TYPE = "buff_power"

    def perform(self, engine, player, skill, target=None):
        strings = engine.content.strings
        eff = skill["effect"]
        player.fighter.apply_buff("power", eff["amount"], eff["turns"])
        engine.effects.spawn_buff(player.x, player.y)
        engine.message_log.add_message(
            strings["cast_buff_power"].format(
                skill=engine.content._(skill["name"]), amount=eff["amount"], turns=eff["turns"]
            ),
            "buff",
        )


def teleport_landing(engine: "Engine", player: "Actor", skill: dict, dx: int, dy: int) -> tuple:
    """沿八向掠出 range 格的落点（遇墙/越界/被占即停）；返回格子坐标。"""
    rng = int(skill["effect"].get("range", 3))
    last = (player.x, player.y)
    for step in range(1, rng + 1):
        nx, ny = player.x + dx * step, player.y + dy * step
        if not engine.gamemap.in_bounds(nx, ny):
            break
        if not engine.gamemap.tiles["walkable"][nx, ny]:
            break
        if engine.gamemap.get_blocking_entity_at(nx, ny):
            break
        last = (nx, ny)
    return last


@register
class TeleportStep(SkillEffect):
    """位移：沿指定八向掠出 range 格（遇阻即停）。"""

    TYPE = "teleport_step"
    needs_direction = True

    def perform(self, engine, player, skill, target=None):
        if target is None:
            raise exceptions.NeedTarget(skill, skill.get("slot", 0))
        strings = engine.content.strings
        dx, dy = target
        start = (player.x, player.y)
        last = teleport_landing(engine, player, skill, dx, dy)
        if last == start:
            raise exceptions.Impossible(strings["no_enemy_sight"])  # 此方向无处可去
        engine.effects.spawn_trail(start[0], start[1], last[0], last[1])
        player.x, player.y = last
        engine.message_log.add_message(
            strings["cast_teleport"].format(
                skill=engine.content._(skill["name"]), range=skill["effect"].get("range", 3)
            ),
            "buff",
        )
        engine.update_fov()


@register
class HealSelf(SkillEffect):
    """自疗：可附小 AOE 伤害（青丘仙泽）。"""

    TYPE = "heal_self"

    def perform(self, engine, player, skill, target=None):
        strings = engine.content.strings
        eff = skill["effect"]
        amount = eff.get("amount", 0) + skill_level(player) * eff.get("scale", 0)
        equipment = getattr(player, "equipment", None)
        if equipment is not None:
            amount += equipment.affix("heal_power")
        healed = player.fighter.heal(int(round(amount)))
        engine.effects.spawn_heal(player.x, player.y, healed)
        engine.message_log.add_message(
            strings["cast_heal"].format(skill=engine.content._(skill["name"]), amount=healed),
            "heal",
        )
        if eff.get("aoe_radius") and eff.get("aoe_power"):
            aoe_eff = {"power": eff["aoe_power"], "scale": 0, "radius": eff["aoe_radius"]}
            targets = aoe_targets(engine, player, skill, radius=eff["aoe_radius"])
            engine.effects.spawn_aoe_ring(player.x, player.y, eff["aoe_radius"])
            for actor in targets:
                hit_actor(
                    engine, player, actor, compute_damage(player, skill, aoe_eff), skill
                )


@register
class PoisonDot(SkillEffect):
    """单体蛊毒：瞄准指定目标施加 DOT。"""

    TYPE = "poison_dot"
    needs_target = True

    def perform(self, engine, player, skill, target=None):
        if target is None:
            raise exceptions.NeedTarget(skill, skill.get("slot", 0))
        strings = engine.content.strings
        damage, turns = apply_skill_poison(engine, player, target, skill)
        engine.message_log.add_message(
            strings["cast_poison"].format(
                skill=engine.content._(skill["name"]),
                target=target.name,
                damage=damage,
                turns=turns,
            ),
            "combat",
        )


@register
class Summon(SkillEffect):
    """召唤：在玩家近旁空位生成契约兽（时限由引擎递减）。"""

    TYPE = "summon"

    def perform(self, engine, player, skill, target=None):
        strings = engine.content.strings
        eff = skill["effect"]
        spot = self._free_spot(engine, player)
        if spot is None:
            raise exceptions.Impossible(strings["no_enemy_sight"])
        x, y = spot
        beast = engine.content.build_summon(
            engine.gamemap,
            x,
            y,
            name=engine.content._(eff.get("beast_name", {"zh_CN": "灵兽", "en_US": "Beast"})),
            char=eff.get("beast_char", "d"),
            color=tuple(eff.get("beast_color", (220, 190, 120))),
            hp=int(eff.get("beast_hp", 8)),
            power=int(eff.get("beast_power", 4)),
            duration=int(eff.get("duration", 15)),
        )
        engine.effects.spawn_summon(x, y)
        engine.message_log.add_message(
            strings["cast_summon"].format(
                skill=engine.content._(skill["name"]), beast=beast.name
            ),
            "summon",
        )

    @staticmethod
    def _free_spot(engine, player):
        gamemap = engine.gamemap
        for radius in (1, 2):
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    if dx == 0 and dy == 0:
                        continue
                    x, y = player.x + dx, player.y + dy
                    if not gamemap.in_bounds(x, y):
                        continue
                    if gamemap.tiles["walkable"][x, y] and not gamemap.get_blocking_entity_at(x, y):
                        return x, y
        return None


@register
class StunAoe(SkillEffect):
    """AOE 眩晕（可带伤害：power>0）。"""

    TYPE = "stun_aoe"

    def perform(self, engine, player, skill, target=None):
        strings = engine.content.strings
        eff = skill["effect"]
        targets = aoe_targets(engine, player, skill)
        name = engine.content._(skill["name"])
        if not targets:
            raise exceptions.Impossible(strings["no_enemy_sight"])
        engine.effects.spawn_aoe_ring(player.x, player.y, eff.get("radius", 1))
        damage = compute_damage(player, skill) if eff.get("power", 0) > 0 else 0
        for actor in targets:
            if damage:
                hit_actor(engine, player, actor, damage, skill)
            if actor.is_alive:
                actor.fighter.apply_stun(int(eff.get("turns", 1)))
                engine.effects.spawn_stun(actor.x, actor.y)
        engine.message_log.add_message(
            strings["cast_stun"].format(skill=name, count=len(targets)), "combat"
        )


@register
class MpRestore(SkillEffect):
    TYPE = "mp_restore"

    def perform(self, engine, player, skill, target=None):
        strings = engine.content.strings
        if player.fighter.mp >= player.fighter.max_mp:
            raise exceptions.Impossible(strings["mp_full"])
        eff = skill["effect"]
        restored = player.fighter.restore_mp(int(eff.get("amount", 0)))
        engine.effects.spawn_mp(player.x, player.y, restored)
        engine.message_log.add_message(
            strings["cast_mp"].format(
                skill=engine.content._(skill["name"]), amount=restored
            ),
            "heal",
        )


def cast(engine: "Engine", player: "Actor", skill: dict, target=None) -> None:
    """统一施放入口：真气/气血检查 → 效果执行 → 扣耗。"""
    strings = engine.content.strings
    cost = mp_cost(player, skill)
    if player.fighter.mp < cost:
        raise exceptions.Impossible(strings["mp_low"])
    hp_cost = int(skill["effect"].get("hp_cost", 0))
    if hp_cost and player.fighter.hp <= hp_cost:
        raise exceptions.Impossible(strings["hp_low"])
    effect = SKILL_EFFECTS[skill["effect"]["type"]]
    effect.perform(engine, player, skill, target)
    # 效果成功落地才结算消耗
    player.fighter.mp -= cost
    if hp_cost:
        player.fighter.hp -= hp_cost
        engine.effects.spawn_damage(player.x, player.y, hp_cost, is_player_victim=True)
