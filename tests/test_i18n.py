"""多语言测试：语言文件完整性、实体名本地化、回退与英文模式运行。"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from content_loader import (  # noqa: E402
    DEFAULT_LANG,
    SUPPORTED_LANGS,
    Content,
    ContentError,
    load_content,
)
from engine import Engine
from settings import Settings  # noqa: E402


def test_supported_langs_load():
    for lang in SUPPORTED_LANGS:
        content = load_content(lang)
        assert content.strings["welcome"], f"{lang} 缺 welcome 文案"
        assert content.strings["window_title"], f"{lang} 缺窗口标题"


def test_string_key_parity():
    zh = load_content("zh_CN").strings
    en = load_content("en_US").strings
    zh_only = set(zh) - set(en)
    en_only = set(en) - set(zh)
    assert not zh_only, f"en_US 缺少键：{zh_only}"
    assert not en_only, f"en_US 多出键：{en_only}"


def test_entity_names_localized():
    zh = load_content("zh_CN")
    en = load_content("en_US")
    assert zh.monsters["xingxing"]["name"] == {"zh_CN": "狌狌", "en_US": "Xingxing"}
    assert en.items["wulei_fu"]["name"]["en_US"] == "Thunder Talisman"
    assert en.player_def["name"]["en_US"] == "Wanderer"


def test_text_resolver_fallback():
    en = load_content("en_US")
    assert en._({"zh_CN": "中", "en_US": "en"}) == "en"
    assert en._({"zh_CN": "只有中文"}) == "只有中文"
    assert en._("plain") == "plain"
    assert en._({"ja_JP": "他语言"}) == "他语言"


def test_unknown_lang_rejected():
    try:
        load_content("fr_FR")
    except ContentError:
        pass
    else:
        raise AssertionError("不支持的语言应当报错")


def test_english_engine_full_flow():
    content = load_content("en_US")
    engine = Engine(content, Settings())
    assert engine.player.name == "Wanderer"
    monster = content.build_monster("xingxing", engine.gamemap, engine.player.x + 1, engine.player.y)
    assert monster.name == "Xingxing"
    for _ in range(80):
        engine.player.fighter.attack(monster.fighter)
        if not monster.is_alive:
            break
    assert not monster.is_alive
    assert engine.player.level.current_xp > 0
