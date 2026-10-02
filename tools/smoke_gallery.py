"""冒烟截图画廊：多场景渲染并保存 PNG 供视觉复核。

用法：./.venv/Scripts/python.exe tools/smoke_gallery.py [输出目录]
场景：主界面×2 双职业 / 参悟(K) / 瞄准 / 择向 / 行囊+装备 / 职业选择 / 中档布局。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tcod

import input_handlers as ih
from actions import EquipAction
from content_loader import load_content
from engine import Engine
from main import build_tileset
from settings import Settings

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("tools")
OUT.mkdir(parents=True, exist_ok=True)


def learn_all(engine, class_id):
    player = engine.player
    player.skill_points = 99
    for _ in range(10):
        progress = False
        for skill in engine.content.skills_for_class(class_id):
            if skill["id"] not in player.learned_skills:
                try:
                    engine.learn_skill(skill["id"])
                    progress = True
                except Exception:
                    pass
        if not progress:
            break


def put_monster(engine, dx, dy, monster_id):
    return engine.content.build_monster(
        monster_id, engine.gamemap, engine.player.x + dx, engine.player.y + dy
    )


def make_shot(engine, handler, name, context, console):
    handler.on_render(console)
    context.present(console, keep_aspect=True, integer_scaling=True)
    path = OUT / f"{name}.png"
    context.save_screenshot(str(path))
    print(f"已保存 {path}")


def run() -> None:
    content = load_content("zh_CN")
    settings = Settings()
    tileset = build_tileset(content, settings)
    with tcod.context.new(
        columns=settings.total_cols,
        rows=settings.total_rows,
        tileset=tileset,
        title="smoke",
        vsync=True,
    ) as context:
        console = tcod.console.Console(settings.total_cols, settings.total_rows, order="F")

        # 1) 雷法+符师：学满主职、装两件装备、身侧两怪
        engine = Engine(content, settings, ("leifa", "fushi"))
        learn_all(engine, "leifa")
        for iid in ("w_taomu", "a_xuangui", "b_zhuifeng"):
            item = content.build_item(iid, engine.gamemap, 0, 0)
            engine.gamemap.entities.discard(item)
            engine.player.inventory.add(item)
            EquipAction(engine.player, item).perform(engine)
        put_monster(engine, 2, 0, "xingxing")
        put_monster(engine, 3, 1, "gudiao")
        engine.update_fov()
        make_shot(engine, ih.MainGameEventHandler(engine), "shot_leifa_fushi", context, console)

        # 2) 夸父+乐师（副职业页）
        engine2 = Engine(content, settings, ("kuafu", "yueshi"))
        learn_all(engine2, "kuafu")
        put_monster(engine2, -2, 0, "bifang")
        engine2.update_fov()
        handler2 = ih.MainGameEventHandler(engine2)
        make_shot(engine2, handler2, "shot_kuafu_yueshi", context, console)

        # 3) 参悟界面（K）
        make_shot(engine, ih.SkillLearnEventHandler(engine), "shot_learn", context, console)

        # 4) 瞄准态：掌心雷锁定近怪
        engine.player.fighter.mp = engine.player.fighter.max_mp
        skill = content.skill_for_slot("leifa", 1)
        make_shot(engine, ih.TargetingEventHandler(engine, skill, 1), "shot_targeting", context, console)

        # 5) 择向态：疾风步
        skill2 = content.skill_for_slot("leifa", 2)
        make_shot(engine, ih.DirectionSelectEventHandler(engine, skill2, 2), "shot_direction", context, console)

        # 6) 行囊（含装备区）
        make_shot(engine, ih.InventoryEventHandler(engine), "shot_inventory", context, console)

        # 7) 职业选择
        selector = ih.ClassSelectEventHandler(content, settings)
        selector.on_render(console)
        context.present(console, keep_aspect=True, integer_scaling=True)
        path = OUT / "shot_class_select.png"
        context.save_screenshot(str(path))
        print(f"已保存 {path}")

    # 8) 中档布局（32 行完整技能区）
    settings_m = Settings("medium", "large")
    tileset_m = build_tileset(content, settings_m)
    with tcod.context.new(
        columns=settings_m.total_cols,
        rows=settings_m.total_rows,
        tileset=tileset_m,
        title="smoke-medium",
        vsync=True,
    ) as context:
        console_m = tcod.console.Console(settings_m.total_cols, settings_m.total_rows, order="F")
        engine_m = Engine(content, settings_m, ("jianke", "wuzhu"))
        learn_all(engine_m, "jianke")
        put_monster(engine_m, 2, 0, "luwu")
        engine_m.update_fov()
        make_shot(engine_m, ih.MainGameEventHandler(engine_m), "shot_medium_layout", context, console_m)


if __name__ == "__main__":
    run()
