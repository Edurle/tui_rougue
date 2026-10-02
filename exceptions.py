"""控制流异常。"""


class Impossible(Exception):
    """动作无法执行。异常消息将作为游戏内提示展示给玩家。"""


class NeedTarget(Exception):
    """技能需要玩家指定目标/方向。携带技能上下文，由主循环切换输入模式。"""

    def __init__(self, skill: dict, slot: int, message: str = "") -> None:
        super().__init__(message)
        self.skill = skill
        self.slot = slot
