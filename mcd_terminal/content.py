"""Parsers for the remaining tool payloads, built from the documented examples."""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from typing import Any

from .order import names_match


# ------------------------------------------------------------ nutrition
@dataclass
class Nutrition:
    name: str
    kcal: int
    protein: float
    fat: float
    carbs: float
    sodium: float


def parse_nutrition(data: Any) -> list[Nutrition]:
    """`list-nutrition-foods` returns a compact 'toon' table:

        [1]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:
          猪柳麦满分,null,1288,308,16,16,24,781,213
    """
    text = data if isinstance(data, str) else ""
    if isinstance(data, list):  # tolerate a plain JSON list too
        return [n for n in (_nutrition_from_dict(d) for d in data) if n]
    m = re.search(r"\{([^}]*)\}\s*:", text)
    if not m:
        return []
    fields = [f.strip() for f in m.group(1).split(",")]
    body = text[m.end():]
    out: list[Nutrition] = []
    for row in csv.reader(io.StringIO(body)):
        row = [c.strip() for c in row]
        if len(row) != len(fields) or not row[0]:
            continue
        n = _nutrition_from_dict(dict(zip(fields, row)))
        if n:
            out.append(n)
    return out


def _nutrition_from_dict(d: dict[str, Any]) -> Nutrition | None:
    def num(k: str) -> float:
        try:
            return float(d.get(k))
        except (TypeError, ValueError):
            return 0.0
    name = str(d.get("productName") or "").strip()
    if not name:
        return None
    return Nutrition(name, int(num("energyKcal")), num("protein"), num("fat"), num("carbohydrate"), num("sodium"))


def find_nutrition(name: str, table: list[Nutrition]) -> Nutrition | None:
    exact = [n for n in table if n.name == name]
    if exact:
        return exact[0]
    hits = [n for n in table if names_match(n.name, name)]
    return min(hits, key=lambda n: abs(len(n.name) - len(name))) if hits else None


# ------------------------------------------------------------ calendar
@dataclass
class Campaign:
    day: str     # e.g. "12月9日"
    tag: str     # e.g. "今日" / "往期回顾" / "即将开始"
    title: str
    intro: str


def parse_calendar(text: Any) -> list[Campaign]:
    if not isinstance(text, str):
        return []
    out: list[Campaign] = []
    day = tag = ""
    current: Campaign | None = None
    for line in text.splitlines():
        h = re.match(r"^####\s+(\S+)\s*(.*)$", line.strip())
        if h:
            day, tag = h.group(1), h.group(2).strip()
            continue
        t = re.search(r"\*\*活动标题\*\*[:：]\s*(.+?)\s*\\?\s*$", line)
        if t:
            current = Campaign(day, tag, t.group(1).strip(), "")
            out.append(current)
            continue
        i = re.search(r"\*\*活动内容介绍\*\*[:：]\s*(.+?)\s*\\?\s*$", line)
        if i and current:
            current.intro = i.group(1).strip()
    return out


# ------------------------------------------------------------ mall orders
def parse_mall_orders(data: Any) -> tuple[list[dict[str, Any]], Any]:
    """`mall-order-list` wraps the page in a one-element array: [{hasNext, lastId, list}]."""
    page = data[0] if isinstance(data, list) and data and isinstance(data[0], dict) and "list" in data[0] else data
    if isinstance(page, dict):
        return list(page.get("list") or []), (page.get("lastId") if page.get("hasNext") else None)
    if isinstance(data, list):
        return data, None
    return [], None


def goods_text(order: dict[str, Any]) -> str:
    goods = order.get("goods") or []
    return "、".join(f"{g.get('spuName', '')}{('·' + g['skuName']) if g.get('skuName') else ''}"
                    f"{' x' + str(g['count']) if g.get('count', 1) != 1 else ''}" for g in goods) or "—"


# ------------------------------------------------------------ store order
STATUS_HINTS = {
    "待支付": "还没付款，打开支付链接就能完成",
    "已支付": "付好啦，餐厅正在准备",
    "制作中": "餐厅正在做，马上就好",
    "配送中": "骑手已经出发，快到了",
    "待取餐": "可以去取餐了",
    "已完成": "已经完成，希望吃得开心",
    "已取消": "订单已取消",
}


def status_hint(status: str) -> str:
    for k, v in STATUS_HINTS.items():
        if k in (status or ""):
            return v
    return ""
