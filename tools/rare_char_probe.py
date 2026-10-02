"""生僻字覆盖检查：对比字体 cmap 与山海经常用生僻字/卦符等字符集。"""

from __future__ import annotations

import sys
from pathlib import Path

from fontTools.ttLib import TTFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from paths import resource_path  # noqa: E402

GROUPS = {
    "游戏现用字": "狌彘蛊雕九尾狐行者灵芝五雷符山海行修为气血尸骸陨落转世",
    "山海经常见异兽名": "夔魑魅魍魉窫窳猰貐凿齿饕餮穷奇梼杌混沌毕方鲲鹏烛阴相柳应龙英招陆吾帝江九婴祸斗",
    "描述性生僻字": "鬣鬃角喙爪鳞甲羽翼骨血皮毛咆哮吼嘶鸣啼猿狙猱玃豺貙罴熊罴兕虎豹犀象麋麈驼鹿豕彘豚",
    "周易相关": "乾坤坎离震巽艮兑卦爻阴阳太极太极☯☰☱☲☳☴☵☶☷𰀁𰀁",
    "CJK 扩展A": "䍶䑏㺤㟙㺢㺪㯶",
    "CJK 扩展B": "𤝱𧴪𩣎𪺣𫆏",
    "GB常用字对照": "的一是了我不人在他有这上们来到时大地为子中你说生国年着就那和要她出也得里后自以会家可下而过天去能对小多然于心学么之都好看起发当没成只如事把还用第样道想作种开",
    "全角符号": "·！？：；、。（）《》【】—…",
}


def coverage(font_path: Path) -> tuple[dict[str, list[str]], int]:
    font = TTFont(str(font_path), fontNumber=0)
    cmap = set()
    for table in font["cmap"].tables:
        if table.isUnicode():
            cmap.update(table.cmap.keys())
    report: dict[str, list[str]] = {}
    for group_name, chars in GROUPS.items():
        missing = []
        seen = set()
        for ch in chars:
            if ch in seen:
                continue
            seen.add(ch)
            if ord(ch) not in cmap:
                missing.append(f"{ch}(U+{ord(ch):04X})")
        report[group_name] = missing
    return report, len(cmap)


def main() -> None:
    fonts = {
        "游戏字体（融合像素 12px zh_hans）": resource_path("assets/font.ttf"),
        "系统黑体（simhei，回退用）": Path("C:/Windows/Fonts/simhei.ttf"),
    }
    for name, path in fonts.items():
        if not path.exists():
            print(f"[跳过] {name}: 文件不存在 {path}")
            continue
        report, total = coverage(path)
        print(f"\n===== {name}（cmap 共 {total} 字） =====")
        for group_name, missing in report.items():
            status = "全覆盖" if not missing else f"缺 {len(missing)} 字: {' '.join(missing)}" + (
                " ……（截断）" if len(missing) > 15 else ""
            )
            print(f"  {group_name}: {status}")


if __name__ == "__main__":
    main()
