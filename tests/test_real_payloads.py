"""Parse real (sanitized) responses captured from the live McDonald's MCP server.

The live server wraps its JSON envelope in LLM guidance text, returns some tools as pure
Markdown, and differs from the published docs in places. These fixtures pin that down.
Personal data (account id, nearby stores, trace ids, signed image URLs) has been replaced.
"""
from pathlib import Path

import pytest

from mcd_terminal.client import McdError, parse_payload
from mcd_terminal.content import find_nutrition, parse_calendar, parse_mall_orders, parse_nutrition
from mcd_terminal.ordering import _stores_summary, fmt_distance
from mcd_terminal.valuation import Account, is_claimable, market_item, parse_claimable, parse_coupons

FIX = Path(__file__).parent / "fixtures" / "real"


def load(name):
    return parse_payload((FIX / f"{name}.txt").read_text(encoding="utf-8"), name)


def test_envelope_inside_guidance_text():
    t = load("now-time-info")
    assert t["date"] == "2026-10-09" and t["dayOfWeek"] == "FRIDAY"


def test_account():
    a = Account.from_payload(load("query-my-account"))
    assert (a.available, a.at_risk) == (101, 0)


def test_error_envelope_followed_by_text_raises_the_server_message():
    with pytest.raises(McdError, match="收藏餐厅列表为空"):
        load("query-nearby-stores_favorites")


def test_stores_have_int_distance_and_pickup_has_no_becode():
    stores = load("query-nearby-stores_location")
    assert stores and all(isinstance(s["distance"], int) for s in stores)
    assert all(not s.get("beCode") for s in stores)
    assert all(s.get("beCode") for s in load("query-nearby-stores_drive"))
    lines = _stores_summary(stores)
    assert lines and ("m" in lines[0] or "km" in lines[0])
    assert (fmt_distance(144), fmt_distance(6720), fmt_distance("320m")) == ("144m", "6.7km", "320m")


def test_empty_addresses_and_mall_orders():
    assert load("delivery-query-addresses") == {"addresses": []}
    orders, _ = parse_mall_orders(load("mall-order-list"))
    assert orders == []


def test_my_coupons_markdown():
    coupons = parse_coupons(load("query-my-coupons"))
    assert len(coupons) == 14
    first = coupons[0]
    assert first.title == "麦旋风任选" and first.price == "9.9" and first.end is not None
    assert "到店专用" in first.tags


def test_claimable_status_wording():
    rows = parse_claimable(load("available-coupons"))
    assert rows and {s for _, s in rows} <= {"已领取", "可领取", "未领取", "不可领取", "已领完"} | {s for _, s in rows}
    assert is_claimable("可领取") and is_claimable("未领取") and not is_claimable("已领取")


def test_nutrition_table():
    table = parse_nutrition(load("list-nutrition-foods"))
    assert len(table) > 20
    assert find_nutrition("巨无霸", table) is not None


def test_calendar_markdown():
    assert parse_calendar(load("campaign-calendar"))


def test_points_mall_discount_coupons():
    data = load("mall-points-products")
    listings = [p for cat in (data if isinstance(data, list) else [data]) for p in _products(cat)]
    items = [market_item(p, None) for p in listings]
    by_name = {i.name: i for i in items}
    cola = by_name["6.9元可乐麦炫酷"]
    assert cola.use_price_fen == 690 and cola.single_item and cola.item_name == "可乐麦炫酷"
    assert cola.in_store_only
    for bundle in ("18.8元2份麦辣鸡翅", "16.9元中薯麦乐鸡组合", "28.8元巨无霸四件套", "9.9元指定小食任选"):
        assert not by_name[bundle].single_item, bundle
    assert by_name["罗技键鼠套装"].use_price_fen is None


def _products(node):
    """The listing nests products under categories; collect every dict that has a spuId."""
    if isinstance(node, dict):
        if "spuId" in node:
            yield node
        for v in node.values():
            yield from _products(v)
    elif isinstance(node, list):
        for v in node:
            yield from _products(v)


# ---------------------------------------------------------------- store-level responses
from mcd_terminal.order import names_match, parse_menu, parse_store_coupons  # noqa: E402
from mcd_terminal.ordering import _take_way  # noqa: E402


