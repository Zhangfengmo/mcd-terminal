"""Campaign calendar → the activity map: one entry per campaign, its days, which "district" of the map it
belongs to, whether it has toys / merch, and which dishes on this store's menu it's about.

Same rules as the web activity map (index.html DISTRICTS / toyKind / campaignItems), so `mcd calendar`
and `mcd web` group and match campaigns the same way.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable

# key, name, emoji, pattern — first match wins
DISTRICTS = [
    ("toy", "周边玩具铺", "🧸", r"玩具|盲盒|公仔|手办|乐园餐|周边|联名|联动|\sX\s|×|帽|丝巾|杯子|钥匙扣|徽章|挂件|限定主题|限量"),
    ("party", "派对乐园", "🎈", r"派对|生日|体验营|读书会|亲子|品鉴|过家家"),
    ("breakfast", "早餐小镇", "☀️", r"早餐|早八|厚松饼|满分|晨"),
    ("coffee", "咖啡山丘", "☕", r"咖啡|麦咖啡|拿铁|美式|奶铁|黑巧"),
    ("new", "上新广场", "🆕", r"上新|新品|回归|首发|来袭|登场|限定|🆕"),
    ("deal", "优惠大街", "🎟", r"\d+(\.\d+)?元|特价|优惠|券|半价|买一送一|立减|会员|卡|霸王餐|抽奖|超值"),
]
OTHER = ("other", "麦麦广场", "🍟")
WHEN = {"today": "今天在做", "soon": "即将开始", "past": "已经结束"}


def district_of(text: str) -> tuple[str, str, str]:
    for key, name, emoji, pat in DISTRICTS:
        if re.search(pat, text):
            return key, name, emoji
    return OTHER


def toy_kind(text: str) -> str:
    if re.search(r"玩具|盲盒|公仔|手办|乐园餐", text):
        return "有玩具"
    if re.search(r"周边|联名|联动|\sX\s|×|帽|丝巾|杯子|钥匙扣|徽章|挂件|限定主题|限量", text):
        return "有周边"
    return ""


def parse_day(text: str, year: int) -> date | None:
    m = re.search(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})", text or "")
    if m:
        y, mo, d = map(int, m.groups())
    else:
        m = re.search(r"(\d{1,2})\s*[月/.-]\s*(\d{1,2})", text or "")
        if not m:
            return None
        y, (mo, d) = year, map(int, m.groups())
    try:
        return date(y, mo, d)
    except ValueError:
        return None


@dataclass
class Campaign:
    title: str
    intro: str = ""
    detail: str = ""
    image: str = ""
    days: list[date] = field(default_factory=list)
    when: str = "past"
    district: tuple[str, str, str] = OTHER
    toy: str = ""

    @property
    def text(self) -> str:
        return f"{self.title} {self.detail or self.intro}"

    @property
    def range(self) -> str:
        if not self.days:
            return ""
        a, b = self.days[0], self.days[-1]
        md = lambda d: f"{d.month}/{d.day}"  # noqa: E731
        return md(a) if a == b else f"{md(a)} – {md(b)}"

    def next_day(self, today: date) -> date | None:
        return next((d for d in self.days if d > today), None)

    def as_dict(self, today: date) -> dict[str, Any]:
        nxt = self.next_day(today)
        return {"title": self.title, "intro": self.intro or None, "detail": self.detail or None, "image": self.image or None,
                "days": [d.isoformat() for d in self.days], "range": self.range, "when": self.when, "when_text": WHEN[self.when],
                "next": nxt.isoformat() if nxt else None, "district": self.district[1], "district_key": self.district[0],
                "toy": self.toy or None}


def merge(items: Iterable[Any], today: date) -> list[Campaign]:
    """Calendar rows (one per campaign per day) → one Campaign each, today's first, then upcoming, then past."""
    by: dict[str, Campaign] = {}
    for it in items:
        c = by.setdefault(it.title, Campaign(it.title))
        c.intro = c.intro or it.intro or ""
        c.detail = c.detail or (it.detail or "")
        c.image = c.image or (it.image or "")
        d = parse_day(it.day, today.year)
        if d and d not in c.days:
            c.days.append(d)
    out = []
    for c in by.values():
        c.days.sort()
        c.when = "today" if today in c.days else ("soon" if any(d > today for d in c.days) else "past")
        c.district = district_of(c.text)
        c.toy = toy_kind(c.text)
        out.append(c)
    order = {"today": 0, "soon": 1, "past": 2}
    return sorted(out, key=lambda c: order[c.when])


def find(campaigns: list[Campaign], query: str) -> list[Campaign]:
    q = re.sub(r"\s+", "", query)
    exact = [c for c in campaigns if re.sub(r"\s+", "", c.title) == q]
    return exact or [c for c in campaigns if q in re.sub(r"\s+", "", c.title)]


def items_on_menu(c: Campaign, menu: list[Any], limit: int = 8) -> list[Any]:
    """Dishes of this store's menu that the campaign text names — the specific one wins
    (keep "蓝莓爆爆珠麦旋风", drop plain "麦旋风")."""
    text = re.sub(r"\s+", "", c.text)
    hits = [m for m in menu if len(m.name) >= 2 and re.sub(r"\s+", "", m.name) in text]
    hits.sort(key=lambda m: -len(m.name))
    keep = [m for i, m in enumerate(hits) if not any(m.name in o.name for o in hits[:i])]
    return keep[:limit]
