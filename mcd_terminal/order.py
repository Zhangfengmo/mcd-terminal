"""Points + cash mixed checkout: pure planning logic (no I/O).

For every unit the user wants to buy we choose one way to pay for it:

- cash at the menu price;
- a coupon already in the account (free to use, each coupon once);
- a points-mall coupon redeemed now (costs points).

Owned coupons are assigned first, best saving first. The remaining units go
through a multiple-choice knapsack over the points budget, which maximises the
cash saved; on ties it spends fewer points.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from math import gcd
from typing import Any, Iterable

from .valuation import MarketItem


# ------------------------------------------------------------------ models
@dataclass
class MenuItem:
    code: str
    name: str
    price_fen: int
    tags: tuple[str, ...] = ()

    @property
    def second_half(self) -> bool:
        """Store promotion like '第二份半价' (applied by calculate-price, not by our estimate)."""
        return any("第二份半价" in t or "第2份半价" in t for t in self.tags)


@dataclass
class OwnedCoupon:
    coupon_id: str
    coupon_code: str
    title: str
    product_code: str
    product_name: str
    price_fen: int | None = None  # what the product costs with this coupon (from calculate-price)
    expires: date | None = None


@dataclass
class Unit:
    """One item the user wants, e.g. the 2nd of '巨无霸x2'."""
    want: str
    menu: MenuItem


@dataclass
class Choice:
    unit: Unit
    kind: str  # "cash" | "coupon" | "points"
    saving_fen: int = 0
    points: int = 0
    coupon: OwnedCoupon | None = None
    mall: MarketItem | None = None

    @property
    def pay_fen(self) -> int:
        return self.unit.menu.price_fen - self.saving_fen


@dataclass
class OrderPlan:
    choices: list[Choice] = field(default_factory=list)
    points_budget: int = 0
    known_coupon_ids: set[str] = field(default_factory=set)  # store coupons seen while planning

    @property
    def original_fen(self) -> int:
        return sum(c.unit.menu.price_fen for c in self.choices)

    @property
    def pay_fen(self) -> int:
        return sum(c.pay_fen for c in self.choices)

    @property
    def saving_fen(self) -> int:
        return sum(c.saving_fen for c in self.choices)

    @property
    def points_used(self) -> int:
        return sum(c.points for c in self.choices)

    def redemptions(self) -> list[tuple[MarketItem, int]]:
        """Mall items to redeem, with counts."""
        counts: dict[int, tuple[MarketItem, int]] = {}
        for c in self.choices:
            if c.kind == "points" and c.mall:
                item, n = counts.get(c.mall.spu_id, (c.mall, 0))
                counts[c.mall.spu_id] = (item, n + 1)
        return list(counts.values())


# ------------------------------------------------------------------ parsing
def yuan_to_fen(v: Any) -> int | None:
    try:
        return int((Decimal(str(v)) * 100).to_integral_value())
    except (InvalidOperation, TypeError, ValueError):
        return None


def parse_menu(data: Any) -> list[MenuItem]:
    """`query-meals` -> menu items with prices (codes appear in `meals`)."""
    if not isinstance(data, dict):
        return []
    meals = data.get("meals") or {}
    tags: dict[str, list[str]] = {}
    for cat in data.get("categories") or []:
        for m in cat.get("meals") or []:
            for t in m.get("tags") or []:
                if t and t not in tags.setdefault(str(m.get("code")), []):
                    tags[str(m.get("code"))].append(str(t))
    out: list[MenuItem] = []
    for code, m in meals.items():
        price = yuan_to_fen((m or {}).get("currentPrice"))
        if m and m.get("name") and price is not None:
            out.append(MenuItem(str(code), m["name"], price, tuple(tags.get(str(code), []))))
    return out


def parse_store_coupons(data: Any) -> list[OwnedCoupon]:
    """`query-store-coupons` -> one OwnedCoupon per (coupon, product)."""
    rows = data if isinstance(data, list) else (data or {}).get("list", []) if isinstance(data, dict) else []
    out: list[OwnedCoupon] = []
    for r in rows:
        dates = re.findall(r"\d{4}-\d{2}-\d{2}", str(r.get("tradeDateTime") or ""))
        expires = datetime.strptime(dates[-1], "%Y-%m-%d").date() if dates else None
        for p in r.get("products") or []:
            out.append(OwnedCoupon(
                coupon_id=str(r.get("couponId", "")), coupon_code=str(r.get("couponCode", "")),
                title=str(r.get("title", "")), product_code=str(p.get("productCode", "")),
                product_name=str(p.get("productName", "")), expires=expires,
            ))
    return out


_QTY = re.compile(r"^(.*?)\s*[*×xX]\s*(\d+)$")
_CN_NUM = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
_QTY_FRONT = re.compile(r"^(\d+|[一两二三四五六七八九十])\s*[份个杯]\s*(.+)$")   # 2份麦乐鸡 / 两杯拿铁
_QTY_BACK = re.compile(r"^(.+?)\s*(\d+|[一两二三四五六七八九十])\s*份$")      # 麦乐鸡2份


def parse_wants(args: Iterable[str]) -> list[tuple[str, int]]:
    """['巨无霸x2', '薯条'] -> [('巨无霸', 2), ('薯条', 1)].

    Quantities: 巨无霸x2 / 巨无霸*2 / 2份巨无霸 / 两份巨无霸 / 巨无霸2份. Piece counts that are part
    of an item's name (麦乐鸡5块) are left alone. `x2` is the one to show people: in zsh an
    unquoted `*` is a glob and fails with "no matches found".
    """
    def num(t: str) -> int:
        return int(t) if t.isdigit() else _CN_NUM[t]

    out: list[tuple[str, int]] = []
    for a in args:
        a = a.strip()
        if not a:
            continue
        if m := _QTY.match(a):
            out.append((m.group(1).strip(), int(m.group(2))))
        elif m := _QTY_FRONT.match(a):
            out.append((m.group(2).strip(), num(m.group(1))))
        elif m := _QTY_BACK.match(a):
            out.append((m.group(1).strip(), num(m.group(2))))
        else:
            out.append((a, 1))
    return [(name, n) for name, n in out if name and n > 0]


# ------------------------------------------------------------------ matching
def _norm(s: str) -> str:
    s = re.sub(r"\d+\s*积分", "", s or "")
    s = re.sub(r"[\s（）()\[\]【】·,，、]", "", s)
    s = re.sub(r"任选\d*$", "", s)  # store coupon products look like "麦旋风任选1"
    return s.lower()


def _alts(s: str) -> list[str]:
    """'中杯拿铁/美式' -> ['中杯拿铁', '中杯美式', '拿铁', '美式'] (size prefix shared)."""
    n = _norm(s)
    parts = [p for p in n.split("/") if p]
    if len(parts) <= 1:
        return [n] if n else []
    size = re.match(r"^(大杯|中杯|小杯|大份|中份|小份)", parts[0])
    out = list(parts)
    if size:
        for p in parts[1:]:
            if not p.startswith(size.group(1)):
                out.append(size.group(1) + p)
        out.append(parts[0][len(size.group(1)):])
    return out


def names_match(a: str, b: str) -> bool:
    """Loose match: one name (or an alternative of it) contains the other."""
    for x in _alts(a):
        for y in _alts(b):
            if x and y and (x in y or y in x):
                return True
    return False


_SIZES = ("大杯", "中杯", "小杯", "大份", "中份", "小份", "大", "中", "小")


def similar_items(want: str, menu: list[MenuItem], limit: int = 3) -> list[MenuItem]:
    """Closest single items for a name that isn't on the menu ("中杯拿铁" -> 麦咖啡™奶铁 …).

    Scores shared characters, ignoring cup sizes; combos/sets rank below single items.
    """
    w = _norm(want)
    for size in _SIZES:
        if w.startswith(size) and len(w) > len(size):
            w = w[len(size):]
            break
    chars = set(w)
    if not chars:
        return []
    scored = []
    for m in menu:
        n = _norm(m.name)
        common = len(chars & set(n))
        if not common:
            continue
        combo = any(k in m.name for k in ("套餐", "件套", "乐园餐", "分享", "桶", "盒"))
        scored.append((common / len(chars), not combo, -len(n), m))
    scored.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)
    best = scored[0][0] if scored else 0
    return [m for score, _, _, m in scored if score >= max(0.5, best - 0.25)][:limit]


def match_menu(want: str, menu: list[MenuItem]) -> MenuItem | None:
    """Best menu item for a keyword: exact name, else the shortest name containing it."""
    w = _norm(want)
    if not w:
        return None
    exact = [m for m in menu if _norm(m.name) == w]
    if exact:
        return exact[0]
    hits = [m for m in menu if w in _norm(m.name)]
    if not hits:
        hits = [m for m in menu if names_match(want, m.name)]
    return min(hits, key=lambda m: (len(m.name), m.price_fen)) if hits else None


# ------------------------------------------------------------------ planning
def plan_order(
    units: list[Unit],
    owned: list[OwnedCoupon],
    mall: list[MarketItem],
    points_budget: int,
) -> OrderPlan:
    budget = max(points_budget, 0)

    # Points options per unit: points buy a coupon; with it the item costs the coupon price
    # ("10.9元…"), or nothing for free-item coupons. Saving is measured against this store's price.
    point_opts: list[list[tuple[int, int, MarketItem]]] = []
    for u in units:
        opts = []
        for m in mall:
            if m.is_physical or not m.sku_id or not (0 < m.points <= budget) or not m.single_item:
                continue
            if not names_match(m.item_name, u.menu.name):
                continue
            saving = u.menu.price_fen - (m.use_price_fen or 0)
            if saving > 0:
                opts.append((m.points, saving, m))
        point_opts.append(opts)

    # Owned-coupon options: (unit, coupon, saving). One coupon id is used at most once.
    coupon_opts: dict[str, list[tuple[int, OwnedCoupon, int]]] = {}
    for ui, u in enumerate(units):
        for c in owned:
            if c.price_fen is None or not names_match(c.product_name or c.title, u.menu.name):
                continue
            saving = u.menu.price_fen - c.price_fen
            if saving > 0:
                coupon_opts.setdefault(c.coupon_id, []).append((ui, c, saving))

    best: tuple[tuple[int, int], dict[int, Choice]] | None = None

    def evaluate(assigned: dict[int, tuple[OwnedCoupon, int]]) -> None:
        nonlocal best
        rest = [ui for ui in range(len(units)) if ui not in assigned]
        picks = _mck([point_opts[ui] for ui in rest], budget)
        chosen: dict[int, Choice] = {
            ui: Choice(units[ui], "coupon", saving_fen=s, coupon=c) for ui, (c, s) in assigned.items()
        }
        for ui, pick in zip(rest, picks):
            if pick is None:
                chosen[ui] = Choice(units[ui], "cash")
            else:
                pts, saving, m = pick
                chosen[ui] = Choice(units[ui], "points", saving_fen=saving, points=pts, mall=m)
        score = (sum(c.saving_fen for c in chosen.values()), -sum(c.points for c in chosen.values()))
        if best is None or score > best[0]:
            best = (score, chosen)

    coupon_ids = list(coupon_opts)

    def search(k: int, assigned: dict[int, tuple[OwnedCoupon, int]]) -> None:
        if k == len(coupon_ids):
            evaluate(assigned)
            return
        search(k + 1, assigned)  # leave this coupon unused
        seen: set[str] = set()   # units of the same menu item are interchangeable
        for ui, c, saving in coupon_opts[coupon_ids[k]]:
            key = units[ui].menu.code
            if ui in assigned or key in seen:
                continue
            seen.add(key)
            assigned[ui] = (c, saving)
            search(k + 1, assigned)
            del assigned[ui]

    if len(coupon_ids) <= 8:
        search(0, {})
    else:  # pragma: no cover - unusually many coupons: greedy fallback
        assigned: dict[int, tuple[OwnedCoupon, int]] = {}
        flat = sorted(((s, ui, c) for opts in coupon_opts.values() for ui, c, s in opts), key=lambda x: -x[0])
        used: set[str] = set()
        for s, ui, c in flat:
            if ui not in assigned and c.coupon_id not in used:
                assigned[ui] = (c, s)
                used.add(c.coupon_id)
        evaluate(assigned)

    assert best is not None
    return OrderPlan(choices=[best[1][i] for i in range(len(units))], points_budget=budget)


def _mck(groups: list[list[tuple[int, int, Any]]], budget: int) -> list[tuple[int, int, Any] | None]:
    """Multiple-choice knapsack: at most one option per group, max value, ties -> fewer points."""
    costs = [o[0] for g in groups for o in g]
    if not costs or budget <= 0:
        return [None] * len(groups)
    g = 0
    for c in costs:
        g = gcd(g, c)
    cap = budget // g
    NEG = (-1, 0)
    dp = [(0, 0)] + [NEG] * cap  # dp[w] = (value, -points) using exactly w units
    parents: list[list[int]] = []  # parents[k][w] = option index chosen (-1 none)
    for opts in groups:
        new = list(dp)
        par = [-1] * (cap + 1)
        for oi, (pts, val, _) in enumerate(opts):
            w = pts // g
            for c in range(cap - w, -1, -1):
                if dp[c] == NEG:
                    continue
                cand = (dp[c][0] + val, dp[c][1] - pts)
                if cand > new[c + w]:
                    new[c + w] = cand
                    par[c + w] = oi
        dp = new
        parents.append(par)
    best_w = max(range(cap + 1), key=lambda w: dp[w])
    # Walk back.
    out: list[tuple[int, int, Any] | None] = [None] * len(groups)
    w = best_w
    for k in range(len(groups) - 1, -1, -1):
        oi = parents[k][w]
        if oi >= 0:
            out[k] = groups[k][oi]
            w -= groups[k][oi][0] // g
    return out


# ------------------------------------------------------------------ extras
@dataclass
class Extra:
    """Something worth adding to the cart because it's (almost) free with what the user already has."""
    kind: str  # "coupon" | "points" | "promo"
    menu: MenuItem
    pay_fen: int
    saving_fen: int
    points: int = 0
    coupon: OwnedCoupon | None = None
    mall: MarketItem | None = None
    days_left: int | None = None


