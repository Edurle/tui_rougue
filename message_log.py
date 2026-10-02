"""消息日志：滚动记录 + 按语义类型自动着色（颜色取自 theme.json）。"""

import textwrap
from typing import List, Optional


class Message:
    def __init__(self, text: str, kind: str) -> None:
        self.plain_text = text
        self.kind = kind
        self.count = 1

    @property
    def full_text(self) -> str:
        if self.count > 1:
            return f"{self.plain_text}（x{self.count}）"
        return self.plain_text


class MessageLog:
    def __init__(self, x: int, width: int, height: int, theme_messages: Optional[dict] = None) -> None:
        self.messages: List[Message] = []
        self.x = x
        self.width = width
        self.height = height
        self._theme_messages = theme_messages or {}
        self.scroll_offset = 0  # 回看偏移：0=停在最新，>0 向上翻历史

    def add_message(self, text: str, kind: str = "info") -> None:
        if self.messages and self.messages[-1].plain_text == text and self.messages[-1].kind == kind:
            self.messages[-1].count += 1
            return
        wrapped = textwrap.wrap(text, self.width)
        # 保留完整历史供回看；渲染窗口只显示最新 height 行
        self.messages.extend(Message(line, kind) for line in wrapped)
        overflow = len(self.messages) - max(200, self.height * 20)
        if overflow > 0:
            del self.messages[:overflow]
        self.scroll_offset = 0

    def scroll(self, delta: int) -> None:
        max_offset = max(0, len(self.messages) - self.height)
        self.scroll_offset = max(0, min(max_offset, self.scroll_offset + delta))

    def visible_window(self) -> slice:
        end = len(self.messages) - self.scroll_offset
        return slice(max(0, end - self.height), end)

    def render(self, console, start_y: int) -> None:
        window = self.visible_window()
        visible = self.messages[window]
        total = len(self.messages)
        for i, message in enumerate(visible):
            color = self._theme_messages.get(message.kind, (200, 200, 200))
            index = window.start + i
            age = total - 1 - index  # 距最新消息的条数
            if age >= 3:
                dim = max(0.45, 1.0 - (age - 2) * 0.12)
                color = tuple(int(c * dim) for c in color)
            console.print(self.x, start_y + i, message.full_text, fg=color)
        if self.scroll_offset > 0:
            console.print(self.x, start_y - 1, "▲", fg=(214, 176, 96))
