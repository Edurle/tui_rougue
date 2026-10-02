"""特效系统测试。"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tcod  # noqa: E402

from content_loader import load_content  # noqa: E402
from effects import Effects  # noqa: E402
from engine import Engine
from settings import Settings  # noqa: E402
import render  # noqa: E402


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, dt: float) -> None:
        self.now += dt


def make_effects(clock=None) -> Effects:
    cfg = load_content().theme["effects"]
    return Effects(cfg, clock=clock) if clock else Effects(cfg)


def test_hit_flash_and_shake_on_player_damage():
    fx = make_effects()
    fx.spawn_damage(5, 5, 4, is_player_victim=True)
    assert fx.hit_flash > 0.2
    assert fx._shake_energy > 0
    assert len(fx.float_texts) == 1
    assert fx.float_texts[0].text == "-4"


def test_monster_damage_no_flash():
    fx = make_effects()
    fx.spawn_damage(5, 5, 3, is_player_victim=False)
    assert fx.hit_flash == 0.0
    assert fx._shake_energy == 0.0


def test_update_decays_and_expires():
    clock = FakeClock()
    fx = make_effects(clock)
    fx.spawn_damage(5, 5, 4, is_player_victim=True)
    flash0 = fx.hit_flash
    fx.update(1 / 60)
    clock.advance(1 / 60)
    assert fx.hit_flash < flash0
    for _ in range(600):
        clock.advance(1 / 60)
        fx.update(1 / 60)
    assert fx.hit_flash == 0.0
    assert fx.shake_offset == (0, 0)
    assert not fx.float_texts


def test_level_up_sparks_eight_directions():
    fx = make_effects()
    fx.spawn_level_up(4, 4)
    assert len(fx.sparks) == 8


def test_notice_lifecycle():
    clock = FakeClock()
    fx = make_effects(clock)
    fx.spawn_notice(3, 3)
    assert len(fx.notices) == 1
    for _ in range(120):
        clock.advance(1 / 60)
        fx.update(1 / 60)
    assert not fx.notices


def test_effects_render_headless():
    fx = make_effects()
    fx.spawn_damage(5, 5, 4, is_player_victim=False)
    fx.spawn_heal(6, 6, 8)
    fx.spawn_level_up(7, 7)
    fx.spawn_notice(8, 8)
    console = tcod.console.Console(40, 24, order="F")
    fx.render(console, 26, 24)


def test_engine_has_effects_and_combat_triggers():
    content = load_content()
    engine = Engine(content, Settings())
    monster = content.build_monster("xingxing", engine.gamemap, engine.player.x + 1, engine.player.y)
    engine.player.fighter.power = 50  # 保证命中且致死，走完整特效链
    for _ in range(20):
        engine.player.fighter.attack(monster.fighter)
        if not monster.is_alive:
            break
    assert not monster.is_alive
    assert engine.effects.float_texts or engine.effects.sparks  # 伤害飘字/死亡粒子已生成
