"""麦麦签：每天一支，宜、忌和幸运餐品。图个乐。"""
from __future__ import annotations

import random

LOTS = [("上上签", "薯条刚出锅，不用等。"), ("上签", "今天的券都用得上。"), ("上签", "第二份半价会遇到对的人。"),
        ("中签", "冰淇淋机今天心情不错。"), ("中签", "点单前先看一眼快过期的积分。"), ("中签", "早餐时段比你想的结束得早。"),
        ("下签", "番茄酱可能不太够，记得多要一包。"), ("上签", "麦旋风搅得特别匀。")]
YI = ["第二份半价", "用掉快过期的券", "约饭搭子", "尝个新品", "加一份薯条", "早起吃早餐", "清空积分", "给自己点杯咖啡"]
JI = ["空腹开会", "把薯条留到最后", "错过午市", "犹豫不决", "一个人吃全家桶", "忘带取餐码"]


def draw(day: str, menu_names: list[str], salt: str = "") -> dict:
    rng = random.Random(f"fortune:{day}:{salt}")
    lot, text = rng.choice(LOTS)
    names = [n for n in menu_names if "套餐" not in n] or ["薯条"]
    return {"lot": lot, "text": text, "yi": rng.sample(YI, 2), "ji": rng.sample(JI, 2), "lucky": rng.choice(names)}
