"""控制流异常。"""


class Impossible(Exception):
    """动作无法执行。异常消息将作为游戏内提示展示给玩家。"""
