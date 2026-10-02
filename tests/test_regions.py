"""山川游历区域测试：卷目覆盖、山名循环、叙事消息、卷目投放。"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from actions import TakeStairsAction  # noqa: E402
from content_loader import ContentError, load_content  # noqa: E402
from engine import Engine  # noqa: E402
from settings import Settings  # noqa: E402


def test_region_boundaries():
    content = load_content("zh_CN")
    assert content.region_for_floor(1)["id"] == "nanshanjing"
    assert content.region_for_floor(3)["id"] == "nanshanjing"
    assert content.region_for_floor(4)["id"] == "xishanjing"
    assert content.region_for_floor(7)["id"] == "beishanjing"
    assert content.region_for_floor(10)["id"] == "dongshanjing"
    assert content.region_for_floor(13)["id"] == "zhongshanjing"
    assert content.region_for_floor(16)["id"] == "dahuangjing"
    assert content.region_for_floor(99)["id"] == "dahuangjing"  # 开区间


def test_mountain_names_sequence_and_cycle():
    content = load_content("zh_CN")
    assert content.mountain_for_floor(1) == "招摇之山"
    assert content.mountain_for_floor(2) == "青丘之山"
    assert content.mountain_for_floor(5) == "小华之山"  # 西山经第 2 座
    assert content.mountain_for_floor(4) == "华山"
    assert content.mountain_for_floor(19) == content.mountain_for_floor(16)  # 大荒 3 山循环

    en = load_content("en_US")
    assert en.mountain_for_floor(1) == "Mt. Zhaoyao"
    assert en.region_name_for_floor(16) == "Great Wilderness"


def test_region_gap_rejected(tmp_path, monkeypatch):
    import json

    from content_loader import CONTENT_DIR, Content
    from paths import resource_path

    monkeypatch.chdir(tmp_path)
    src = resource_path(CONTENT_DIR)
    dest = tmp_path / "content"
    for f in src.rglob("*"):
        if f.is_file():
            rel = f.relative_to(src)
            (dest / rel.parent).mkdir(parents=True, exist_ok=True)
            (dest / rel).write_bytes(f.read_bytes())
    data = json.loads((dest / "regions.json").read_text(encoding="utf-8"))
    data["regions"][1]["min_floor"] = 5  # 制造 4 层空档
    (dest / "regions.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    try:
        Content(dest / ".." / "content" if False else dest)
    except ContentError as exc:
        assert "不连续" in str(exc)
    else:
        raise AssertionError("楼层空档应被校验拒绝")


def test_descend_message_contains_region_and_mountain():
    engine = Engine(load_content("zh_CN"), Settings())
    for expected_mountain in ("青丘之山", "堂庭之山", "华山"):  # 第 2、3、4 层
        engine.player.x, engine.player.y = engine.gamemap.downstairs_xy
        TakeStairsAction(engine.player, "down").perform(engine)
        joined = "".join(m.plain_text for m in engine.message_log.messages).replace(" ", "")
        assert expected_mountain in joined, f"消息应包含 {expected_mountain}：{joined}"
    assert "西山经" in joined


def test_spawn_table_matches_regions():
    content = load_content()
    for floor in range(1, 20):
        ids = content.monster_ids_for_floor(floor)
        assert ids, f"第 {floor} 层无可投放怪物"


def test_new_monsters_present():
    content = load_content()
    for mid in ("luwu", "bifang", "zhudu", "qiuyu", "mafu", "xiangliu", "zhulong"):
        assert mid in content.monsters
        assert content.monsters[mid]["components"]["fighter"]["hp"] > 0


def test_new_monster_glyphs_are_single_ascii():
    content = load_content()
    for mid in ("luwu", "bifang", "zhudu", "qiuyu", "mafu", "xiangliu", "zhulong"):
        ch = content.monsters[mid]["char"]
        assert len(ch) == 1 and ch.isascii()


def test_contextual_hints_render():
    import tcod

    import render

    content = load_content("zh_CN")
    engine = Engine(content, Settings())

    engine.player.x, engine.player.y = engine.gamemap.downstairs_xy  # 站上金色山径
    content.build_item("lingzhi", engine.gamemap, engine.player.x, engine.player.y)  # 脚下放灵芝
    console = tcod.console.Console(40, 24, order="F")
    render.render_all(console, engine)

    texts = []
    for y in (6, 7):
        line = "".join(chr(c) for c in console.rgb[27:40, y]["ch"] if c != 32)
        texts.append(line)
    joined = "".join(texts)
    assert ">" in joined and "深入" in joined.replace(" ", "")
    assert "G" in joined and "拾取" in joined.replace(" ", "")

    engine.player.x += 1  # 离开山径与物品
    # 清掉近旁的随机投放物品，避免新位置再触发拾取提示
    for existing in list(engine.gamemap.items):
        if abs(existing.x - engine.player.x) <= 1 and abs(existing.y - engine.player.y) <= 1:
            engine.gamemap.entities.discard(existing)
    render.render_all(console, engine)
    joined = "".join(
        "".join(chr(c) for c in console.rgb[27:40, y]["ch"] if c != 32) for y in (6, 7)
    )
    assert ">" not in joined and "拾取" not in joined.replace(" ", "")