def test_store_menu():
    menu = parse_menu(load("query-meals"))
    assert len(menu) > 100
    by_name = {m.name: m for m in menu}
    assert by_name["培根安格斯厚牛堡"].price_fen == 3450
    assert any(m.tags for m in menu)


def test_store_coupons_use_coupon_product_codes():
    coupons = parse_store_coupons(load("query-store-coupons"))
    c = coupons[0]
    assert (c.title, c.product_code, c.product_name) == ("麦旋风任选", "9900014239", "麦旋风任选1")
    assert c.expires is not None
    assert names_match(c.product_name, "麦旋风奥利奥") and names_match(c.product_name, "麦旋风")


def test_calculate_price_and_take_way_codes():
    q = load("calculate-price")
    assert (q["productPrice"], q["price"]) == (6800, 6800)
    assert _take_way(q) == "eat-in"


def test_order_list_and_detail():
    rows = load("order-list")["list"]
    assert rows[0]["orderStatus"] == "订单已完成" and rows[0]["orderProductList"][0]["comboItemList"]
    d = load("query-order")
    assert d["pickupCode"] and d["realTotalAmount"] == "63" and d["couponList"]


def test_off_shelf_detail_and_missing_survey_raise_clear_errors():
    with pytest.raises(McdError, match="商品已下架"):
        load("mall-product-detail_off-shelf")
    with pytest.raises(McdError, match="无匹配的答卷"):
        load("query-survey-coupon")


# ---------------------------------------------------------------- commands on real responses
class ReplayClient:
    """Answers each tool with its captured (sanitized) real response."""
    files = {"query-meals": "query-meals", "query-order": "query-order", "order-list": "order-list",
             "query-meal-detail": "query-meal-detail_combo", "mall-points-products": "mall-points-products",
             "mall-product-detail": "mall-product-detail_off-shelf", "query-my-account": "query-my-account",
             "query-my-coupons": "query-my-coupons", "available-coupons": "available-coupons",
             "campaign-calendar": "campaign-calendar", "now-time-info": "now-time-info",
             "list-nutrition-foods": "list-nutrition-foods", "mall-order-list": "mall-order-list"}

    def call(self, tool, args=None):
        if tool not in self.files:
            raise McdError(f"replay has no {tool}")
        return load(self.files[tool])

    def close(self):
        pass


@pytest.fixture
def replay(monkeypatch, tmp_path):
    from mcd_terminal import cli
    monkeypatch.setenv("MCD_HOME", str(tmp_path))
    monkeypatch.setattr(cli.State, "client", property(lambda self: ReplayClient()))
    return cli


def _invoke(cli, *args):
    from typer.testing import CliRunner
    res = CliRunner().invoke(cli.app, list(args), env={"COLUMNS": "120"})
    assert res.exception is None or isinstance(res.exception, SystemExit), res.output
    return res


def test_today_orders_track_on_real_data(replay):
    out = _invoke(replay, "today").output
    assert "101" in out
    out = _invoke(replay, "orders").output
    assert "人气超值四件套随心选" in out and "订单已完成" in out
    import json
    body = json.loads(_invoke(replay, "--json", "track").output)  # no remembered order: uses order-list
    assert body["order"]["pickup_code"] == "12345" and body["order"]["status"] == "订单已完成"
    assert [i["name"] for i in body["order"]["items"]][0] == "人气超值四件套随心选"


def test_market_on_real_data_skips_events_and_expired_items(replay):
    import json
    body = json.loads(_invoke(replay, "--json", "market").output)
    names = {i["name"] for i in body["items"]}
    assert "麦当劳亲子读书会" not in names            # 0-point paid event
    assert "罗技键鼠套装" not in names                # window ended in August
    assert "6.9元可乐麦炫酷" in names                 # on shelf until 2026-12-30


def test_on_shelf_mall_detail_ext_trade_price_is_the_coupon_price():
    detail = load("mall-product-detail_on-shelf")
    listing = {"spuName": "16.9元麦辣可乐组合", "spuId": 17079, "point": "500", "catName": "到店专用"}
    mi = market_item(listing, detail)
    assert (mi.sku_id, mi.points, mi.use_price_fen, mi.is_physical) == (17785, 500, 1690, False)
    assert not mi.single_item and mi.value_fen is None   # a bundle: not valued against single items


