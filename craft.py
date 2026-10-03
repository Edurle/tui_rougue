"""天工开物：炼丹 / 炼器 / 炼符的配方执行。

配方与材料全在 crafting.json / items.json（数据驱动，代码零内容）。
execute_recipe 做四件事：材料检查（含堆叠计数）→ 扣料 → 产出入囊 → 消息。
由 C 键炼制界面调用，不消耗回合。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List

import exceptions

if TYPE_CHECKING:
    from engine import Engine

# 炼制三系的展示顺序与名称键
CRAFT_KINDS = ("alchemy", "forge", "talisman")


def recipes_of_kind(content, kind: str) -> List[dict]:
    return [r for r in content.recipes if r["kind"] == kind]


def materials_of(content):
    """items.json 中的全部材料定义（材料摘要行用）。"""
    return {iid: idef for iid, idef in content.items.items() if "material" in idef.get("tags", [])}


def recipe_requirements(engine: "Engine", recipe: dict) -> list:
    """逐材料 [(id, 名称, 需求, 持有, 足否)]，渲染与执行共用。"""
    content = engine.content
    out = []
    for entry in recipe["inputs"]:
        have = engine.player.inventory.count_material(entry["id"], content)
        out.append(
            (
                entry["id"],
                content._(content.items[entry["id"]]["name"]),
                int(entry["count"]),
                have,
                have >= entry["count"],
            )
        )
    return out


def can_craft(engine: "Engine", recipe: dict) -> bool:
    return all(ok for _, _, _, _, ok in recipe_requirements(engine, recipe))


def execute_recipe(engine: "Engine", recipe: dict) -> None:
    """炼制：扣材料、产出入囊。材料不足抛 Impossible（界面层提示）。"""
    strings = engine.content.strings
    content = engine.content
    if not can_craft(engine, recipe):
        raise exceptions.Impossible(strings["craft_no_materials"])

    for entry in recipe["inputs"]:
        engine.player.inventory.take_material(entry["id"], int(entry["count"]), content)

    output = recipe["output"]
    item = content.build_item(output["id"], engine.gamemap, engine.player.x, engine.player.y)
    engine.gamemap.entities.discard(item)
    item.gamemap = engine.player.gamemap  # 行囊物品组件经它回溯 engine
    count = int(output.get("count", 1))
    if item.is_material:
        item.stack = count
    engine.player.inventory.add(item)  # 行囊无上限，直接入囊

    engine.effects.spawn_buff(engine.player.x, engine.player.y)
    label = item.name + (f"×{count}" if count > 1 else "")
    engine.message_log.add_message(
        strings["craft_ok"].format(recipe=content._(recipe["name"]), item=label), "levelup"
    )
