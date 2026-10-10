"""吃了多少：把点餐记录（order-list）和营养表（list-nutrition-foods）对起来，按今天 / 本周 / 本月统计。

- 套餐按 comboItemList 拆成单品再查营养（套餐名本身查不到）；查不到的单品单独列出，不瞎估。
- 取消、退款、待支付的订单不算。
- order-list 只返回最近的订单，所以每次统计都把见过的订单记到本机 meals.json，时间长了周、月数据才完整。
  演示模式不写文件。

参考值按《中国居民膳食指南》成年人：能量约 2000 千卡/天，钠不超过 2000 毫克/天（约 5 克盐）。
只是对照，不是建议。
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .content import Nutrition, find_nutrition

KCAL_PER_DAY = 2000
SODIUM_PER_DAY = 2000
SKIP = ("取消", "退款", "待支付", "未支付", "已关闭")


@dataclass
class Item:
    name: str
    qty: int
    kcal: float | None = None
    protein: float = 0.0
    fat: float = 0.0
    carbs: float = 0.0
    sodium: float = 0.0


@dataclass
class Meal:
    order_id: str
    time: datetime
    store: str = ""
    pay_fen: int = 0
    items: list[Item] = field(default_factory=list)

    @property
    def kcal(self) -> float:
        return sum(i.kcal * i.qty for i in self.items if i.kcal is not None)

    def to_json(self) -> dict[str, Any]:
        return {"order_id": self.order_id, "time": self.time.strftime("%Y-%m-%d %H:%M:%S"), "store": self.store,
                "pay_fen": self.pay_fen, "items": [i.__dict__ for i in self.items]}

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> "Meal":
        return cls(str(d["order_id"]), datetime.strptime(d["time"], "%Y-%m-%d %H:%M:%S"), d.get("store", ""),
                   int(d.get("pay_fen") or 0), [Item(**i) for i in d.get("items") or []])


def _fen(v: Any) -> int:
    try:
        return round(float(str(v)) * 100)
    except (TypeError, ValueError):
        return 0


def _item(name: str, qty: int, table: list[Nutrition]) -> Item:
    n = find_nutrition(name, table) if name else None
    if n is None:
        return Item(name, qty)
    return Item(name, qty, float(n.kcal), float(n.protein), float(n.fat), float(n.carbs), float(n.sodium))


def meals_from_orders(rows: list[dict[str, Any]], table: list[Nutrition]) -> list[Meal]:
    out = []
    for o in rows:
        status = str(o.get("orderStatus") or "")
        if not o.get("orderId") or any(w in status for w in SKIP):
            continue
        try:
            t = datetime.strptime(str(o.get("createTime"))[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        items: list[Item] = []
        for p in o.get("orderProductList") or []:
            q = int(p.get("quantity") or 1)
            parts = p.get("comboItemList") or []
            if parts:   # 套餐：拆成单品
                items += [_item(str(c.get("name") or ""), q * int(c.get("quantity") or 1), table) for c in parts]
            else:
                items.append(_item(str(p.get("productName") or ""), q, table))
        out.append(Meal(str(o["orderId"]), t, str(o.get("storeName") or ""), _fen(o.get("realTotalAmount")), items))
    return out


# ------------------------------------------------------------------ local ledger
def load_ledger(path: Path) -> dict[str, Meal]:
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
        return {m.order_id: m for m in (Meal.from_json(r) for r in rows)}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def merge(ledger: dict[str, Meal], fresh: list[Meal]) -> dict[str, Meal]:
    out = dict(ledger)
    out.update({m.order_id: m for m in fresh})   # the server's latest view wins
    return out


def save_ledger(path: Path, meals: dict[str, Meal]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted((m.to_json() for m in meals.values()), key=lambda r: r["time"])
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


# ------------------------------------------------------------------ summaries
def periods(now: datetime) -> dict[str, tuple[datetime, datetime, int]]:
    """name -> (start, end, days so far)."""
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week0 = day0 - timedelta(days=day0.weekday())
    month0 = day0.replace(day=1)
    end = day0 + timedelta(days=1)
    return {"today": (day0, end, 1), "week": (week0, end, (day0 - week0).days + 1),
            "month": (month0, end, (day0 - month0).days + 1)}


def summarize(meals: list[Meal], start: datetime, end: datetime, days: int) -> dict[str, Any]:
    picked = [m for m in meals if start <= m.time < end]
    tot = {"kcal": 0.0, "protein": 0.0, "fat": 0.0, "carbs": 0.0, "sodium": 0.0}
    eaten: Counter[str] = Counter()
    kcal_by: Counter[str] = Counter()
    missing: Counter[str] = Counter()
    for m in picked:
        for i in m.items:
            if i.kcal is None:
                missing[i.name] += i.qty
                continue
            for k in ("protein", "fat", "carbs", "sodium"):
                tot[k] += getattr(i, k) * i.qty
            tot["kcal"] += i.kcal * i.qty
            eaten[i.name] += i.qty
            kcal_by[i.name] += i.kcal * i.qty
    kcal = round(tot["kcal"])
    energy = tot["protein"] * 4 + tot["fat"] * 9 + tot["carbs"] * 4
    return {
        "orders": len(picked), "spent_fen": sum(m.pay_fen for m in picked),
        "kcal": kcal, "protein_g": round(tot["protein"], 1), "fat_g": round(tot["fat"], 1),
        "carbs_g": round(tot["carbs"], 1), "sodium_mg": round(tot["sodium"]),
        "days": days, "kcal_per_day": round(kcal / days) if days else kcal,
        "share_of_daily_kcal": round(kcal / (KCAL_PER_DAY * days), 3) if days else None,
        "energy_split": {"protein": round(tot["protein"] * 4 / energy, 3), "fat": round(tot["fat"] * 9 / energy, 3),
                         "carbs": round(tot["carbs"] * 4 / energy, 3)} if energy else None,
        "top": [{"name": n, "count": eaten[n], "kcal": round(kcal_by[n])} for n, _ in kcal_by.most_common(5)],
        "not_counted": [{"name": n, "count": c} for n, c in missing.most_common()],
    }


def daily(meals: list[Meal], now: datetime, days: int = 30) -> list[dict[str, Any]]:
    day0 = now.date()
    by: Counter[date] = Counter()
    n: Counter[date] = Counter()
    for m in meals:
        by[m.time.date()] += m.kcal
        n[m.time.date()] += 1
    return [{"date": (day0 - timedelta(days=k)).isoformat(), "kcal": round(by[day0 - timedelta(days=k)]),
             "orders": n[day0 - timedelta(days=k)]} for k in range(days - 1, -1, -1)]


def sparkline(values: list[float]) -> str:
    bars = "▁▂▃▄▅▆▇█"
    top = max(values) if values else 0
    return "".join("·" if not v else bars[min(len(bars) - 1, int(v / top * (len(bars) - 1)))] for v in values) if top else ""