# ---------------------------------------------------------------- the user's own first order
def test_not_on_menu_offers_close_items_and_a_zsh_safe_retry(replay, monkeypatch):
    import json
    import sys
    monkeypatch.setattr(sys, "argv", ["mcd", "--json", "order", "巨无霸", "中杯拿铁", "薯条", "麦乐鸡*2", "--dry-run"])
    from mcd_terminal.prefs import Prefs
    Prefs().set("store_pickup", {"code": "9900001", "be": "", "name": "麦当劳示例一路餐厅"})
    body = json.loads(_invoke(replay, "--json", "order", "巨无霸", "中杯拿铁", "薯条", "麦乐鸡*2", "--dry-run").output)
    assert body["status"] == "not_on_menu" and body["missing"] == ["中杯拿铁"]
    assert "麦咖啡™奶铁" in body["alternatives"]["中杯拿铁"]
    assert "麦乐鸡x2" in body["retry_with"] and "*" not in body["retry_with"]


def test_quantity_forms():
    from mcd_terminal.order import parse_wants
    assert parse_wants(["麦乐鸡x2", "麦乐鸡*3", "2份麦乐鸡", "两杯拿铁", "薯条2份", "麦乐鸡5块"]) == [
        ("麦乐鸡", 2), ("麦乐鸡", 3), ("麦乐鸡", 2), ("拿铁", 2), ("薯条", 2), ("麦乐鸡5块", 1)]


def test_no_favourites_falls_back_to_the_last_order_store(replay, tmp_path):
    """Live server: favourites empty -> error 600050. Use the store of the last pickup order."""
    from mcd_terminal.ordering import _store_scene
    from mcd_terminal.prefs import Prefs

    class C(ReplayClient):
        files = dict(ReplayClient.files, **{"query-nearby-stores": "query-nearby-stores_favorites"})
    scene = _store_scene(C(), Prefs(), "pickup", None, None, 1)
    assert (scene.store_code, scene.store_name) == ("9900001", "麦当劳示例一路餐厅")
    assert Prefs().get("store_pickup")["code"] == "9900001"   # remembered for next time


def test_no_favourites_no_orders_uses_the_delivery_address(replay):
    from mcd_terminal.ordering import _store_scene
    from mcd_terminal.prefs import Prefs
    seen = {}

    class C(ReplayClient):
        def call(self, tool, args=None):
            if tool == "order-list":
                return {"list": []}
            if tool == "delivery-query-addresses":
                return {"addresses": [{"addressId": "A1", "fullAddress": "上海市黄浦区人民大道200号 3楼"}]}
            if tool == "query-nearby-stores":
                if args["searchType"] == 1:
                    return load("query-nearby-stores_favorites")
                seen.update(args)
                return load("query-nearby-stores_location")
            return super().call(tool, args)
    scene = _store_scene(C(), Prefs(), "pickup", None, None, 1)
    assert (seen["city"], seen["keyword"]) == ("上海市", "人民大道200号")
    assert scene.store_name == "麦当劳示例一路餐厅"


# ---------------------------------------------------------------- the last four tools, on real responses
class ReplayMore(ReplayClient):
    """Party lookups, lottery, promotions and survey answered with captured (sanitized) responses."""
    files = dict(ReplayClient.files, **{
        "query-party-city": "query-party-city", "query-party-store": "query-party-store",
        "query-party-store-date": "query-party-store-date", "query-party-store-session": "query-party-store-session",
        "query-lottery-info": "query-lottery-info", "query-my-prizes": "query-my-prizes",
        "query-promotions": "query-promotions", "query-survey-coupon": "query-survey-coupon"})
    details = {1830: "mall-product-detail_party-both", 8516: "mall-product-detail_party-private"}

    def call(self, tool, args=None):
        assert tool not in ("party-order-create", "draw-lottery"), "replay must never book or draw"
        if tool == "mall-product-detail" and int((args or {}).get("spuId", 0)) in self.details:
            return load(self.details[int(args["spuId"])])
        return super().call(tool, args)


@pytest.fixture
def replay_more(monkeypatch, tmp_path):
    from mcd_terminal import cli
    monkeypatch.setenv("MCD_HOME", str(tmp_path))
    monkeypatch.setattr(cli.State, "client", property(lambda self: ReplayMore()))
    from datetime import datetime
    monkeypatch.setattr(cli, "_now", lambda: datetime(2026, 10, 9, 20, 0))   # when the party data was captured
    return cli


