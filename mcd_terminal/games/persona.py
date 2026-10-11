"""麦麦人格：6 道题测出你是哪种麦门信徒，附一份本命套餐。和网页版同一套题。"""
from __future__ import annotations

# key: (name, art, description, signature order keywords)
PERSONAS = {
    "breakfast": ("早餐战神", "breakfast", "七点的猪柳蛋麦满分是你的闹钟，早餐时段结束前从不迟到。", ["满分", "美式", "薯饼"]),
    "night": ("夜宵游侠", "burger", "城市睡了你还醒着，深夜的巨无霸最懂你。", ["巨无霸", "薯条", "可乐"]),
    "sweet": ("甜品星人", "icecream", "正餐只是甜品的前奏，第二个胃永远为麦旋风留着。", ["麦旋风", "冰淇淋", "派"]),
    "coffee": ("咖啡续命官", "coffee", "没有拿铁的上午不算开始，你的血液里流着浓缩。", ["拿铁", "美式", "派"]),
    "chicken": ("炸鸡猎人", "chicken", "鸡翅、麦乐鸡、脆汁鸡，你对酥脆的追求从不妥协。", ["鸡翅", "麦乐鸡", "可乐"]),
    "saver": ("省钱大师", "ticket", "券叠券、积分换券，你点的每一单都是一道最优化题。", ["巨无霸", "薯条", "拿铁"]),
}

QUESTIONS = [
    ("周末你几点吃第一口麦当劳？", [("早上 8 点", "breakfast"), ("下午 3 点", "sweet"), ("晚上 11 点", "night"), ("看券什么时候能用", "saver")]),
    ("点单时你先看哪一栏？", [("小食", "chicken"), ("甜品", "sweet"), ("咖啡", "coffee"), ("我的券", "saver")]),
    ("薯条你怎么吃？", [("蘸麦旋风", "sweet"), ("配可乐趁热吃", "night"), ("留着最后吃", "breakfast"), ("只吃券里送的", "saver")]),
    ("朋友约你去麦当劳，你会说？", [("来杯咖啡续个命", "coffee"), ("鸡翅我包了", "chicken"), ("明早吧，早餐划算", "breakfast"), ("等我算一下怎么最省", "saver")]),
    ("下面哪个最让你心动？", [("新口味麦旋风", "sweet"), ("脆汁鸡回归", "chicken"), ("第二杯半价", "coffee"), ("积分快过期提醒", "saver")]),
    ("你的麦当劳时刻是？", [("加班后的那一份", "night"), ("上班路上的那一杯", "coffee"), ("周末早餐的阳光", "breakfast"), ("和朋友分一桶", "chicken")]),
]


def result(answers: list[str]) -> dict:
    """answers: the persona key of each chosen option. Ties go to the earliest-answered persona."""
    score: dict[str, int] = {}
    for k in answers:
        score[k] = score.get(k, 0) + 1
    top = max(score, key=lambda k: (score[k], -answers.index(k)))
    name, art, desc, wants = PERSONAS[top]
    return {"key": top, "name": name, "art": art, "text": desc, "order": wants,
            "share": f"我的麦麦人格是「{name}」：{desc} 你是哪种？"}


def match_menu(wants: list[str], menu_names: list[str]) -> list[str]:
    """The signature order as real items on this store's menu (skipping combos)."""
    out = []
    for w in wants:
        hit = next((n for n in menu_names if w in n and "套餐" not in n and n not in out), None)
        if hit:
            out.append(hit)
    return out
