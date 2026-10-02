"""冒烟截图画廊：多场景渲染并保存 PNG 供视觉复核。

用法：./.venv/Scripts/python.exe tools/smoke_gallery.py [输出目录]
场景：大世界×2 / 秘境·BOSS 层 / 参悟(K) / 瞄准 / 择向 / 行囊+装备 /
职业选择（含继续游历）/ 中档布局。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tcod

import input_handlers as ih
from actions import EquipAction, TakeStairsAction
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


def clear_view(engine, x1, x2, y1, y2):
    """把包围盒清成开阔地，保证镜头前的怪可见（世界森林遮视野）。"""
    import tile_types

    gm = engine.gamemap
    for x in range(min(x1, x2), max(x1, x2) + 1):
        for y in range(min(y1, y2), max(y1, y2) + 1):
            if gm.in_bounds(x, y):
                gm.terrain[x, y] = tile_types.T_PLAIN
    gm.refresh_tile_flags()


def put_monster(engine, dx, dy, monster_id):
    clear_view(engine, engine.player.x, engine.player.x + dx, engine.player.y, engine.player.y + dy)
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

        # 1) 大世界：雷法+符师，学满主职、装三件装备、身侧两怪
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
        make_shot(engine, ih.MainGameEventHandler(engine), "shot_world_main", context, console)

        # 2) 大世界旅行：向东连走一段，展示多样地形
        engine.traveling = (1, 0)
        for _ in range(60):
            engine.travel_step()
            if engine.traveling is None:
                break
        make_shot(engine, ih.MainGameEventHandler(engine), "shot_world_travel", context, console)

        # 3) 秘境第 1 层（回世界出生点附近找新手秘境入口）
        gate = next(
            e for e in engine.world.entities
            if "realm_gate" in e.tags and "yaoshan_gudong" in e.tags
        )
        engine.player.x, engine.player.y = gate.x, gate.y
        TakeStairsAction(engine.player, "down").perform(engine)
        engine.gamemap.explored[:] = False
        engine.update_fov()
        make_shot(engine, ih.MainGameEventHandler(engine), "shot_realm", context, console)

        # 4) 秘境 BOSS 层（鸣蛇盘踞）
        engine.player.x, engine.player.y = engine.gamemap.downstairs_xy
        TakeStairsAction(engine.player, "down").perform(engine)
        boss = next(a for a in engine.gamemap.actors if "boss" in a.tags)
        # 把玩家挪近 BOSS 房门口
        clear_view(engine, boss.x, boss.x + 8, boss.y, boss.y)
        engine.player.x, engine.player.y = boss.x + 6, boss.y
        engine.update_fov()
        make_shot(engine, ih.MainGameEventHandler(engine), "shot_realm_boss", context, console)

        # 5) 参悟界面（K）
        make_shot(engine, ih.SkillLearnEventHandler(engine), "shot_learn", context, console)

        # 6) 瞄准态：掌心雷
        engine.player.fighter.mp = engine.player.fighter.max_mp
        skill = content.skill_for_slot("leifa", 1)
        make_shot(engine, ih.TargetingEventHandler(engine, skill, 1), "shot_targeting", context, console)

        # 7) 择向态：疾风步
        skill2 = content.skill_for_slot("leifa", 2)
        make_shot(engine, ih.DirectionSelectEventHandler(engine, skill2, 2), "shot_direction", context, console)

        # 8) 行囊（含装备区）
        make_shot(engine, ih.InventoryEventHandler(engine), "shot_inventory", context, console)

        # 9) 职业选择（有存档：顶部"继续游历"）
        engine.autosave()
        selector = ih.ClassSelectEventHandler(content, settings, has_save=True)
        selector.on_render(console)
        context.present(console, keep_aspect=True, integer_scaling=True)
        path = OUT / "shot_class_select.png"
        context.save_screenshot(str(path))
        print(f"已保存 {path}")
        import save_manager

        save_manager.delete_save()

    # 10) 中档布局（32 行完整技能区）
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
