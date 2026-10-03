"""测试全局隔离：存档目录指向临时路径，防止测试 autosave 污染真实存档。

历史教训：test_realms/test_stairs_log 等触发 enter/exit/next_floor 的
autosave 曾把测试引擎状态（秘境第 N 层、等级 1）写进真实 saves/save.json，
玩家读档后"莫名身处秘境"。
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_save_dir(tmp_path, monkeypatch):
    import save_manager

    monkeypatch.setattr(save_manager, "SAVE_DIR", str(tmp_path / "saves"))
