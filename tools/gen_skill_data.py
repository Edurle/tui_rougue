"""一次性数据生成脚本：从交接文档定稿表生成 classes.json + skills.json。

用法：./.venv/Scripts/python.exe tools/gen_skill_data.py
生成后跑 pytest 校验（DAG/前置/链首/效果类断言）。
"""

from __future__ import annotations

import json
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "content"

# ---- 10 职业（hp/pow/def/mp，交接文档定稿）----
CLASSES = [
    # id, 中文名, EN, hp, pow, def, mp, 中文简介, EN 简介
    ("leifa", "雷法·方士", "Thunder Adept", 26, 4, 1, 14,
     "役使天雷的方士，杀伐凌厉，气海充盈。",
     "A tactician wielding heaven's thunder; devastating and deep of breath."),
    ("jianke", "剑客", "Sword Saint", 34, 6, 2, 8,
     "以剑证道的游侠，气血雄厚，攻守兼备。",
     "A wandering sword saint; hardy, balanced in blade and guard."),
    ("wuzhu", "巫祝", "Shaman", 30, 4, 1, 12,
     "沟通山川精魅的巫祝，能医能蛊。",
     "A shaman who bargains with spirits; heals as readily as hexes."),
    ("yishe", "羿射", "Archer", 28, 6, 1, 10,
     "承羿之风的射手，箭出如虹。",
     "An archer of Yi's lineage; arrows fly like falling suns."),
    ("kuafu", "夸父裔", "Kuafa Kin", 42, 5, 3, 8,
     "逐日巨人的后裔，筋骨如铁。",
     "Descendant of the sun-chaser; sinew like iron."),
    ("yingwei", "影卫", "Shadow Guard", 26, 8, 0, 10,
     "藏身于影的卫士，一击致命。",
     "A guard of shadows; one strike, one death."),
    ("gushi", "蛊师", "Gu Master", 28, 4, 1, 14,
     "豢养百蛊的驭毒者，缠绵致命。",
     "A breeder of hundred gu; a slow, certain death."),
    ("yushou", "御兽师", "Beast Caller", 30, 4, 1, 12,
     "与百兽立契的驭者，呼朋引伴。",
     "A caller bonded with beasts; never fights alone."),
    ("fushi", "符师", "Sigil Adept", 26, 4, 1, 16,
     "以符箓载道的术士，气脉绵长。",
     "A scribe of sigils; endless breath, endless fire."),
    ("yueshi", "乐师", "Musician", 28, 3, 2, 14,
     "以音律扰神夺魄的乐师。",
     "A musician whose notes unravel the mind."),
]

