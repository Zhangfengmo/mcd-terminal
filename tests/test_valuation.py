from datetime import date
from decimal import Decimal
from itertools import product

from mcd_terminal.demo import DemoClient
from mcd_terminal.valuation import (
    Account, MarketItem, clean_name, market_item, optimize, parse_coupons, rank,
)


def item(spu, pts, price, cat="1"):
    return MarketItem(spu, 10000 + spu, f"item{spu}", pts, Decimal(price) if price else None, cat)


def brute_force(items, budget, max_each):
    best = (0, 0)
    for counts in product(range(max_each + 1), repeat=len(items)):
        pts = sum(i.points * n for i, n in zip(items, counts))
        if pts <= budget:
            val = sum(i.value_fen * n for i, n in zip(items, counts))
            best = max(best, (val, pts))
    return best


def test_optimize_matches_brute_force():
    items = [item(1, 500, "17"), item(2, 150, "5"), item(3, 400, "12"), item(4, 900, "23.5"), item(5, 1200, "25")]
    for budget in (0, 140, 150, 480, 1000, 1480, 2333, 3260):
        for max_each in (1, 2, 3):
            plan = optimize(items, budget, max_each)
            assert (plan.value_fen, plan.points_used) == brute_force(items, budget, max_each), (budget, max_each)
            assert plan.points_used <= budget
            assert all(n <= max_each for _, n in plan.picks)


def test_optimize_skips_physical_unpriced_and_oversized():
    items = [item(1, 100, "50", cat="2"), item(2, 100, None), item(3, 5000, "999"), item(4, 100, "1")]
    plan = optimize(items, 300, max_each=1)
    assert [i.spu_id for i, _ in plan.picks] == [4]


def test_tie_prefers_spending_more_points():
    # Same value, one costs more points: when points are expiring, use them.
    items = [item(1, 100, "3"), item(2, 300, "3")]
    plan = optimize(items, 300, max_each=1)
    assert plan.value_fen == 300 and plan.points_used == 300


def test_rank_orders_by_value_per_point_and_unpriced_last():
    ranked = rank([item(1, 500, "10"), item(2, 100, None), item(3, 100, "5")])
    assert [i.spu_id for i in ranked] == [3, 1, 2]
    assert ranked[0].fen_per_point == 5.0


def test_account_handles_api_spelling_and_strings():
    acct = Account.from_payload({
        "availablePoint": "7592", "frozenPoint": "30", "currentMouthExpirePoint": "10",
        "nextMouthExpirePoint": "200", "accumulativePoint": "141760.94", "usedPoint": "115474.14",
    })
    assert (acct.available, acct.at_risk, acct.accumulated) == (7592, 210, 141760.94)


def test_parse_coupons_from_documented_format():
    md = (
        "# 您的优惠券列表\n\n共 1 张可用优惠券\n\n## 9.9元薯你最甜\n- **优惠**: ¥9.9 (用券价格)\n"
        "- **有效期**: 2025-12-09 00:00-2026-02-12 23:59\n- **领取时间**: 今日收到\n"
        "- **标签**: 到店专用、外送专用\n\n<img src=\"x\" alt=\"y\">\n"
    )
    [c] = parse_coupons(md)
    assert (c.title, c.price, c.end, c.tags) == ("9.9元薯你最甜", "9.9", date(2026, 2, 12), "到店专用、外送专用")
    assert c.days_left(date(2026, 2, 10)) == 2
    assert parse_coupons("暂无优惠券") == []


def test_market_item_from_documented_payloads():
    listing = {"spuName": "中杯拿铁/美式500积分", "spuId": 542, "point": "500", "downTime": "2026-04-30 23:59:59"}
    detail = {"skuList": [{"skuId": 10997, "points": "500", "extTradePrice": "7"}], "spuCategory": "1"}
    mi = market_item(listing, detail)
    # extTradePrice is "券核销额外支付金额": what you still pay, not what the item is worth
    assert (mi.name, mi.sku_id, mi.points, mi.use_price_fen, mi.ref_fen) == ("中杯拿铁/美式", 10997, 500, 700, None)
    free = market_item(listing, {"skuList": [{"skuId": 1, "points": "500", "extTradePrice": "0"}]})
    assert free.use_price_fen == 0
    assert market_item(listing, None).ref_price is None and market_item(listing, None).use_price_fen is None


def test_on_shelf_window():
    from datetime import datetime
    from mcd_terminal.valuation import on_shelf
    now = datetime(2026, 10, 9, 18, 0)
    assert on_shelf({"upTime": "2026-06-25 00:00:03", "downTime": "2026-12-30 23:59:59"}, now)
    assert not on_shelf({"upTime": "2024-12-31 11:45:03", "downTime": "2026-03-21 23:59:59"}, now)
    assert not on_shelf({"upTime": "2026-11-01 00:00:00", "downTime": ""}, now)
    assert on_shelf({}, now)


def test_points_coupons_are_valued_against_the_store_menu():
    from mcd_terminal.order import MenuItem, price_from_menu
    menu = [MenuItem("1", "可乐麦炫酷", 1350), MenuItem("2", "中杯拿铁", 1700)]
    disc = market_item({"spuName": "6.9元可乐麦炫酷", "spuId": 1, "point": "50"},
                       {"skuList": [{"skuId": 11, "points": "50", "extTradePrice": "6.9"}]})
    bundle = market_item({"spuName": "18.8元2份麦辣鸡翅", "spuId": 2, "point": "200"}, None)
    assert price_from_menu([disc, bundle], menu) == 1
    assert (disc.value_fen, bundle.value_fen) == (660, None)
    assert clean_name("巨无霸 1200 积分") == "巨无霸"


def test_demo_client_redeem_deducts_points():
    c = DemoClient(today=date(2026, 10, 9))
    before = Account.from_payload(c.call("query-my-account")).available
    c.call("mall-create-order", {"skuId": 10542, "count": 2})
    assert Account.from_payload(c.call("query-my-account")).available == before - 1000


def test_discount_coupon_is_valued_by_what_it_saves():
    from mcd_terminal.valuation import MarketItem
    from decimal import Decimal
    d = MarketItem(1, 11, "6.9元可乐麦炫酷", 50, Decimal("13.5"), cat_name="到店专用")
    assert (d.use_price_fen, d.value_fen, d.fen_per_point) == (690, 660, 13.2)
    same = MarketItem(2, 12, "6.9元可乐麦炫酷", 50, Decimal("6.9"))
    assert same.value_fen is None and same.fen_per_point is None
