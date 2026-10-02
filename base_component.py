"""组件基类：所有可挂到实体上的组件（战斗/AI/成长/物品效果等）继承此类。

扩展新系统（五行、卦象、工艺等）时新建组件子类并挂到 Actor/Item 上即可，
核心引擎无需改动。
"""

from __future__ import annotations

import typing

if typing.TYPE_CHECKING:
    from engine import Engine
    from entity import Entity


class BaseComponent:
    parent: Entity  # type: ignore[assignment]

    @property
    def gamemap(self):
        return self.parent.gamemap

    @property
    def engine(self) -> Engine:
        return self.gamemap.engine
