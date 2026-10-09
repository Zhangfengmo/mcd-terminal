"""Agent support: JSON serialisers for --json output, and the bundled Skill."""
from __future__ import annotations

import shutil
from datetime import date
from importlib import resources
from pathlib import Path
from typing import Any

from .order import OrderPlan
from .valuation import Account, Coupon, MarketItem, Plan


def yuan(fen: int | None) -> float | None:
    return None if fen is None else round(fen / 100, 2)


def account(a: Account) -> dict[str, Any]:
    return {
        "available": a.available, "frozen": a.frozen,
        "expiring_this_month": a.expiring_this_month, "expiring_next_month": a.expiring_next_month,
        "expiring_soon": a.at_risk, "accumulated": a.accumulated, "used": a.used,
    }


def coupon(c: Coupon, today: date) -> dict[str, Any]:
    return {"title": c.title, "price_yuan": float(c.price) if c.price else None,
            "expires": c.end.isoformat() if c.end else None, "days_left": c.days_left(today), "tags": c.tags}


def market_item(i: MarketItem) -> dict[str, Any]:
    return {"name": i.name, "sku_id": i.sku_id, "spu_id": i.spu_id, "points": i.points,
            "ref_price_yuan": yuan(i.ref_fen), "use_price_yuan": yuan(i.use_price_fen),
            "value_yuan": yuan(i.value_fen), "in_store_only": i.in_store_only, "fen_per_point": round(i.fen_per_point, 3) if i.fen_per_point else None,
            "physical": i.is_physical}


def spend_plan(p: Plan) -> dict[str, Any]:
    return {
        "budget_points": p.budget, "points_used": p.points_used, "points_left": p.leftover,
        "value_yuan": yuan(p.value_fen),
        "picks": [{"name": i.name, "sku_id": i.sku_id, "count": n, "points": i.points * n,
                   "value_yuan": yuan((i.value_fen or 0) * n)} for i, n in p.picks],
    }


def order_plan(p: OrderPlan) -> dict[str, Any]:
    lines = []
    for c in p.choices:
        line: dict[str, Any] = {"want": c.unit.want, "item": c.unit.menu.name, "code": c.unit.menu.code,
                                "price_yuan": yuan(c.unit.menu.price_fen), "pay_with": c.kind,
                                "pay_yuan": yuan(c.pay_fen)}
        if c.coupon:
            line["coupon"] = c.coupon.title
        if c.mall:
            line["points"] = c.points
            line["redeem"] = {"name": c.mall.name, "sku_id": c.mall.sku_id}
        lines.append(line)
    return {"original_yuan": yuan(p.original_fen), "pay_yuan": yuan(p.pay_fen),
            "saving_yuan": yuan(p.saving_fen), "points_used": p.points_used,
            "coupons_used": sum(1 for c in p.choices if c.kind == "coupon"), "lines": lines}


def scene(s: Any) -> dict[str, Any]:
    return {"mode": s.mode, "label": s.label, "store": s.store_name, "store_code": s.store_code,
            "address": s.address_text or None, "reservation": s.reservation,
            "service": s.gm_service_name or None}


# ------------------------------------------------------------------ the Skill
def skill_text() -> str:
    return resources.files("mcd_terminal").joinpath("skill/SKILL.md").read_text(encoding="utf-8")


def install_skill(target_dir: str | None) -> Path:
    base = Path(target_dir).expanduser() if target_dir else Path.home() / ".claude" / "skills"
    dest = base / "mcd-terminal"
    dest.mkdir(parents=True, exist_ok=True)
    src = resources.files("mcd_terminal").joinpath("skill/SKILL.md")
    with resources.as_file(src) as p:
        shutil.copyfile(p, dest / "SKILL.md")
    return dest / "SKILL.md"
