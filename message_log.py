"""消息日志：战斗与事件提示的滚动记录。"""

import textwrap
from typing import List


class Message:
    def __init__(self, text: str, fg: tuple) -> None:
        self.plain_text = text
        self.fg = fg
        self.count = 1

    @property
    def full_text(self) -> str:
        """相邻同名消息合并计数，避免刷屏。"""
        if self.count > 1:
            return f"{self.plain_text}（x{self.count}）"
        return self.plain_text


class MessageLog:
    def __init__(self, x: int, width: int, height: int) -> None:
        self.messages: List[Message] = []
        self.x = x
        self.width = width
        self.height = height

    def add_message(self, text: str, fg: tuple = (230, 230, 230)) -> None:
        """新消息若与上一条相同则计数，否则按宽度折行后追加。"""
        if self.messages and self.messages[-1].plain_text == text:
            self.messages[-1].count += 1
            return
        wrapped = textwrap.wrap(text, self.width)
        for line in wrapped:
            if len(self.messages) == self.height:
                del self.messages[0]
            self.messages.append(Message(line, fg))

    def render(self, console, start_y: int) -> None:
        for i, message in enumerate(self.messages):
            console.print(self.x, start_y + i, message.full_text, fg=message.fg)