# ---- 80 技能（每职业 8 个；req 用中文名便于对照，脚本内翻译为 id）----
# 条目格式：(中文名, EN 名, 中文描述, EN 描述, tags, mp, cost, req[中文技能名], effect dict)
SKILLS = {
    "leifa": [
        ("掌心雷", "Palm Thunder", "掌中引雷，轰击眼前之敌。", "Thunder crackles in your palm, striking the foe before you.",
         ["thunder"], 4, 1, [], {"type": "damage_nearest", "power": 6, "scale": 1.5, "hits": 1}),
        ("疾风步", "Gale Step", "身随风向，倏忽数丈。", "Ride the wind; blink across the tiles.",
         ["move"], 3, 1, [], {"type": "teleport_step", "range": 3}),
        ("雷池", "Thunder Pool", "以身为池，雷走四邻。", "A pool of thunder spills to every neighbouring tile.",
         ["thunder", "aoe"], 6, 1, ["掌心雷"], {"type": "damage_aoe_self", "radius": 1, "power": 5, "scale": 1}),
        ("引雷符", "Bolt Sigil", "符引天雷，力贯双臂。", "A sigil that channels sky-force into your arms.",
         ["buff"], 5, 1, [], {"type": "buff_power", "amount": 2, "turns": 12}),
        ("金光咒", "Gold Light Ward", "金光护体，刀兵不侵。", "Golden light sheathes you against blade and claw.",
         ["buff"], 5, 1, ["引雷符"], {"type": "buff_defense", "amount": 3, "turns": 12}),
        ("雷遁", "Thunder Blink", "化雷而行，其疾如电。", "Become the bolt itself.",
         ["move"], 5, 1, ["疾风步"], {"type": "teleport_step", "range": 6}),
        ("天雷破", "Skyfall Bolt", "一雷破空，妖邪辟易。", "A single bolt splits the sky.",
         ["thunder"], 10, 1, ["雷池"], {"type": "damage_nearest", "power": 12, "scale": 2.5, "hits": 1}),
        ("万雷引", "Myriad Bolts", "万雷齐落，方圆俱寂。", "Ten thousand bolts fall at once.",
         ["thunder", "aoe"], 18, 2, ["天雷破"], {"type": "damage_aoe_self", "radius": 4, "power": 10, "scale": 2}),
    ],
    "jianke": [
        ("斩铁", "Iron Cleaver", "一剑之下，铁石俱断。", "One stroke shears iron and stone alike.",
         [], 3, 1, [], {"type": "damage_nearest", "power": 8, "scale": 2, "hits": 1}),
        ("剑罡", "Sword Aura", "罡气外放，伤及周身。", "Sword-aura spills outward, wounding all around.",
         ["aoe"], 5, 1, [], {"type": "damage_aoe_self", "radius": 1, "power": 5, "scale": 1}),
        ("瞬步", "Flash Step", "步随身动，瞬息即至。", "A single breath, a single step.",
         ["move"], 3, 1, [], {"type": "teleport_step", "range": 3}),
        ("裂空斩", "Sky-Rending Cut", "剑气裂空，无可阻挡。", "A cut that rends the very air.",
         [], 8, 1, ["斩铁"], {"type": "damage_nearest", "power": 14, "scale": 3, "hits": 1}),
        ("铁骨咒", "Ironbone Ward", "咒固筋骨，坚如铁石。", "A ward that tempers bone to iron.",
         ["buff"], 5, 1, [], {"type": "buff_defense", "amount": 4, "turns": 12}),
        ("剑气长河", "Sword River", "剑气如河，奔涌不休。", "Sword-aura flows like an unending river.",
         ["aoe"], 10, 1, ["剑罡"], {"type": "damage_aoe_self", "radius": 1.5, "power": 8, "scale": 1.5}),
        ("无我", "Selfless Blade", "忘我而剑，其锋愈锐。", "Forget the self; the blade sharpens.",
         ["buff"], 8, 1, ["铁骨咒"], {"type": "buff_power", "amount": 4, "turns": 12}),
        ("人剑合一", "Blade Unity", "人剑合一，剑气纵横十步。", "Sword and wielder become one; aura sweeps ten paces.",
         ["aoe"], 18, 2, ["剑气长河"], {"type": "damage_aoe_self", "radius": 4, "power": 12, "scale": 2.5}),
    ],
    "wuzhu": [
        ("荆棘刺", "Thorn Sting", "巫术化刺，刺骨蚀心。", "A shaman's thorn that bites to the bone.",
         [], 3, 1, [], {"type": "damage_nearest", "power": 5, "scale": 1.5, "hits": 1}),
        ("蚀心蛊", "Heart-Gnaw Gu", "蛊虫入体，蚀心腐骨。", "A gu that gnaws the heart and rots the bones.",
         ["poison"], 5, 1, ["荆棘刺"], {"type": "poison_dot", "damage": 3, "scale": 1, "turns": 6}),
        ("回春术", "Vernal Rite", "咒起回春，伤者自愈。", "A rite that calls spring back into flesh.",
         ["heal"], 5, 1, [], {"type": "heal_self", "amount": 8, "scale": 2}),
        ("万棘阵", "Thorn Field", "荆棘蔓生，遍地锋芒。", "Thorns erupt across the field.",
         ["aoe"], 8, 1, ["荆棘刺"], {"type": "damage_aoe_self", "radius": 1.5, "power": 6, "scale": 1.5}),
        ("石肤咒", "Stoneskin Ward", "咒化肌肤，坚若磐石。", "Skin turns to living stone.",
         ["buff"], 5, 1, [], {"type": "buff_defense", "amount": 3, "turns": 12}),
        ("血祭", "Blood Offering", "以血为祭，力灌一击。", "Pay in blood; strike with all you have.",
         [], 0, 1, ["万棘阵"], {"type": "damage_nearest", "power": 16, "scale": 3, "hits": 1, "hp_cost": 6}),
        ("巫蛊滔天", "Gu Tide", "蛊如潮涌，毒浸八方。", "A tide of gu drowns the eight directions.",
         ["poison", "aoe"], 12, 1, ["蚀心蛊"], {"type": "damage_aoe_self", "radius": 1.5, "power": 7, "scale": 1.5, "poison": [2, 4]}),
        ("青丘仙泽", "Qingiu Blessing", "仙泽沛然，疗伤破敌。", "A blessed spring heals you and scours your foes.",
         ["heal"], 14, 2, ["回春术"], {"type": "heal_self", "amount": 20, "scale": 3, "aoe_radius": 1, "aoe_power": 4}),
    ],
    "yishe": [
        ("射日箭", "Sunshot Arrow", "一箭既出，如日坠空。", "One arrow, like a falling sun.",
         [], 3, 1, [], {"type": "damage_nearest", "power": 7, "scale": 2, "hits": 1}),
        ("鹰目", "Hawk Eye", "目若鹰隼，箭无虚发。", "Eyes of a hawk; no arrow flies true.",
         ["buff"], 4, 1, [], {"type": "buff_power", "amount": 2, "turns": 15}),
        ("连珠矢", "Stringed Arrows", "箭如连珠，三矢连发。", "Arrows like strung beads; three in a breath.",
         [], 6, 1, ["射日箭"], {"type": "damage_nearest", "power": 5, "scale": 1, "hits": 3}),
        ("贯虹矢", "Rainbow Piercer", "一矢贯虹，破甲穿云。", "An arrow that pierces rainbow and mail alike.",
         [], 8, 1, ["连珠矢"], {"type": "damage_nearest", "power": 13, "scale": 3, "hits": 1}),
        ("风行步", "Windwalk", "御风而行，其疾如风。", "Walk the wind.",
         ["move"], 3, 1, [], {"type": "teleport_step", "range": 4}),
        ("箭雨", "Arrow Rain", "仰天抛射，箭落如雨。", "Arrows loosed skyward fall as rain.",
         ["aoe"], 9, 1, ["贯虹矢"], {"type": "damage_aoe_self", "radius": 1.5, "power": 6, "scale": 1.5}),
        ("破军矢", "Army-Breaker", "一矢破军，锐不可当。", "One arrow to break an army.",
         [], 12, 1, ["箭雨"], {"type": "damage_nearest", "power": 18, "scale": 4, "hits": 1}),
        ("落日弓", "Setting-Sun Bow", "挽弓如月，落日千里。", "Draw the bow like a moon; the sun falls a thousand li.",
         ["aoe"], 18, 2, ["破军矢"], {"type": "damage_aoe_self", "radius": 4, "power": 11, "scale": 2.5}),
    ],
    "kuafu": [
        ("巨力震", "Titan Quake", "巨力跺地，震伤四邻。", "A titan's stomp shudders the ground.",
         ["aoe"], 4, 1, [], {"type": "damage_aoe_self", "radius": 1, "power": 6, "scale": 1.5}),
        ("踏山", "Mountain Stride", "一步踏山，越过丘壑。", "Stride over hills and hollows.",
         ["move"], 2, 1, [], {"type": "teleport_step", "range": 2}),
        ("不坏身", "Unbreaking Body", "肉身如山，不坏不摧。", "A body like the mountain itself.",
         ["buff"], 6, 1, [], {"type": "buff_defense", "amount": 5, "turns": 15}),
        ("拽山掷", "Hurl Peak", "拔山而掷，砸落敌身。", "Uproot a peak and hurl it.",
         [], 7, 1, ["巨力震"], {"type": "damage_nearest", "power": 12, "scale": 2.5, "hits": 1}),
        ("巨灵碾压", "Titan Crush", "巨灵临世，碾碎八方。", "A titan's tread crushes all around.",
         ["aoe"], 10, 1, ["拽山掷"], {"type": "damage_aoe_self", "radius": 1.5, "power": 8, "scale": 2}),
        ("逐日", "Sun-Chase", "追日之志，力贯周身。", "The will that chased the sun fills your limbs.",
         ["buff"], 6, 1, ["不坏身"], {"type": "buff_power", "amount": 3, "turns": 15}),
        ("山河撼", "Land Shaker", "撼动山河，群敌失据。", "Mountains and rivers shake; foes lose their footing.",
         ["stun"], 12, 1, ["巨灵碾压"], {"type": "stun_aoe", "turns": 2, "radius": 1.5, "power": 6, "scale": 1}),
        ("逐日怒", "Sun-Chaser's Wrath", "怒火燎原，山河变色。", "Wrath spreads like wildfire; the land changes colour.",
         ["aoe"], 18, 2, ["山河撼"], {"type": "damage_aoe_self", "radius": 4, "power": 13, "scale": 3}),
    ],
    "yingwei": [
        ("蚀骨刺", "Bone-Etch Sting", "暗刺蚀骨，痛入骨髓。", "A hidden sting that etches the bone.",
         [], 3, 1, [], {"type": "damage_nearest", "power": 7, "scale": 2, "hits": 1}),
        ("影遁", "Shadow Slip", "没入阴影，无声无息。", "Melt into shadow without a sound.",
         ["move"], 2, 1, [], {"type": "teleport_step", "range": 3}),
        ("连诛", "Serial Kills", "连番出手，诛敌于隙。", "Strike again and again through the gaps.",
         [], 6, 1, ["蚀骨刺"], {"type": "damage_nearest", "power": 5, "scale": 1, "hits": 3}),
        ("背袭", "Backstab", "自影中出，一击致命。", "From the shadow behind: one killing blow.",
         [], 8, 1, ["连诛"], {"type": "damage_nearest", "power": 15, "scale": 3, "hits": 1}),
        ("雾隐", "Mist Veil", "雾隐其身，刀剑难加。", "A veil of mist turns blows aside.",
         ["buff"], 4, 1, [], {"type": "buff_defense", "amount": 3, "turns": 10}),
        ("影刃乱舞", "Shadow Blade Dance", "影刃齐出，乱舞伤敌。", "Shadow-blades dance and wound.",
         ["aoe"], 9, 1, ["背袭"], {"type": "damage_aoe_self", "radius": 1, "power": 7, "scale": 1.5}),
        ("绝命刺", "Death Thrust", "以命换命，刺出绝境。", "Trade blood for the killing thrust.",
         [], 10, 1, ["影刃乱舞"], {"type": "damage_nearest", "power": 20, "scale": 4, "hits": 1, "hp_cost": 4}),
        ("影分身", "Shadow Split", "分身千百，刃影重重。", "A hundred shadows, a hundred blades.",
         ["aoe"], 16, 2, ["绝命刺"], {"type": "damage_aoe_self", "radius": 2, "power": 9, "scale": 2}),
    ],
    "gushi": [
        ("蚀骨蛊", "Bone-Gnaw Gu", "蛊蚀其骨，昼夜不息。", "A gu that gnaws the bone day and night.",
         ["poison"], 4, 1, [], {"type": "poison_dot", "damage": 3, "scale": 1, "turns": 5}),
        ("瘴云", "Miasma Cloud", "瘴云漫卷，毒浸群敌。", "A miasmal cloud poisons the crowd.",
         ["poison", "aoe"], 6, 1, ["蚀骨蛊"], {"type": "damage_aoe_self", "radius": 1, "power": 4, "scale": 1, "poison": [2, 3]}),
        ("驱虫咬", "Swarm Bite", "驱虫成群，啮敌要害。", "Drive the swarm to gnaw vitals.",
         [], 3, 1, [], {"type": "damage_nearest", "power": 6, "scale": 2, "hits": 1}),
        ("蛊毒引爆", "Gu Detonation", "蛊毒积于敌身，一瞬引爆。", "Gu venom pools in the foe — then detonates.",
         ["poison"], 8, 1, ["蚀骨蛊"], {"type": "damage_nearest", "power": 10, "scale": 2.5, "hits": 1}),
        ("蛊甲", "Gu Carapace", "蛊虫结甲，附体护身。", "Gu weave a carapace over your skin.",
         ["buff"], 5, 1, [], {"type": "buff_defense", "amount": 3, "turns": 12}),
        ("万蛊噬心", "Myriad Gu Feast", "万蛊噬心，痛不欲生。", "Ten thousand gu feast upon the heart.",
         ["poison"], 12, 1, ["蛊毒引爆"], {"type": "poison_dot", "damage": 5, "scale": 1, "turns": 8}),
        ("毒龙钻", "Venom Drake Drill", "毒聚如龙，钻心裂肺。", "Venom gathers into a drake that drills the heart.",
         ["poison"], 10, 1, ["驱虫咬"], {"type": "damage_nearest", "power": 12, "scale": 3, "hits": 1, "poison": [3, 4]}),
        ("蛊神降世", "Gu God Descends", "蛊神临世，毒染山河。", "The gu god descends; venom stains the land.",
         ["poison", "aoe"], 18, 2, ["万蛊噬心"], {"type": "damage_aoe_self", "radius": 4, "power": 9, "scale": 2, "poison": [4, 6]}),
    ],
    "yushou": [
        ("灵犬契约", "Hound Pact", "与灵犬立契，并肩而战。", "Seal a pact; a spirit hound fights at your side.",
         ["summon"], 6, 1, [], {"type": "summon", "duration": 15, "beast_hp": 10, "beast_power": 4,
                                "beast_char": "d", "beast_color": [220, 190, 120],
                                "beast_name": {"zh_CN": "灵犬", "en_US": "Spirit Hound"}}),
        ("犄角冲", "Horn Charge", "兽角前冲，顶翻敌身。", "Charge with beast horns and toss the foe.",
         [], 4, 1, [], {"type": "damage_nearest", "power": 7, "scale": 2, "hits": 1}),
        ("兽魂共鸣", "Beast Resonance", "兽魂共鸣，气力大增。", "Your beast's soul resonates; strength swells.",
         ["buff"], 5, 1, [], {"type": "buff_power", "amount": 3, "turns": 15}),
        ("狼群啸", "Wolf Howl", "长啸引狼，撕咬群敌。", "A howl summons wolves that tear the crowd.",
         ["aoe"], 8, 1, ["灵犬契约"], {"type": "damage_aoe_self", "radius": 1, "power": 5, "scale": 1}),
        ("灵犀", "Beast Empathy", "以灵犀之意，抚平伤势。", "Beast empathy knits your wounds.",
         ["heal"], 6, 1, ["灵犬契约"], {"type": "heal_self", "amount": 10, "scale": 2}),
        ("白泽啸", "Baize Roar", "白泽长啸，群敌震惶。", "The baize roars; the crowd freezes in terror.",
         ["stun"], 10, 1, ["狼群啸"], {"type": "stun_aoe", "turns": 1, "radius": 1.5, "power": 5, "scale": 1}),
        ("巨熊击", "Great Bear Blow", "巨熊挥爪，一击千钧。", "A great bear's swipe, heavy as a mountain.",
         [], 9, 1, ["犄角冲"], {"type": "damage_nearest", "power": 14, "scale": 3, "hits": 1}),
        ("白泽临", "Baize Descends", "白泽神兽，应召临世。", "The divine baize answers your call.",
         ["summon"], 18, 2, ["白泽啸"], {"type": "summon", "duration": 20, "beast_hp": 18, "beast_power": 8,
                                        "beast_char": "Z", "beast_color": [240, 240, 250],
                                        "beast_name": {"zh_CN": "白泽", "en_US": "Baize"}}),
    ],
    "fushi": [
        ("火符", "Fire Sigil", "祭出火符，焚灼敌身。", "A fire sigil sears the foe.",
         ["fire"], 3, 1, [], {"type": "damage_nearest", "power": 6, "scale": 2, "hits": 1}),
        ("符甲", "Sigil Harness", "符箓护体，坚不可摧。", "Sigils plate your body.",
         ["buff"], 4, 1, [], {"type": "buff_defense", "amount": 3, "turns": 12}),
        ("连珠符", "Stringed Sigils", "符如连珠，接连轰落。", "Sigils fall like strung beads.",
         [], 6, 1, ["火符"], {"type": "damage_nearest", "power": 5, "scale": 1, "hits": 3}),
        ("三昧符", "Samadhi Sigil", "三昧真火，焚尽四邻。", "Samadhi fire scorches every neighbour.",
         ["fire", "aoe"], 8, 1, ["火符"], {"type": "damage_aoe_self", "radius": 1, "power": 7, "scale": 1.5}),
        ("遁地符", "Earth-Sink Sigil", "化符入地，遁行无碍。", "Sink with the sigil into the earth.",
         ["move"], 4, 1, [], {"type": "teleport_step", "range": 5}),
        ("火龙符", "Fire Drake Sigil", "火龙腾空，扑噬敌身。", "A fire drake leaps to engulf the foe.",
         ["fire"], 10, 1, ["三昧符"], {"type": "damage_nearest", "power": 13, "scale": 3, "hits": 1}),
        ("镇魂符", "Soul-Pin Sigil", "符镇其魂，动弹不得。", "The sigil pins the soul; the body cannot move.",
         ["stun"], 10, 1, ["符甲"], {"type": "stun_aoe", "turns": 2, "radius": 1, "power": 0, "scale": 0}),
        ("天火符", "Heaven Fire Sigil", "天火焚野，无所遁形。", "Heaven's fire scorches the field bare.",
         ["fire", "aoe"], 18, 2, ["火龙符"], {"type": "damage_aoe_self", "radius": 4, "power": 11, "scale": 2.5}),
    ],
    "yueshi": [
        ("音刃", "Sound Blade", "凝音为刃，割裂敌身。", "Sound condenses into a cutting edge.",
         [], 3, 1, [], {"type": "damage_nearest", "power": 5, "scale": 2, "hits": 1}),
        ("清心曲", "Clear-Heart Tune", "一曲清心，真气回涌。", "A tune that stills the heart; breath returns.",
         [], 0, 1, [], {"type": "mp_restore", "amount": 6}),
        ("裂帛音", "Silk-Tearing Note", "裂帛之音，震伤四邻。", "A note like tearing silk wounds all around.",
         ["aoe"], 6, 1, ["音刃"], {"type": "damage_aoe_self", "radius": 1, "power": 6, "scale": 1.5}),
        ("迷魂音", "Soul-Befuddling Note", "靡音入耳，神魂俱迷。", "The note unsettles; the mind wanders loose.",
         ["stun"], 6, 1, ["裂帛音"], {"type": "stun_aoe", "turns": 1, "radius": 1, "power": 0, "scale": 0}),
        ("绕梁", "Lingering Note", "余音绕梁，蚀骨不休。", "The note lingers, gnawing without end.",
         ["poison"], 6, 1, ["音刃"], {"type": "poison_dot", "damage": 3, "scale": 1, "turns": 6}),
        ("变徵", "Zhi Variation", "变徵之声，慷慨激昂。", "The zhi note rises; strength kindles.",
         ["buff"], 6, 1, ["清心曲"], {"type": "buff_power", "amount": 3, "turns": 15}),
        ("破阵曲", "Array-Breaking Tune", "一曲破阵，锐不可当。", "One tune scatters the formation.",
         ["aoe"], 12, 1, ["裂帛音"], {"type": "damage_aoe_self", "radius": 1.5, "power": 9, "scale": 2}),
        ("广陵散", "Guangling San", "广陵一散，绝响夺魂。", "The last performance; the note claims souls.",
         ["aoe", "stun"], 18, 2, ["破阵曲"], {"type": "damage_aoe_self", "radius": 4, "power": 10, "scale": 2.5, "stun": 1}),
    ],
}


