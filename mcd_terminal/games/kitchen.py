"""The real data behind the menu games: this store's menu, your coupons, points and the points mall.

Loaded once per game; every combination the games try is then priced by the same engine as
`mcd order` (plan_order), so a game's "you'd pay ¥X" is exactly what ordering would cost.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from ..order import MenuItem, OrderPlan, Unit, plan_order

REELS = {
    "main": ("主食", ("堡", "巨无霸", "满分", "卷", "鸡排")),
    "side": ("小食", ("薯", "麦乐鸡", "鸡块", "鸡翅", "玉米", "派", "脆汁鸡", "薯饼")),
    "drink": ("饮料", ("可乐", "雪碧", "拿铁", "美式", "咖啡", "奶铁", "茶", "汁", "奶", "豆浆")),
    "sweet": ("甜品", ("冰淇淋", "麦旋风", "新地", "圆筒", "甜筒")),
}


def reel_of(name: str) -> str | None:
    if "套餐" in name or "桶" in name:
        return None
    for key, (_, words) in REELS.items():
        if any(w in name for w in words):
            return key
    return None


@dataclass
class Kitchen:
    scene: Any
    menu: list[MenuItem]
    owned: list[Any]
    mall: list[Any]
    budget: int
    kcal: dict[str, int]

    def plan(self, items: list[MenuItem]) -> OrderPlan:
        return plan_order([Unit(m.name, m) for m in items], self.owned, self.mall, self.budget)

    def kcal_of(self, items: list[MenuItem]) -> int | None:
        vals = [self.kcal.get(m.name) for m in items]
        return sum(v for v in vals if v) if any(vals) else None

    def reel(self, key: str) -> list[MenuItem]:
        return [m for m in self.menu if m.price_fen > 0 and reel_of(m.name) == key]

    def roll(self, rng: random.Random, keys: list[str], max_pay: int | None = None,
             max_kcal: int | None = None, tries: int = 400) -> tuple[list[MenuItem], OrderPlan] | None:
        """A random combo (one per reel) that fits the budget / calorie cap after coupons and points."""
        reels = [self.reel(k) for k in keys]
        reels = [r for r in reels if r]
        if not reels:
            return None
        best = None
        for _ in range(tries):
            pick = [rng.choice(r) for r in reels]
            p = self.plan(pick)
            k = self.kcal_of(pick)
            if (max_pay is None or p.pay_fen <= max_pay) and (max_kcal is None or k is None or k <= max_kcal):
                return pick, p
            if best is None or p.pay_fen < best[1].pay_fen:
                best = (pick, p)
        return None if (max_pay is not None or max_kcal is not None) else best


def load(client: Any, prefs: Any, mode: str | None = None) -> Kitchen:
    from .. import render as ui
    from ..content import find_nutrition, parse_nutrition
    from ..ordering import load_menu, mall_options, owned_coupons, pick_scene
    from ..valuation import Account

    scene = pick_scene(client, prefs, mode or prefs.get("mode") or "pickup", None, None, None, None, None, 1)
    menu = load_menu(client, scene)
    pool = [Unit(m.name, m) for m in menu if reel_of(m.name)]
    owned, _ = owned_coupons(client, scene, pool, menu)
    acct = Account.from_payload(ui.call(client, "query-my-account", summary=lambda d: "看看积分"))
    mall = mall_options(client, pool, menu) if acct.available > 0 else []
    if scene.mode in ("delivery", "group"):
        mall = [m for m in mall if not m.in_store_only]
    try:
        table = parse_nutrition(client.call("list-nutrition-foods"))
    except Exception:
        table = []
    kcal = {}
    for m in menu:
        n = find_nutrition(m.name, table) if table else None
        if n:
            kcal[m.name] = int(n.kcal)
    return Kitchen(scene, menu, owned, mall, acct.available, kcal)
