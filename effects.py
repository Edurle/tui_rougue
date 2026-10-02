"""特效系统：纯表现层动画，回合逻辑不依赖。

所有特效对象带出生时间戳，update(dt) 推进并清理过期项，render 叠加在
主渲染之上。参数全部来自 theme.json 的 effects 节。
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


def _fade(life_ratio: float) -> float:
    return max(0.0, min(1.0, life_ratio))


@dataclass
class FloatText:
    x: float
    y: float
    text: str
    color: Tuple[int, int, int]
    born: float
    big: bool = False


@dataclass
class Spark:
    x: float
    y: float
    vx: float
    vy: float
    char: str
    color: Tuple[int, int, int]
    born: float


@dataclass
class Notice:
    x: int
    y: int
    born: float
    char: str = "!"
    color: Tuple[int, int, int] = (255, 222, 122)


class Effects:
    def __init__(self, cfg: dict, clock=time.perf_counter) -> None:
        self.cfg = cfg
        self._clock = clock
        self.float_texts: List[FloatText] = []
        self.sparks: List[Spark] = []
        self.notices: List[Notice] = []
        self.hit_flash = 0.0
        self.shake_offset: Tuple[int, int] = (0, 0)
        self._shake_energy = 0.0

    # ---- 触发 ----

    def spawn_damage(self, x: int, y: int, amount: int, is_player_victim: bool) -> None:
        color = (244, 96, 96) if is_player_victim else (246, 226, 160)
        self.float_texts.append(FloatText(x, y, f"-{amount}", color, self._clock()))
        if is_player_victim:
            self.hit_flash = self.cfg["hit_flash_strength"]
            self._shake_energy = self.cfg["shake_strength"]

    def spawn_heal(self, x: int, y: int, amount: int) -> None:
        self.float_texts.append(FloatText(x, y, f"+{amount}", (122, 232, 190), self._clock()))

    def spawn_lightning(self, x: int, y: int, amount: int, color: Tuple[int, int, int]) -> None:
        self.float_texts.append(
            FloatText(x, y, f"-{amount}", color, self._clock(), big=True)
        )
        now = self._clock()
        for i in range(8):
            angle = i * math.pi / 4
            self.sparks.append(
                Spark(x, y, math.cos(angle) * 5, math.sin(angle) * 5, "✦", color, now)
            )

    def spawn_level_up(self, x: int, y: int) -> None:
        now = self._clock()
        color = (255, 222, 122)
        for i in range(8):
            angle = i * math.pi / 4 + math.pi / 8
            speed = self.cfg["spark_speed"]
            self.sparks.append(
                Spark(x, y, math.cos(angle) * speed, math.sin(angle) * speed, "✦", color, now)
            )

    def spawn_pickup(self, x: int, y: int) -> None:
        now = self._clock()
        color = (240, 208, 128)
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            self.sparks.append(Spark(x, y, dx * 3, dy * 3, "✦", color, now))

    def spawn_notice(self, x: int, y: int) -> None:
        self.notices.append(Notice(x, y, self._clock()))

    # ---- 技能特效 ----

    def spawn_aoe_ring(self, x: int, y: int, radius: float) -> None:
        """AOE 环形扩散粒子。"""
        now = self._clock()
        color = (196, 168, 255)
        count = max(8, int(radius * 6))
        for i in range(count):
            angle = i * 2 * math.pi / count
            r = max(0.8, radius)
            self.sparks.append(
                Spark(x, y, math.cos(angle) * r * 2.4, math.sin(angle) * r * 2.4, "✦", color, now)
            )

    def spawn_buff(self, x: int, y: int) -> None:
        """增益金光标记。"""
        self.float_texts.append(FloatText(x, y, "↑", (255, 222, 122), self._clock(), big=True))

    def spawn_trail(self, x0: int, y0: int, x1: int, y1: int) -> None:
        """位移残影：起点到落点沿线粒子。"""
        now = self._clock()
        steps = max(1, int(math.hypot(x1 - x0, y1 - y0)))
        color = (170, 200, 255)
        for i in range(steps + 1):
            t = i / steps
            self.sparks.append(
                Spark(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, 0, -0.5, "·", color, now)
            )

    def spawn_poison_mark(self, x: int, y: int) -> None:
        self.float_texts.append(FloatText(x, y, "毒", (140, 220, 110), self._clock()))

    def spawn_poison_tick(self, x: int, y: int, amount: int) -> None:
        self.float_texts.append(FloatText(x, y, f"-{amount}", (140, 220, 110), self._clock()))

    def spawn_stun(self, x: int, y: int) -> None:
        self.notices.append(Notice(x, y, self._clock(), char="!", color=(180, 180, 190)))

    def spawn_mp(self, x: int, y: int, amount: int) -> None:
        self.float_texts.append(FloatText(x, y, f"+{amount}", (120, 226, 232), self._clock()))

    def spawn_summon(self, x: int, y: int) -> None:
        now = self._clock()
        color = (150, 220, 240)
        for i in range(8):
            angle = i * math.pi / 4
            self.sparks.append(
                Spark(x, y, math.cos(angle) * -3, math.sin(angle) * -3, "✦", color, now)
            )

    def clear(self) -> None:
        self.float_texts.clear()
        self.sparks.clear()
        self.notices.clear()
        self.hit_flash = 0.0
        self._shake_energy = 0.0
        self.shake_offset = (0, 0)

    # ---- 推进 ----

    def update(self, dt: float) -> None:
        now = self._clock()
        life_float = self.cfg["float_lifetime"]
        life_spark = self.cfg["spark_lifetime"]
        life_notice = self.cfg["notice_lifetime"]
        self.float_texts = [f for f in self.float_texts if now - f.born < life_float]
        self.sparks = [s for s in self.sparks if now - s.born < life_spark]
        self.notices = [n for n in self.notices if now - n.born < life_notice]

        decay = self.cfg["hit_flash_decay"]
        self.hit_flash = max(0.0, self.hit_flash - self.hit_flash * decay * dt)
        if self.hit_flash < 0.01:
            self.hit_flash = 0.0

        self._shake_energy = max(0.0, self._shake_energy - self.cfg["shake_decay"] * dt)
        if self._shake_energy > 0.05:
            self.shake_offset = (
                int(round(math.sin(now * 85) * self._shake_energy)),
                int(round(math.cos(now * 67) * self._shake_energy * 0.6)),
            )
        else:
            self.shake_offset = (0, 0)

    # ---- 渲染 ----

    def render(self, console, map_width: int, map_height: int, off_x: int = 0, off_y: int = 0) -> None:
        """叠加渲染；off 为地图坐标 → 视口坐标平移（摄像机+震屏）。"""
        now = self._clock()

        def blend(color: Tuple[int, int, int], ratio: float) -> Tuple[int, int, int]:
            return tuple(int(c * _fade(ratio)) for c in color)

        speed = self.cfg["float_speed"]
        life_float = self.cfg["float_lifetime"]
        for f in self.float_texts:
            age = now - f.born
            ratio = 1 - age / life_float
            dy = -age * speed
            x = int(f.x) + off_x
            y = int(f.y + dy) + off_y
            if 0 <= x < map_width and 0 <= y < map_height:
                console.print(x, y, f.text, fg=blend(f.color, ratio))

        life_spark = self.cfg["spark_lifetime"]
        for s in self.sparks:
            age = now - s.born
            ratio = 1 - age / life_spark
            x = int(s.x + s.vx * age) + off_x
            y = int(s.y + s.vy * age) + off_y
            if 0 <= x < map_width and 0 <= y < map_height:
                console.print(x, y, s.char, fg=blend(s.color, ratio))

        life_notice = self.cfg["notice_lifetime"]
        for n in self.notices:
            age = now - n.born
            ratio = 1 - age / life_notice
            x, y = n.x + off_x, n.y - 1 + off_y
            if 0 <= x < map_width and 0 <= y < map_height:
                console.print(x, y, n.char, fg=blend(n.color, ratio))
