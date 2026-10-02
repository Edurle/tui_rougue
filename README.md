# 山海行 — 字符 Roguelike

以《山海经》异兽为对手的终端风地牢探索游戏。Python + [python-tcod](https://github.com/libtcod/python-tcod)（libtcod）渲染点阵字符画面，**全部内容数值由 JSON 数据驱动**，为后续国风内容内核（周易占卜、天工开物合成）预留了扩展位。

## 运行

需要 Python 3.10+：

```bash
python -m venv .venv
.venv/Scripts/pip install tcod pyinstaller pytest pillow
.venv/Scripts/python main.py
```

或者直接运行打包好的单文件（无需安装 Python）：

```
dist\shanhai_rogue.exe
```

重新打包：双击 `build.bat`（或 `pyinstaller --onefile --name shanhai_rogue --add-data "assets;assets" --add-data "data;data" main.py`）。

## 玩法

下潜无尽的地下层，击杀异兽提升修为，死亡即结束（回车转世重开）。

| 按键 | 功能 |
|---|---|
| 方向键 / WASD / HJKLYUBN（vi 八方向）/ 小键盘 | 移动；走向异兽即攻击 |
| `.` 或小键盘 5 | 原地等待一回合 |
| `G` 或 `,` | 拾取脚下的物品 |
| `I` | 打开行囊，按字母使用对应物品 |
| `>`（Shift+句号） | 在石阶上下楼 |
| `Esc` | 关闭菜单 / 退出游戏 |

初始行囊为空。灵芝恢复气血，五雷符雷击最近的可见敌人。击杀获得修为，自动升级（气血上限+8、攻+1、防+1）。

## 修改与扩展内容（不用改代码）

所有内容在 `data/content/`：

- **monsters.json** — 异兽定义（字符、颜色、战斗数值、AI 类型、tags、出处典籍）
- **items.json** — 物品与效果
- **spawn_tables.json** — 各层投放权重与数量（难度曲线）
- **player.json** — 玩家初始属性、升级加成、行囊容量
- **strings.json** — 全部游戏内文案模板（整体润色只动这里）
- **hexagrams.json / crafting.json** — 周易占卜、天工开物合成的**占位数据**（schema 已定，系统未实现）

新增一只异兽 = 在 monsters.json 加一条 + 在 spawn_tables.json 配置投放层与权重，重启即生效。新行为/新效果才需要写代码：在 `ai.py` / `consumable.py` 的注册表加一个类，然后数据里引用类型名。

## 测试

```bash
.venv/Scripts/python -m pytest tests/ -q
```

含地图连通性、内容 schema 校验、投放表覆盖、合成键盘事件的完整输入管线集成测试。

## 项目结构

```
main.py            入口与主循环          actions.py        回合动作
engine.py          引擎与回合推进        input_handlers.py 键位映射与输入模式
game_map.py        瓦片/FOV/实体查询     procgen.py        房间走廊地牢生成
entity.py          Entity/Actor/Item     base_component.py 组件基类
fighter.py         战斗组件              ai.py             敌人 AI（注册表）
consumable.py      物品效果（注册表）     inventory.py      行囊
level.py           修为升级              content_loader.py JSON→实体工厂与校验
render.py          渲染（地图/HUD/菜单） message_log.py    消息日志
tile_types.py      瓦片定义              paths.py          打包资源路径
assets/            中文像素字体（OFL）   data/content/     全部内容数据
```

## 字体版权

`assets/font.ttf` 为[融合像素字体](https://github.com/TakWolf/fusion-pixel-font)（12px proportional zh_hans），依 SIL Open Font License 1.1 授权，可随本程序再分发，协议全文见 `assets/font-OFL.txt`。

## 已知技术债

- tcod 21 对 `EventDispatch` 标记了弃用告警（建议迁移 Protocol），功能不受影响
- 行囊暂无"丢弃"操作；死亡不掉落物品
