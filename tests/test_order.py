import itertools
import random
from decimal import Decimal

from mcd_terminal.content import find_nutrition, parse_calendar, parse_mall_orders, parse_nutrition
from mcd_terminal.order import (
    MenuItem, OwnedCoupon, Unit, match_menu, names_match, parse_menu, parse_store_coupons, parse_wants,
    plan_order,
)
from mcd_terminal.valuation import MarketItem

MENU = [MenuItem("1", "巨无霸", 2500), MenuItem("2", "巨无霸套餐", 3900), MenuItem("3", "中杯拿铁", 1700),
        MenuItem("4", "中杯美式", 1500), MenuItem("5", "中份薯条", 1200), MenuItem("6", "麦乐鸡 5 块", 1450)]


def mall(spu, name, pts, cat="1"):
    return MarketItem(spu, 10000 + spu, name, pts, Decimal("1"), cat)


def coupon(cid, name, price):
    return OwnedCoupon(cid, cid + "-code", f"{price / 100:g}元{name}", "C" + cid, name, price)


def test_parse_wants_and_matching():
    assert parse_wants(["巨无霸*2", "薯条", "拿铁x3", " "]) == [("巨无霸", 2), ("薯条", 1), ("拿铁", 3)]
    assert match_menu("巨无霸", MENU).name == "巨无霸"          # exact beats the combo
    assert match_menu("薯条", MENU).name == "中份薯条"
    assert match_menu("麦乐鸡", MENU).name == "麦乐鸡 5 块"
    assert match_menu("火星披萨", MENU) is None
    assert names_match("中杯拿铁/美式", "中杯美式") and names_match("中杯拿铁/美式500积分", "中杯拿铁")
    assert not names_match("巨无霸", "麦辣鸡腿堡")


def test_documented_payload_parsers():
    menu = parse_menu({"categories": [], "meals": {"920215": {"name": "培根安格斯厚牛堡大套餐", "currentPrice": "55.5"}}})
    assert menu == [MenuItem("920215", "培根安格斯厚牛堡大套餐", 5550)]
    cps = parse_store_coupons([{"title": "外送优惠券二次券", "couponId": "X", "couponCode": "Y",
                                "products": [{"productCode": "P1", "productName": "甜蜜小食1+1"}]}])
    assert (cps[0].coupon_id, cps[0].product_code, cps[0].product_name) == ("X", "P1", "甜蜜小食1+1")
    n = parse_nutrition("[1]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:\n"
                        "  猪柳麦满分,null,1288,308,16,16,24,781,213\n ")
    assert (n[0].name, n[0].kcal, n[0].protein) == ("猪柳麦满分", 308, 16.0)
    assert find_nutrition("猪柳麦满分", n) is n[0]
    cal = parse_calendar("### 当前时间：2025-12-09 14:48:42\n### 活动列表：\n#### 12月9日 今日\n"
                         "-   **活动标题**：⏳倒计时！芝芝火腿扒堡即将回归！\\\n    **活动内容介绍**：🍔松软芝芝\n")
    assert (cal[0].day, cal[0].tag, cal[0].title, cal[0].intro) == ("12月9日", "今日", "⏳倒计时！芝芝火腿扒堡即将回归！", "🍔松软芝芝")
    orders, nxt = parse_mall_orders([{"hasNext": True, "lastId": 81954, "list": [{"orderId": "ECS1"}]}])
    assert orders == [{"orderId": "ECS1"}] and nxt == 81954


def test_owned_coupon_is_not_wasted_when_points_save_more():
    """A ¥2.10 coupon on fries must not block a points redemption that saves ¥12."""
    units = [Unit("薯条", MENU[4])]
    plan = plan_order(units, [coupon("F", "中份薯条", 990)], [mall(563, "中份薯条", 400)], 1000)
    assert plan.choices[0].kind == "points" and plan.pay_fen == 0


def test_mixed_plan_from_demo_numbers():
    units = [Unit("巨无霸", MENU[0]), Unit("拿铁", MENU[2]), Unit("薯条", MENU[4]), Unit("麦乐鸡", MENU[5])]
    owned = [coupon("N", "麦乐鸡 5 块", 1190), coupon("F", "中份薯条", 990)]
    pts = [mall(590, "巨无霸", 1200), mall(542, "中杯拿铁/美式", 500), mall(563, "中份薯条", 400), mall(570, "麦乐鸡 5 块", 600)]
    plan = plan_order(units, owned, pts, 1880)
    assert [c.kind for c in plan.choices] == ["points", "points", "coupon", "coupon"]
    assert (plan.points_used, plan.pay_fen) == (1700, 2180)
    assert [(i.name, n) for i, n in plan.redemptions()] == [("巨无霸", 1), ("中杯拿铁/美式", 1)]


