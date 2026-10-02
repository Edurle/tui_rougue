# 山海行 — 字符 Roguelike

以《山海经》异兽为对手的终端风地牢探索游戏。Python + [python-tcod](https://github.com/libtcod/python-tcod)（libtcod）渲染字符画面，**全部内容数值由 JSON 数据驱动**，为后续国风内容内核（周易占卜、天工开物合成）预留了扩展位。

**画面风格**：国潮配色（墨底/鎏金/朱砂/青瓷/紫电）× 现代等宽字体（Maple Mono NF CN）× 全套动效（光照脉动、受击闪红震屏、伤害飘字、发现提示、升级粒子、雷击特效）。

## 运行

需要 Python 3.10+：

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt pyinstaller pytest
.venv/Scripts/python main.py
```

或者直接运行打包好的单文件（无需安装 Python）：

```
dist\shanhai_rogue.exe
```

重新打包：双击 `build.bat`（或 `pyinstaller --onefile --name shanhai_rogue --add-data "assets;assets" --add-data "data;data" main.py`）。

## 玩法

以「山川游历」推进：循径深入《山海经》诸卷——南山经→西山经→北山经→东山经→中山经→大荒经，每层一座书中名山（HUD 显示「南山经·招摇之山」），越入大荒越凶险。上楼=循径回返，走过的山完整保留。击杀异兽提升修为，死亡即结束（回车转世重开）。

| 按键 | 功能 |
|---|---|
| 方向键 / WASD / HJKLYUBN（vi 八方向）/ 小键盘 | 移动；走向异兽即攻击 |
| `空格` 或 `.` | 原地等待一回合 |
| `G` 或 `,` | 拾取脚下的物品 |
| `I` | 打开行囊，按字母使用对应物品 |
| `>`（Shift+句号） | 站在金色山径上循径深入（走过的山完整保留） |
| `<`（Shift+逗号） | 站在青色山径上循径回返 |
| `Esc` | 关闭菜单 / 退出游戏 |
| `[` / `]` 或鼠标滚轮 | 回看/返回事件日志历史（采取行动自动回底） |
| `F1` | 循环画面大小（大/中/小：字号+格数，默认大） |
| `F2` | 循环信息板宽度（大/中/小：14/18/22 列，默认大） |

初始行囊为空。灵芝恢复气血，五雷符雷击最近的可见敌人。信息板会按当前处境动态提示可用按键（站上山径提示上下楼、脚下有物提示拾取、气血低且行囊有药提示服用）。击杀获得修为，自动升级（气血上限+8、攻+1、防+1）。

## 多语言

内置 `zh_CN`（简体中文）与 `en_US`（英文），发布 exe 会**自动跟随系统语言**，也可强制指定：

```
python main.py --lang en_US        # 或 zh_CN
shanhai_rogue.exe --lang en_US
```

- 文案：`data/content/strings/{语言}.json`，新增语言 = 加一个同结构文件
- 实体名/典故：monsters.json / items.json / player.json 中 `name`/`lore` 写成 `{"zh_CN": …, "en_US": …}`（纯字符串 = 所有语言同值；缺失语言自动回退 zh_CN）
- 语言列表在 `content_loader.py` 的 `SUPPORTED_LANGS` 登记

## 修改与扩展内容（不用改代码）

所有内容在 `data/content/`：

- **monsters.json** — 异兽定义（字符、颜色、战斗数值、AI 类型、tags、出处卷目、多语言名）
- **regions.json** — 山川游历区域表（楼层区间→经卷→山中名序列）
- **items.json** — 物品与效果
- **spawn_tables.json** — 各层投放权重与数量（难度曲线）
- **player.json** — 玩家初始属性、升级加成、行囊容量
- **strings/** — 各语言文案模板（整体润色只动这里）
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

## 画面系统

- **国潮配色**：墨底 / 鎏金墙线框 / 朱砂 HUD / 青瓷地板 / 紫电雷法，全部在 `data/content/theme.json`，换肤=复制改色值
- **动效**（`effects.py`，参数在 theme 的 `effects` 节）：帧循环 60fps；光照呼吸脉动；玩家受击闪红+震屏；伤害/治疗/雷击飘字；怪物发现你的 `!` 提示；升级八向金色粒子；拾取闪光
- **邻接墙**：墙体按四邻居自动选择 ─│└┌┐┘├┤┬┴┼ 制表符，鎏金线框结构（16 种 bitmask 查表，`game_map.py`）
- **光照衰减**：视野内 3 格全亮、向外线性渐暗（`theme.json` 的 `lighting`）
- **彩色图块**：特殊实体用程序生成的图块（白色形状 + fg 调制，光照/配色自动生效）——五雷符、灵芝、尸骸、发光楼梯；JSON 加 `"art": "图块名"` 即启用，新图块在 `tileset_art.py` 注册表加生成函数
- **消息分色**：13 种语义类型（combat/heal/warn/loot/levelup…）自动着色
- **生僻字自动回退**：启动时检查内容字符的字体覆盖，缺字自动从系统字体注入（`font_fallback.py`）
- 渲染管线向量化（numpy 批量写 console.rgb）

## 字体与显示

- 主字体 **Maple Mono NF CN**（现代等宽 + Nerd 图标，OFL 授权，实测 CJK 宽高比正常）；融合像素字体保留为 `assets/font-fusion.ttf`，想换回把 `main.py` 的 FALLBACK_FONTS 顺序对调即可

- `assets/font.ttf` 为[融合像素字体](https://github.com/TakWolf/fusion-pixel-font)（12px proportional zh_hans），依 SIL Open Font License 1.1 授权，可随本程序再分发，协议全文见 `assets/font-OFL.txt`
- 显示设置两档独立（F1/F2 游戏内切换，持久化到 settings.json，当前默认均为**大**）：
  - **画面**（字号+格数，窗口像素基本不变）：大 48px/40×22，中 36px/53×29，小 28px/68×37
  - **信息板**（占列数）：大 14 列 / 中 18 列 / 小 22 列，地图相应让列
- 布局 = 地图 + 金线分隔 + 右侧信息板（属性区/气血条/事件日志）；也可用 `--map`/`--sidebar` 参数指定档位启动
- 呈现时启用 `keep_aspect + integer_scaling`：窗口任意拉伸/最大化都按整数倍缩放，**不会发糊**（不足一倍的余量留黑边）

## 已知技术债

- tcod 21 对 `EventDispatch` 标记了弃用告警（建议迁移 Protocol），功能不受影响
- 行囊暂无"丢弃"操作；死亡不掉落物品
