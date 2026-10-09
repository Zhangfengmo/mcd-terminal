"""Pure logic: parse tool payloads, value points, and plan the best redemption.

Kept free of I/O so it can be unit-tested without a token.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from math import gcd
from typing import Any, Iterable


# ---------------------------------------------------------------- account
@dataclass
class Account:
    available: int
    frozen: int
    expiring_this_month: int
    expiring_next_month: int
    accumulated: float
    used: float

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> "Account":
        return cls(
            available=_int(data.get("availablePoint")),
            frozen=_int(data.get("frozenPoint")),
            # the API spells it "Mouth"; accept "Month" too in case it is ever fixed
            expiring_this_month=_int(data.get("currentMouthExpirePoint", data.get("currentMonthExpirePoint"))),
            expiring_next_month=_int(data.get("nextMouthExpirePoint", data.get("nextMonthExpirePoint"))),
            accumulated=_float(data.get("accumulativePoint")),
            used=_float(data.get("usedPoint")),
        )

    @property
    def at_risk(self) -> int:
        """Points that will expire this month or next."""
        return self.expiring_this_month + self.expiring_next_month


# ---------------------------------------------------------------- coupons
@dataclass
class Coupon:
    title: str
    price: str | None
    end: date | None
    tags: str = ""

    def days_left(self, today: date) -> int | None:
        return None if self.end is None else (self.end - today).days


_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def parse_coupons(markdown: str) -> list[Coupon]:
    """Parse the Markdown returned by `query-my-coupons`."""
    if not isinstance(markdown, str):
        return []
    coupons: list[Coupon] = []
    for block in re.split(r"^##\s+", markdown, flags=re.M)[1:]:
        lines = block.strip().splitlines()
        title = lines[0].strip()
        price = end = None
        tags = ""
        for ln in lines[1:]:
            if "优惠" in ln and (m := re.search(r"¥\s*([\d.]+)", ln)):
                price = m.group(1)
            elif "有效期" in ln:
                dates = _DATE.findall(ln)
                if dates:
                    end = datetime.strptime(dates[-1], "%Y-%m-%d").date()
            elif "标签" in ln:
                tags = ln.split(":", 1)[-1].replace("**", "").strip()
        coupons.append(Coupon(title, price, end, tags))
    return coupons


CLAIMABLE = ("可领取", "未领取")  # the live server says 可领取; the docs showed 未领取


def is_claimable(status: str) -> bool:
    return status in CLAIMABLE


def parse_claimable(markdown: Any) -> list[tuple[str, str]]:
    """`available-coupons` Markdown -> [(title, status)], status like 未领取/已领取/不可领取."""
    if not isinstance(markdown, str):
        return []
    pat = re.compile(r"优惠券标题[:：]\s*(.+?)\s*\\?\s*\n\s*状态[:：]\s*([^\s\\]+)")
    return [(t.strip(), s.strip()) for t, s in pat.findall(markdown)]


def parse_bind_result(markdown: Any) -> tuple[int | None, int | None, list[str]]:
    """`auto-bind-coupons` Markdown -> (succeeded, failed, claimed titles)."""
    if not isinstance(markdown, str):
        return None, None, []

    def num(label: str) -> int | None:
        m = re.search(rf"{label}\**\s*[:：]\s*(\d+)", markdown)
        return int(m.group(1)) if m else None

    titles: list[str] = []
    if "成功领取" in markdown:
        section = markdown.split("成功领取", 1)[1].split("####", 1)[0]
        titles = re.findall(r"^\s*-\s*\*\*(.+?)\*\*", section, flags=re.M)
    return num("成功"), num("失败"), titles


# ---------------------------------------------------------------- market
@dataclass
class MarketItem:
    spu_id: int
    sku_id: int | None
    name: str
    points: int
    ref_price: Decimal | None  # yuan: the store's menu price of the item, when known
    category: str = "1"  # "1" virtual coupon, "2" physical goods
    off_shelf: str = ""
    cat_name: str = ""   # listing catName, e.g. 到店专用 / 生日类派对 / 玩具
    ext_price: Decimal | None = None  # yuan, `extTradePrice`: what you still pay when using the coupon

    @property
    def is_physical(self) -> bool:
        return self.category == "2"

    @property
    def in_store_only(self) -> bool:
        return "到店" in self.cat_name

    @property
    def use_price_fen(self) -> int | None:
        """What you still pay at the store with the redeemed coupon.

        Live mall items are mostly discount coupons named like "10.9元指定小食任选": points buy
        the coupon, then the item costs 10.9元. The detail's `extTradePrice` ("券核销额外支付金额")
        says the same thing and wins when present; names without a price are free-item coupons.
        """
        if self.ext_price is not None:
            return int(self.ext_price * 100)
        m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*元", self.name)
        return int(Decimal(m.group(1)) * 100) if m else None

    @property
    def single_item(self) -> bool:
        """True when the coupon clearly covers one unit of one item (safe to map onto a cart line).

        Bundles ("2份…", "两件套", "组合") and pick-any coupons ("任选") are not mapped automatically.
        Piece counts that are part of one item ("麦乐鸡5块") still count as a single item.
        """
        body = re.sub(r"^\s*\d+(?:\.\d+)?\s*元", "", self.name)
        if re.search(r"(组合|套|任选|[2-9两二三四]\s*[份件]|\d+\s*份)", body):
            return False
        return bool(body.strip())

    @property
    def item_name(self) -> str:
        """The item part of the name, without the price prefix."""
        return re.sub(r"^\s*\d+(?:\.\d+)?\s*元", "", self.name).strip()

    @property
    def ref_fen(self) -> int | None:
        return None if self.ref_price is None else int(self.ref_price * 100)

    @property
    def value_fen(self) -> int | None:
        """What the points actually buy, in 分.

        For a free-item coupon that is the reference price. For a discount coupon
        ("6.9元可乐麦炫酷") you still pay the coupon price, so only the difference counts;
        if the reference price is not above the coupon price we cannot tell, so None.
        """
        ref = self.ref_fen
        if not ref:
            return None
        use = self.use_price_fen or 0
        return ref - use if ref > use else None

    @property
    def fen_per_point(self) -> float | None:
        """Cash value in 分 that each point buys."""
        if self.value_fen is None or self.points <= 0:
            return None
        return self.value_fen / self.points


def clean_name(spu_name: str) -> str:
    return re.sub(r"\s*\d+\s*积分\s*$", "", spu_name or "").strip() or spu_name


def on_shelf(listing: dict[str, Any], now: datetime) -> bool:
    """The live listing still contains items whose upTime/downTime window has passed."""
    def when(key: str) -> datetime | None:
        try:
            return datetime.strptime(str(listing.get(key) or "")[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    up, down = when("upTime"), when("downTime")
    return (up is None or up <= now) and (down is None or now <= down)


def market_item(listing: dict[str, Any], detail: dict[str, Any] | None,
                ref_price: Decimal | None = None) -> MarketItem:
    detail = detail or {}
    sku = (detail.get("skuList") or [{}])[0]
    ext = sku.get("extTradePrice")
    return MarketItem(
        spu_id=_int(listing.get("spuId")),
        sku_id=_int(sku.get("skuId")) or None,
        name=clean_name(listing.get("spuName", "")),
        points=_int(sku.get("points") or listing.get("point")),
        ref_price=ref_price,
        ext_price=None if ext in (None, "") else _decimal_or_zero(ext),
        category=str(detail.get("spuCategory") or "1"),
        off_shelf=str(listing.get("downTime") or detail.get("downDate") or ""),
        cat_name=str(listing.get("catName") or detail.get("catName") or ""),
    )


def rank(items: Iterable[MarketItem]) -> list[MarketItem]:
    """Best value per point first; items without a reference price go last."""
    return sorted(items, key=lambda i: (i.fen_per_point is None, -(i.fen_per_point or 0), i.points))


# ---------------------------------------------------------------- planner
@dataclass
class Plan:
    budget: int
    picks: list[tuple[MarketItem, int]] = field(default_factory=list)

    @property
    def points_used(self) -> int:
        return sum(i.points * n for i, n in self.picks)

    @property
    def value_fen(self) -> int:
        return sum((i.value_fen or 0) * n for i, n in self.picks)

    @property
    def leftover(self) -> int:
        return self.budget - self.points_used


def optimize(items: Iterable[MarketItem], budget: int, max_each: int = 2) -> Plan:
    """Bounded knapsack: maximise total reference value within `budget` points.

    Only virtual items with a known price and sku are considered (physical goods
    need a delivery address). Ties prefer spending more points, since the usual
    goal is to use up points before they expire.
    """
    pool = [i for i in items if not i.is_physical and i.value_fen and i.sku_id and 0 < i.points <= budget]
    plan = Plan(budget=budget)
    if budget <= 0 or not pool or max_each <= 0:
        return plan

    # Scale by the common divisor of all costs so the DP table stays small.
    g = 0
    for i in pool:
        g = gcd(g, i.points)
    cap = budget // g

    # Expand each item into up to `max_each` copies (0/1 knapsack).
    copies: list[MarketItem] = [i for i in pool for _ in range(max_each)]
    # Score = value * (cap+1) + units used, so value wins and units break ties.
    scale = cap + 1
    best = [0] * (cap + 1)
    choice: list[list[bool]] = [[False] * (cap + 1) for _ in copies]
    for k, item in enumerate(copies):
        w = item.points // g
        s = item.value_fen * scale + w
        for c in range(cap, w - 1, -1):
            if best[c - w] + s > best[c]:
                best[c] = best[c - w] + s
                choice[k][c] = True

    top = best[cap] // scale
    c = cap
    counts: dict[int, int] = {}
    for k in range(len(copies) - 1, -1, -1):
        if choice[k][c]:
            item = copies[k]
            counts[id(item)] = counts.get(id(item), 0) + 1
            c -= item.points // g
    by_id = {id(i): i for i in pool}
    plan.picks = sorted(
        ((by_id[k], n) for k, n in counts.items()),
        key=lambda p: -(p[0].fen_per_point or 0),
    )
    assert plan.value_fen == top
    return plan


# ---------------------------------------------------------------- helpers
def _int(v: Any) -> int:
    try:
        return int(Decimal(str(v)))
    except (InvalidOperation, TypeError, ValueError):
        return 0


def _float(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _decimal_or_zero(v: Any) -> Decimal | None:
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        return None
    return d if d >= 0 else None


def _decimal(v: Any) -> Decimal | None:
    if v in (None, ""):
        return None
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        return None
    return d if d > 0 else None
