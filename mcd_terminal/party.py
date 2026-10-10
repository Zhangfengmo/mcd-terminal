"""派对场次怎么选才不会“凑不齐人”。

麦当劳门店派对的两条硬规则：
- 拼团在截止前没凑够最少人数，预约会自动取消并退款——选错场次，生日当天就没场地；
- 需要提前 N 天（通常 3 天）预订——留给拉人的时间是一个倒计时。

服务端只给每个场次的 partyMin / partyMax / leftNum，这里据此算出：已经报了几个人、
加上你们还差几个、拉人截止还剩多久，并给出最稳的场次和方式。截止时间按“提前 N 天预订”推算，以 App 为准。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

ADVANCE_DEFAULT = 3
KINDS = {1: "包场", 2: "拼团"}


def advance_days(detail: dict[str, Any] | None) -> int:
    """商品须知里“请提前3天预订”的天数；没写就按 3 天。"""
    text = re.sub(r"<[^>]+>", "", str((detail or {}).get("note") or ""))
    m = re.search(r"提前\s*(\d+)\s*天", text)
    return int(m.group(1)) if m else ADVANCE_DEFAULT


def deadline(day: str, advance: int) -> datetime:
    """最后能预约 / 凑人的时刻：活动日前 advance 天的 23:59:59。"""
    d = datetime.strptime(day, "%Y-%m-%d") - timedelta(days=advance)
    return d.replace(hour=23, minute=59, second=59)


def joined(x: dict[str, Any]) -> int:
    """这一场已经有几个人报了（拼团）：最多人数 - 剩余位置。"""
    hi, left = x.get("partyMax"), x.get("leftNum")
    if not isinstance(hi, int) or not isinstance(left, int):
        return 0
    return max(0, hi - left)


def countdown(hours: float) -> str:
    if hours <= 0:
        return "已截止"
    if hours < 1:
        return "不到 1 小时"
    if hours < 48:
        return f"还剩 {int(hours)} 小时"
    return f"还剩 {int(hours // 24)} 天"


@dataclass
class Fit:
    day: str
    session: dict[str, Any]
    kind: int                   # 1 包场 / 2 拼团
    people: int                 # 你们几个人
    joined: int                 # 已经报名的（拼团）
    min: int
    max: int | None
    left: int | None
    need: int                   # 加上你们还差几个人
    fits: bool                  # 位置够不够你们这些人
    deadline: datetime
    hours_left: float

    @property
    def expired(self) -> bool:
        return self.hours_left <= 0

    @property
    def safe(self) -> bool:
        """不用指望别人：人数够、位置够、还没截止。"""
        return self.need == 0 and self.fits and not self.expired

    @property
    def verdict(self) -> str:
        if self.expired:
            return "已过预约截止"
        if not self.fits:
            return f"位置不够（只剩 {self.left}）" if self.kind == 2 else f"人太多（最多 {self.max} 人）"
        if self.kind == 1:
            return "人够了，整场是你们的" if self.need == 0 else f"包场至少 {self.min} 人，还差 {self.need} 人"
        if self.need == 0:
            return "加上你们就成团" if self.joined < self.min else "已成团，直接加入"
        return f"加上你们还差 {self.need} 人成团"

    def as_dict(self) -> dict[str, Any]:
        return {"date": self.day, "time": self.session.get("timeStart"), "end": self.session.get("timeEnd"),
                "type": KINDS[self.kind], "people": self.people, "joined": self.joined, "min": self.min,
                "max": self.max, "left": self.left, "need_more": self.need, "safe": self.safe,
                "deadline": self.deadline.strftime("%Y-%m-%d %H:%M"), "hours_left": round(max(self.hours_left, 0), 1),
                "verdict": self.verdict}


def assess(day: str, x: dict[str, Any], kind: int, people: int, now: datetime, advance: int) -> Fit:
    lo = int(x.get("partyMin") or 1)
    hi = x.get("partyMax") if isinstance(x.get("partyMax"), int) else None
    left = x.get("leftNum") if isinstance(x.get("leftNum"), int) else None
    j = joined(x)
    if kind == 1:   # 包场：整场只有你们，人数全靠自己
        need, fits = max(0, lo - people), hi is None or people <= hi
    else:           # 拼团：和别的家庭凑，已报的人也算
        need, fits = max(0, lo - j - people), left is None or people <= left
    dl = deadline(day, advance)
    return Fit(day, x, kind, people, j, lo, hi, left, need, fits, dl, (dl - now).total_seconds() / 3600)


def rank(sessions: list[tuple[str, dict[str, Any]]], kinds: list[int], people: int, now: datetime,
         advance: int, by: date | None = None) -> list[Fit]:
    """最稳的排前面：不用等别人 > 差的人少 > （有 by 时）离想办的日子近 > 包场 > 已报的人多。"""
    fits = []
    for day, x in sessions:
        if (x.get("leftNum") or 0) <= 0:
            continue
        d = datetime.strptime(day, "%Y-%m-%d").date()
        if by and d > by:
            continue
        for k in kinds:
            f = assess(day, x, k, people, now, advance)
            if not f.expired and f.fits:
                fits.append(f)

    def key(f: Fit) -> tuple:
        d = datetime.strptime(f.day, "%Y-%m-%d").date()
        closeness = (by - d).days if by else (d - now.date()).days
        # 人够时包场最稳（不靠别人）；人不够时拼团更有希望（别的家庭也会来报）
        kind_pref = f.kind != 1 if f.safe else f.kind != 2
        if by:   # 有想办的日子（比如生日）：稳的里面挑离那天最近的
            return (not f.safe, f.need, closeness, kind_pref, -f.joined, f.session.get("timeStart") or "")
        return (not f.safe, f.need, kind_pref, -f.joined, closeness, f.session.get("timeStart") or "")
    return sorted(fits, key=key)


def invite_text(event: str, store: str, f: Fit) -> str:
    """发给亲友群的一段话：哪天哪家店哪一场、还差几个人、什么时候前报名。"""
    when = f"{f.day[5:].replace('-', '月')}日 {f.session.get('timeStart')}–{f.session.get('timeEnd')}"
    if f.need:
        head = f"还差 {f.need} 位小朋友就成团！{f.deadline:%m月%d日 %H:%M} 前报名有效，凑不齐会自动取消退款。"
    else:
        head = f"已经够人成团啦，欢迎再多来几位！{f.deadline:%m月%d日} 前都能报名。"
    return (f"🎈 {when} 在{store}办「{event}」（拼团），{head}"
            f"打开麦当劳 App → 麦麦商城 → 搜「{event}」→ 选{store}、{when} 这一场，一起来玩～")


def check_time(f: Fit, now: datetime) -> datetime | None:
    """拉人截止前什么时候提醒看一眼：截止当天 10 点；来不及就截止前 3 小时；再来不及就不提醒了。"""
    for t in (f.deadline.replace(hour=10, minute=0, second=0), f.deadline - timedelta(hours=3)):
        if t > now + timedelta(minutes=30):
            return t
    return None
