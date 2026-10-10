"""企业团餐的满减 / 满折规则（query-promotions）。

服务端只返回规则原始数据，不做推荐；这里算出这单现在能享受哪一条、离下一档还差多少。
最终金额以 calculate-price 的核价为准。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Tier:
    threshold_fen: int
    reduce_fen: int = 0       # 满减：减多少
    off_pct: int = 0          # 满折：打掉多少（30 = 7 折）

    def saving(self, eligible_fen: int) -> int:
        if eligible_fen < self.threshold_fen:
            return 0
        return self.reduce_fen if self.reduce_fen else eligible_fen * self.off_pct // 100

    @property
    def text(self) -> str:
        head = f"满{_yuan(self.threshold_fen)}"
        if self.reduce_fen:
            return f"{head}减{_yuan(self.reduce_fen)}"
        zhe = (100 - self.off_pct) / 10
        return f"{head}享{zhe:g}折"


@dataclass
class Promo:
    promo_id: str
    tiers: list[Tier]
    scope: str = "3"                       # 1 只含 codes，2 除了 codes，3 全部餐品
    codes: set[str] = field(default_factory=set)
    start: str = ""
    end: str = ""
    service: str = ""                      # gmServiceCode：团餐的满折按助餐服务分开（保鲜速达 / 专人分餐…）

    def covers(self, code: str) -> bool:
        if self.scope == "1":
            return code in self.codes
        if self.scope == "2":
            return code not in self.codes
        return True

    @property
    def text(self) -> str:
        return " / ".join(t.text for t in self.tiers) + {"1": "（指定餐品）", "2": "（个别餐品除外）"}.get(self.scope, "")


def _yuan(fen: int) -> str:
    return f"¥{fen / 100:g}"


def _fen(v: Any) -> int | None:
    try:
        return round(float(str(v).strip()) * 100)
    except (TypeError, ValueError):
        return None


def parse_promotions(data: Any) -> list[Promo]:
    rows = data.get("list") or data.get("data") or [] if isinstance(data, dict) else data
    out: list[Promo] = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        detail = r.get("ruleDetail") or {}
        tiers: list[Tier] = []
        for x in (detail.get("orderReduce") or {}).get("reduceInfo") or []:
            th, amt = _fen(x.get("startDiscountPoint")), _fen(x.get("reduceAmount"))
            if th is not None and amt:
                tiers.append(Tier(th, reduce_fen=amt))
        disc = detail.get("orderDiscount") or {}
        th, off = _fen(disc.get("startDiscountPoint")), _fen(disc.get("discount"))
        if th is not None and off:
            tiers.append(Tier(th, off_pct=off // 100))
        if not tiers:
            continue
        prods = [p for p in r.get("products") or [] if isinstance(p, dict)]
        scope = str(prods[0].get("type", "3")) if prods else "3"
        codes = {str(p.get("productCode")) for p in prods if p.get("productCode")}
        out.append(Promo(str(r.get("promotionId", "")), sorted(tiers, key=lambda t: t.threshold_fen), scope, codes,
                         str(r.get("startTime") or ""), str(r.get("endTime") or ""), str(r.get("gmServiceCode") or "")))
    return out


def for_service(promos: list[Promo], service: str | None) -> list[Promo]:
    """只留这次选的助餐服务的规则（没标服务的规则对所有服务都有效）。"""
    return [p for p in promos if not p.service or not service or p.service == service]


def summary(promos: list[Promo]) -> list[str]:
    """同一服务、同一范围的单档规则合成一行：满¥300享7.8折 / 满¥500享7.4折 / …"""
    groups: dict[tuple, list[Tier]] = {}
    for p in promos:
        groups.setdefault((p.service, p.scope, frozenset(p.codes)), []).extend(p.tiers)
    out = []
    for (_, scope, _), tiers in groups.items():
        tiers = sorted(tiers, key=lambda t: t.threshold_fen)
        out.append(" / ".join(t.text for t in tiers) + {"1": "（指定餐品）", "2": "（个别餐品除外）"}.get(scope, ""))
    return out


def promo_status(promos: list[Promo], lines: list[tuple[str, int]]) -> dict[str, Any]:
    """lines: (餐品编码, 现金部分金额). 返回已满足的最优一档，和离下一档最近的差额。"""
    best: tuple[int, Promo, Tier, int] | None = None
    nxt: tuple[int, Promo, Tier, int] | None = None   # (差额, 规则, 档位, 达到后多省)
    for p in promos:
        eligible = sum(f for code, f in lines if p.covers(code))
        for t in p.tiers:
            s = t.saving(eligible)
            if s and (best is None or s > best[0]):
                best = (s, p, t, eligible)
    current = best[0] if best else 0
    for p in promos:
        eligible = sum(f for code, f in lines if p.covers(code))
        for t in p.tiers:
            gap = t.threshold_fen - eligible
            if gap <= 0:
                continue
            gain = t.saving(t.threshold_fen) - current
            if gain > 0 and (nxt is None or gap < nxt[0]):
                nxt = (gap, p, t, gain)
    return {
        "applied": {"rule": best[2].text, "saving_fen": best[0], "eligible_fen": best[3]} if best else None,
        "next": {"rule": nxt[2].text, "gap_fen": nxt[0], "extra_saving_fen": nxt[3]} if nxt else None,
    }