def build() -> None:
    classes = {
        cid: {
            "name": {"zh_CN": zh, "en_US": en},
            "desc": {"zh_CN": d_zh, "en_US": d_en},
            "hp": hp,
            "power": pow_,
            "defense": dfn,
            "mp": mp,
        }
        for cid, zh, en, hp, pow_, dfn, mp, d_zh, d_en in CLASSES
    }

    # 中文名 → 技能 id 映射（req 翻译用；同职业内唯一）
    name_to_id: dict[tuple[str, str], str] = {}
    for class_id, skills in SKILLS.items():
        for slot, entry in enumerate(skills, start=1):
            name_to_id[(class_id, entry[0])] = f"s_{class_id}_{slot}"

    skills_json = {}
    for class_id, skills in SKILLS.items():
        assert len(skills) == 8, f"{class_id} 技能数应为 8"
        for slot, (zh, en, d_zh, d_en, tags, mp, cost, req, effect) in enumerate(skills, start=1):
            sid = f"s_{class_id}_{slot}"
            requires = [name_to_id[(class_id, r)] for r in req]
            skills_json[sid] = {
                "class": class_id,
                "slot": slot,
                "name": {"zh_CN": zh, "en_US": en},
                "desc": {"zh_CN": d_zh, "en_US": d_en},
                "tags": tags,
                "mp": mp,
                "cost": cost,
                "requires": requires,
                "effect": effect,
            }

    OUT_DIR.joinpath("classes.json").write_text(
        json.dumps(classes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    OUT_DIR.joinpath("skills.json").write_text(
        json.dumps(skills_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"生成 {len(classes)} 职业 / {len(skills_json)} 技能 → {OUT_DIR}")


if __name__ == "__main__":
    build()