def _body(cli, *args):
    import json
    return json.loads(_invoke(cli, "--json", *args).output.strip().splitlines()[-1])


def test_real_party_detail_carries_party_type_and_limits():
    both, private = load("mall-product-detail_party-both"), load("mall-product-detail_party-private")
    assert (both["shopId"], both["partyType"], private["partyType"]) == (5, -1, 1)
    assert private["spuLimit"]["baseCount"] == 5 and both["skuList"][0]["price"] == "45"
    s = load("query-party-store-session")[0]
    assert (s["price"], s["partyMin"], s["partyMax"], s["leftNum"]) == (4500, 5, 12, 12)


def test_real_party_listing_and_booking_plan(replay_more):
    body = _body(replay_more, "party", "亲子读书会", "-c", "上海")
    assert body["status"] == "listed" and body["store"]["code"] == "1450713"
    assert body["days"][0]["sessions"][0]["price_yuan"] == 45.0
    base = ["party", "亲子读书会", "-c", "上海", "--book", "--date", "2026-10-13", "--time", "10:30"]
    assert _body(replay_more, *base)["status"] == "choose_type"            # partyType -1: ask
    plan = _body(replay_more, *base, "--type", "拼团", "--count", "2")
    assert plan["status"] == "needs_confirmation"
    assert plan["booking"]["price_per_person_yuan"] == 45.0 and plan["booking"]["total_yuan"] == 90.0
    # 尊享版生日派对: 包场 only, at least 5 people (spuLimit.baseCount)
    vip = ["party", "一起开心鸭尊享版", "-c", "上海", "--book", "--date", "2026-10-13", "--time", "10:30"]
    p = _body(replay_more, *vip)
    assert p["status"] == "needs_confirmation" and p["booking"]["type"] == "包场" and p["booking"]["count"] == 5
    assert p["booking"]["total_yuan"] == 225.0
    assert _body(replay_more, *vip, "--count", "3")["ok"] is False


def test_real_lottery_draw_needs_confirmation(replay_more):
    body = _body(replay_more, "draw")
    assert body["status"] == "needs_confirmation" and body["cost"] == "本次将消耗 24 积分"
    assert body["lottery"]["eligible"] is True and body["lottery"]["prizes"]
    mine = _body(replay_more, "prizes")["my_prizes"]
    assert mine and all(p["status"] for p in mine)


def test_real_group_promotions_split_by_meal_service():
    from mcd_terminal.promos import for_service, parse_promotions, promo_status, summary
    ps = parse_promotions(load("query-promotions"))
    assert len(ps) == 12 and {p.service for p in ps} == {"GMS001", "GMS002", "GMS003"}
    fresh = for_service(ps, "GMS001")
    assert summary(fresh) == ["满¥300享7.8折 / 满¥500享7.4折 / 满¥1000享7折 / 满¥2000享6.6折（个别餐品除外）"]
    st = promo_status(fresh, [("920100", 40000)])
    assert st["applied"]["rule"] == "满¥300享7.8折" and st["applied"]["saving_fen"] == 8800
    assert st["next"]["rule"] == "满¥500享7.4折" and st["next"]["gap_fen"] == 10000


def test_real_survey_without_answer_is_not_an_error(replay_more):
    body = _body(replay_more, "survey", "1030938700000000000000000000")
    assert body["ok"] is True and body["surveys"] == []


def test_real_party_sessions_rank_by_risk(replay_more):
    """Real sessions: min 5, max 12, 12 left (nobody yet). 3 people can't form a group alone; 6 can 包场."""
    few = _body(replay_more, "party", "亲子读书会", "-c", "上海", "--people", "3")
    top = few["recommended"][0]
    assert top["safe"] is False and top["need_more"] == 2 and top["type"] == "拼团"
    assert few["rules"]["advance_days"] == 3 and top["deadline"].endswith("23:59")
    six = _body(replay_more, "party", "亲子读书会", "-c", "上海", "--people", "6")
    assert six["recommended"][0]["safe"] is True and six["recommended"][0]["type"] == "包场"