def suggest_extras(plan: OrderPlan, menu: list[MenuItem], coupons: list[OwnedCoupon],
                   mall: list[MarketItem], budget: int, today: date, limit: int = 2) -> list[Extra]:
    """Idle coupons this order doesn't use, and leftover points that cover another item.

    Coupons expiring within 3 days come first, then by money saved.
    """
    used = {c.coupon.coupon_id for c in plan.choices if c.coupon}
    in_cart = {c.unit.menu.code for c in plan.choices}
    out: list[Extra] = []

    seen: set[str] = set()
    for c in coupons:
        if c.coupon_id in used or c.coupon_id in seen or c.price_fen is None:
            continue
        m = match_menu(c.product_name or c.title, menu)
        if m is None or not names_match(c.product_name or c.title, m.name):
            continue
        saving = m.price_fen - c.price_fen
        if saving <= 0:
            continue
        seen.add(c.coupon_id)
        days = (c.expires - today).days if c.expires else None
        out.append(Extra("coupon", m, pay_fen=c.price_fen, saving_fen=saving, coupon=c, days_left=days))

    left = budget - plan.points_used
    best: tuple[tuple[int, int], Extra] | None = None
    for mi in mall:
        if mi.is_physical or not mi.sku_id or mi.points <= 0 or mi.points > left or not mi.single_item:
            continue
        m = match_menu(mi.item_name, menu)
        if m is None or m.code in in_cart:
            continue
        pay = mi.use_price_fen or 0
        saving = m.price_fen - pay
        if saving <= 0:
            continue
        key = (saving, -mi.points)  # most money saved, then fewest points
        if best is None or key > best[0]:
            best = (key, Extra("points", m, pay_fen=pay, saving_fen=saving, points=mi.points, mall=mi))
    if best:
        out.append(best[1])

    # Store promotion: an odd count of a '第二份半价' item means the next one is half price.
    counts: dict[str, list[MenuItem]] = {}
    for c in plan.choices:
        if c.unit.menu.second_half and c.kind == "cash":
            counts.setdefault(c.unit.menu.code, []).append(c.unit.menu)
    for items in counts.values():
        if len(items) % 2 == 1:
            m = items[0]
            half = m.price_fen // 2
            out.append(Extra("promo", m, pay_fen=m.price_fen - half, saving_fen=half))

    def rank(x: Extra) -> tuple[int, int]:
        urgent = x.days_left is not None and 0 <= x.days_left <= 3
        return (0 if urgent else 1, -x.saving_fen)

    return sorted(out, key=rank)[:limit]


def price_from_menu(items: list[MarketItem], menu: list[MenuItem]) -> int:
    """Fill in each points item's reference price from the store menu; returns how many matched.

    The mall itself has no reference price, so a coupon's worth is only known against a menu.
    Bundles and physical goods are left alone.
    """
    n = 0
    for mi in items:
        if mi.is_physical or not mi.single_item or mi.ref_price is not None:
            continue
        m = match_menu(mi.item_name, menu)
        if m is not None:
            mi.ref_price = Decimal(m.price_fen) / 100
            n += 1
    return n