def test_physical_and_unaffordable_mall_items_are_ignored():
    units = [Unit("巨无霸", MENU[0])]
    plan = plan_order(units, [], [mall(1, "巨无霸", 100, cat="2"), mall(2, "巨无霸", 5000)], 1000)
    assert plan.choices[0].kind == "cash" and plan.points_used == 0


def brute(units, owned, malls, budget):
    best = (0, 0)
    options = []
    for u in units:
        opts = [("cash", None, 0, 0)]
        for c in owned:
            if names_match(c.product_name, u.menu.name) and u.menu.price_fen - c.price_fen > 0:
                opts.append(("coupon", c.coupon_id, 0, u.menu.price_fen - c.price_fen))
        for m in malls:
            saving = u.menu.price_fen - (m.use_price_fen or 0)
            if (m.single_item and names_match(m.item_name, u.menu.name) and m.points <= budget
                    and not m.is_physical and saving > 0):
                opts.append(("points", None, m.points, saving))
        options.append(opts)
    for combo in itertools.product(*options):
        ids = [o[1] for o in combo if o[0] == "coupon"]
        pts = sum(o[2] for o in combo)
        if len(ids) != len(set(ids)) or pts > budget:
            continue
        best = max(best, (sum(o[3] for o in combo), -pts))
    return best


def test_plan_matches_brute_force_on_random_carts():
    rng = random.Random(7)
    names = [m.name for m in MENU]
    for _ in range(300):
        units = [Unit(n, next(m for m in MENU if m.name == n)) for n in rng.choices(names, k=rng.randint(1, 5))]
        owned = [coupon(f"c{i}", rng.choice(names), rng.choice([0, 500, 990, 1190, 2000]))
                 for i in range(rng.randint(0, 3))]
        malls = [mall(i, rng.choice(names), rng.choice([150, 400, 500, 600, 900, 1200])) for i in range(rng.randint(0, 4))]
        budget = rng.choice([0, 300, 500, 1000, 1880, 3000])
        plan = plan_order(units, owned, malls, budget)
        assert (plan.saving_fen, -plan.points_used) == brute(units, owned, malls, budget)
        assert plan.points_used <= budget
        used = [c.coupon.coupon_id for c in plan.choices if c.kind == "coupon"]
        assert len(used) == len(set(used))


# ------------------------------------------------------------------ extras
from datetime import date as _date  # noqa: E402

from mcd_terminal.order import suggest_extras  # noqa: E402


def test_menu_tags_and_second_half_promo():
    menu = parse_menu({"categories": [{"name": "热卖", "meals": [{"code": "9", "tags": ["第二份半价"]}]}],
                       "meals": {"9": {"name": "麦辣鸡腿堡", "currentPrice": "23.5"}}})
    assert menu[0].tags == ("第二份半价",) and menu[0].second_half
    plan = plan_order([Unit("麦辣鸡腿堡", menu[0])], [], [], 0)
    [x] = suggest_extras(plan, menu, [], [], 0, _date(2026, 10, 9))
    assert (x.kind, x.pay_fen, x.saving_fen) == ("promo", 1175, 1175)
    plan2 = plan_order([Unit("麦辣鸡腿堡", menu[0])] * 2, [], [], 0)
    assert suggest_extras(plan2, menu, [], [], 0, _date(2026, 10, 9)) == []  # already a pair


def test_leftover_points_and_idle_coupons_are_suggested():
    menu = MENU + [MenuItem("7", "圆筒冰淇淋", 500)]
    fries = coupon("F", "中份薯条", 990)
    fries.expires = _date(2026, 10, 11)
    nuggets = coupon("N", "麦乐鸡 5 块", 1190)
    malls = [mall(590, "巨无霸", 1200), mall(588, "圆筒冰淇淋", 150), mall(542, "中杯拿铁/美式", 500)]
    plan = plan_order([Unit("巨无霸", MENU[0])], [fries, nuggets], malls, 1400)
    assert plan.points_used == 1200
    xs = suggest_extras(plan, menu, [fries, nuggets], malls, 1400, _date(2026, 10, 9))
    # The fries coupon expires in 2 days, so it comes first even though the nuggets one saves more.
    assert [x.kind for x in xs] == ["coupon", "points"]
    assert xs[0].coupon.coupon_id == "F" and xs[0].days_left == 2
    assert xs[1].menu.name == "圆筒冰淇淋" and xs[1].points == 150   # only 200 points left


def test_no_suggestions_when_everything_is_used():
    menu = MENU[:1]
    plan = plan_order([Unit("巨无霸", MENU[0])], [], [mall(590, "巨无霸", 1200)], 1200)
    assert suggest_extras(plan, menu, [], [mall(590, "巨无霸", 1200)], 1200, _date(2026, 10, 9)) == []
