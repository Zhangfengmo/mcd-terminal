"""Store/address selection and the mixed points + cash checkout flow."""
from __future__ import annotations

import re
from datetime import datetime

from dataclasses import dataclass, field
from typing import Any, Callable

from rich.text import Text

from . import render as ui
from .client import McdError
from .order import (
    MenuItem, OrderPlan, OwnedCoupon, Unit, match_menu, names_match, parse_menu, parse_store_coupons,
    plan_order, similar_items,
)
from .prefs import Prefs
from .valuation import MarketItem, market_item, on_shelf

MODES = {
    # mode: (beType, orderType, label)
    "pickup": (1, 1, "到店自取"),
    "drive": (5, 1, "得来速"),
    "delivery": (2, 2, "麦乐送"),
    "group": (6, 2, "企业团餐"),
}


@dataclass
class Scene:
    mode: str
    store_code: str
    be_code: str
    store_name: str
    address_id: str | None = None
    address_text: str = ""
    reservation: str | None = None
    gm_service: str | None = None
    gm_service_name: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def be_type(self) -> int:
        return MODES[self.mode][0]

    @property
    def order_type(self) -> int:
        return MODES[self.mode][1]

    @property
    def label(self) -> str:
        return MODES[self.mode][2]

    def params(self) -> dict[str, Any]:
        p: dict[str, Any] = {"storeCode": self.store_code, "orderType": self.order_type, "beType": self.be_type}
        # Server rule: pickup (beType=1) must NOT send beCode; drive-thru, delivery and group must.
        if self.be_code and self.mode != "pickup":
            p["beCode"] = self.be_code
        if self.reservation:
            p["reservationDate"] = self.reservation
        return p


def fmt_distance(d: Any) -> str:
    """The server returns metres as a number (docs showed a string); show 320m / 6.7km."""
    if isinstance(d, (int, float)):
        return f"{d / 1000:.1f}km" if d >= 1000 else f"{int(d)}m"
    return str(d or "")


def _rows(data: Any, key: str = "list") -> list[dict[str, Any]]:
    if isinstance(data, dict):
        data = data.get(key) or data.get("list") or data.get("records") or []
    return data if isinstance(data, list) else []


# ------------------------------------------------------------------ scene
def pick_scene(client: Any, prefs: Prefs, mode: str, city: str | None, near: str | None,
               address: str | None, at: str | None, service: str | None, pick: int = 1) -> Scene:
    if mode in ("delivery", "group"):
        scene = _delivery_scene(client, prefs, mode, address, pick)
    else:
        scene = _store_scene(client, prefs, mode, city, near, pick)
    scene.reservation = at
    if mode == "group":
        _pick_service(client, scene, service)
    return scene


def _store_scene(client: Any, prefs: Prefs, mode: str, city: str | None, near: str | None, pick: int) -> Scene:
    be_type = MODES[mode][0]
    remembered = prefs.get(f"store_{mode}")
    if not near and remembered:
        ui.step("还是上次那家", f"{remembered['name']}（想换门店加 --near 地点）")
        return Scene(mode, remembered["code"], remembered["be"], remembered["name"])

    if near:
        city = city or prefs.get("city")
        if not city:
            raise McdError("按位置找门店需要城市，例如：--city 上海 --near 人民广场")
        stores = _search_stores(client, be_type, city, near)
        if not stores:
            raise McdError("附近没找到营业中的门店，换个地点试试")
        prefs.set("city", city)
        return _remember_store(prefs, mode, stores, pick)

    # Nothing remembered and no place given. The MCP can't search by GPS, so try, in order:
    # favourite stores → the store of your last order → near your delivery address → ask once.
    try:
        stores = _open(_rows(client.call("query-nearby-stores", {"searchType": 1, "beType": be_type})))
    except McdError:
        stores = []
    if stores:
        ui.tool_line("query-nearby-stores")
        ui.result(_stores_summary(stores)[0] + "（收藏的门店）")
        return _remember_store(prefs, mode, stores, pick)

    last = _last_order_store(client, be_type)
    if last:
        ui.step("用你上次点餐的门店", f"{last['name']}（想换门店加 --near 地点）")
        prefs.set(f"store_{mode}", last)
        return Scene(mode, last["code"], last["be"], last["name"])

    place = _place_from_address(client) or _ask_place()
    if place:
        city, kw = place
        stores = _search_stores(client, be_type, city, kw)
        if stores:
            prefs.set("city", city)
            return _remember_store(prefs, mode, stores, pick)
    raise McdError("还不知道你在哪。告诉我城市和附近的地点，例如：--city 上海 --near 人民广场（之后会记住）")


def _open(stores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [s for s in stores if s.get("businessStatus", True)] or stores


def _search_stores(client: Any, be_type: int, city: str, near: str) -> list[dict[str, Any]]:
    args = {"searchType": 2, "beType": be_type, "city": city, "keyword": near}
    return _open(_rows(ui.call(client, "query-nearby-stores", args, summary=lambda d: _stores_summary(_rows(d)))))


def _remember_store(prefs: Prefs, mode: str, stores: list[dict[str, Any]], pick: int) -> Scene:
    st = stores[min(max(pick, 1), len(stores)) - 1]
    prefs.set(f"store_{mode}", {"code": st["storeCode"], "be": st.get("beCode", ""), "name": st["storeName"]})
    return Scene(mode, str(st["storeCode"]), str(st.get("beCode", "")), st["storeName"],
                 extra={"address": st.get("address", ""), "distance": st.get("distance", "")})


def _last_order_store(client: Any, be_type: int) -> dict[str, str] | None:
    """Store of the most recent order of the same kind (order-list carries storeCode and beCode)."""
    try:
        rows = _rows(client.call("order-list"))
    except McdError:
        return None
    ui.tool_line("order-list")
    for o in rows:
        if str(o.get("beType", "")) == str(be_type) and o.get("storeCode"):
            ui.result(f"最近一单在 {o.get('storeName', '')}（{str(o.get('createTime', ''))[:10]}）")
            return {"code": str(o["storeCode"]), "be": str(o.get("beCode") or ""), "name": str(o.get("storeName", ""))}
    ui.result("还没有到店点过餐")
    return None


def _place_from_address(client: Any) -> tuple[str, str] | None:
    """('上海', '人民大道 200 号') from the first saved delivery address, if any."""
    try:
        addrs = _rows(client.call("delivery-query-addresses"), "addresses")
    except McdError:
        return None
    for a in addrs:
        full = str(a.get("fullAddress") or "")
        m = re.match(r"^(.+?市)(?:.+?[区县])?(.+)$", full)
        if m:
            ui.step("按你的收货地址找附近门店", full)
            return m.group(1), m.group(2).split(" ")[0]
    return None


def _ask_place() -> tuple[str, str] | None:
    answer = ui.ask_text("你在哪个城市、哪附近？我帮你找最近的麦当劳（只问这一次）", "例如：上海 人民广场")
    if not answer:
        return None
    parts = answer.replace("，", " ").replace(",", " ").split()
    if len(parts) < 2:
        return None
    return parts[0], " ".join(parts[1:])


def _stores_summary(stores: list[dict[str, Any]]) -> list[str]:
    if not stores:
        return ["没有找到门店"]
    first = stores[0]
    dist = f" · {fmt_distance(first.get('distance'))}" if first.get("distance") not in (None, "") else ""
    out = [f"找到 {len(stores)} 家，选了最近的 {first['storeName']}{dist}"]
    return out


def _delivery_scene(client: Any, prefs: Prefs, mode: str, address: str | None, pick: int) -> Scene:
    addrs = _rows(ui.call(client, "delivery-query-addresses",
                          summary=lambda d: f"{len(_rows(d, 'addresses'))} 个收货地址"), "addresses")
    if not addrs:
        raise McdError("麦乐送要先有一个收货地址，加一个（只需一次）：mcd address add --city 上海市 --name 你的名字 --phone 手机号 --street 小区或楼宇 --detail 门牌号")
    want = address or prefs.get("address_id")
    addr = next((a for a in addrs if str(a.get("addressId")) == str(want)), addrs[0])
    prefs.set("address_id", str(addr["addressId"]))
    prefs.set("address_text", str(addr.get("fullAddress") or ""))
    who = " ".join(x for x in (str(addr.get("contactName") or ""), str(addr.get("phone") or "")) if x)
    if who:
        prefs.set("address_contact", who)
    stores = _rows(ui.call(
        client, "delivery-query-stores", {"addressId": addr["addressId"], "beType": MODES[mode][0]},
        summary=lambda d: f"送到 {addr.get('fullAddress', '')}" + (
            f"，由 {_rows(d)[0]['storeName']} 配送" if _rows(d) else "，暂无门店可配送")))
    if not stores:
        raise McdError("这个地址附近暂时没有可配送的门店")
    st = stores[min(max(pick, 1), len(stores)) - 1]
    return Scene(mode, str(st["storeCode"]), str(st.get("beCode", "")), st["storeName"],
                 address_id=str(addr["addressId"]), address_text=addr.get("fullAddress", ""))


def _pick_service(client: Any, scene: Scene, service: str | None) -> None:
    args = {"storeCode": scene.store_code, "beCode": scene.be_code, "beType": 6, "orderType": 2}
    if scene.reservation:
        args["reservationDate"] = scene.reservation
    data = ui.call(client, "query-meal-assistance", args) or {}
    items = [i for i in data.get("mealAssistanceItems") or [] if i.get("enable", True)]
    if not items:
        raise McdError("这家门店暂不支持团餐助餐服务")
    chosen = next((i for i in items if service and service in i.get("gmServiceName", "")), None) \
        or next((i for i in items if i.get("selected")), items[0])
    scene.gm_service = chosen["gmServiceCode"]
    scene.gm_service_name = chosen.get("gmServiceName", "")
    promo = next((p for p in data.get("promotions") or [] if scene.gm_service_name in p), "")
    ui.result(f"助餐服务：{scene.gm_service_name}（{'、'.join(chosen.get('serviceItems') or [])}）",
              *([promo] if promo else []))


def group_promotions(client: Any, scene: Scene) -> list[Any]:
    """团餐门店当前的满减 / 满折规则（只有企业团餐有）。拿不到就当没有，不挡下单。"""
    from .promos import for_service, parse_promotions, summary
    if scene.mode != "group":
        return []
    args = dict(scene.params(), orderType=2, beType=6)

    def line(d: Any) -> str:
        ps = for_service(parse_promotions(d), scene.gm_service)
        if not ps:
            return "这家门店现在没有团餐满减满折"
        return (f"{scene.gm_service_name}：" if scene.gm_service_name else "团餐优惠：") + "；".join(summary(ps))
    try:
        data = ui.call(client, "query-promotions", args, summary=line)
    except ui.ShownError:
        return []
    return for_service(parse_promotions(data), scene.gm_service)


# ------------------------------------------------------------------ menu
def load_menu(client: Any, scene: Scene) -> list[MenuItem]:
    data = ui.call(client, "query-meals", scene.params(),
                   summary=lambda d: f"{scene.store_name} 现在有 {len(parse_menu(d))} 款餐品")
    return parse_menu(data)


def resolve_units(wants: list[tuple[str, int]], menu: list[MenuItem]) -> list[Unit]:
    units: list[Unit] = []
    missing: list[str] = []
    for want, qty in wants:
        item = match_menu(want, menu)
        if item is None:
            missing.append(want)
            continue
        units += [Unit(want, item) for _ in range(qty)]
    if missing:
        raise NotOnMenu(missing, {w: [m.name for m in similar_items(w, menu)] for w in missing})
    return units


class NotOnMenu(McdError):
    """Some wanted items aren't sold here; carries close alternatives for each."""

    def __init__(self, missing: list[str], alternatives: dict[str, list[str]]) -> None:
        self.missing, self.alternatives = missing, alternatives
        parts = []
        for w in missing:
            alts = alternatives.get(w) or []
            parts.append(f"「{w}」" + (f"，相近的有 {'、'.join(alts)}" if alts else ""))
        tail = "" if all(alternatives.get(w) for w in missing) else "，用 mcd menu 看看都有什么吧"
        super().__init__("这家店没有" + "；".join(parts) + tail)


# ------------------------------------------------------------------ coupons / points
EXTRA_LOOKUPS = 4  # extra calculate-price / mall-product-detail calls for "you could also add" ideas


def owned_coupons(client: Any, scene: Scene, units: list[Unit],
                  menu: list[MenuItem] | None = None) -> tuple[list[OwnedCoupon], set[str]]:
    """Coupons usable at this store, priced via calculate-price, and every coupon id seen.

    Coupons for the wanted items are always priced; a few others that match the menu are
    priced too so we can suggest adding them.
    """
    coupons = parse_store_coupons(ui.call(
        client, "query-store-coupons", scene.params(),
        summary=lambda d: f"本店能用 {len({c.coupon_id for c in parse_store_coupons(d)})} 张券"))
    all_ids = {c.coupon_id for c in coupons}
    relevant = [c for c in coupons if any(names_match(c.product_name or c.title, u.menu.name) for u in units)]
    if menu:
        others = [c for c in coupons if c not in relevant
                  and any(names_match(c.product_name or c.title, m.name) for m in menu)]
        relevant += others[:EXTRA_LOOKUPS]
    if not relevant:
        return [], all_ids
    with ui.thinking("算券中") as spin:
        for n, c in enumerate(relevant, 1):
            spin.detail = f"({n}/{len(relevant)}) {c.title}"
            try:
                price = client.call("calculate-price", dict(scene.params(), **_gm(scene), items=[
                    {"productCode": c.product_code, "quantity": 1, "couponId": c.coupon_id,
                     "couponCode": c.coupon_code}]))
                c.price_fen = int((price or {}).get("productPrice"))
            except (McdError, TypeError, ValueError):
                c.price_fen = None
    ui.tool_line("calculate-price", times=len(relevant))
    ui.result(f"试算了 {len(relevant)} 张相关券的用券价")
    return relevant, all_ids


def _spends_points(row: dict[str, Any]) -> bool:
    """Point "0" entries are paid events (parties, tastings), not something points buy."""
    try:
        return float(row.get("point") or 0) > 0
    except (TypeError, ValueError):
        return False


def _item_part(row: dict[str, Any]) -> str:
    """"6.9元可乐麦炫酷" -> "可乐麦炫酷", so the price prefix doesn't block a name match."""
    return re.sub(r"^\s*\d+(?:\.\d+)?\s*元", "", str(row.get("spuName", ""))).strip()


def mall_options(client: Any, units: list[Unit], menu: list[MenuItem] | None = None) -> list[MarketItem]:
    listings = _rows(ui.call(client, "mall-points-products",
                             summary=lambda d: f"积分商城共 {len(_rows(d))} 个可兑换商品"))
    now = datetime.now()
    listings = [r for r in listings if _spends_points(r) and on_shelf(r, now)]
    relevant = [r for r in listings if any(names_match(_item_part(r), u.menu.name) for u in units)]
    if menu:  # a few more that this store sells, for "leftover points could get you…" ideas
        others = [r for r in listings if r not in relevant
                  and any(names_match(_item_part(r), m.name) for m in menu)]
        relevant += others[:EXTRA_LOOKUPS]
    items: list[MarketItem] = []
    if not relevant:
        return items
    with ui.thinking("比价中") as spin:
        for n, row in enumerate(relevant, 1):
            spin.detail = f"({n}/{len(relevant)}) {row.get('spuName', '')}"
            try:
                detail = client.call("mall-product-detail", {"spuId": int(row["spuId"])})
            except (McdError, KeyError, ValueError):
                detail = None
            items.append(market_item(row, detail))
    ui.tool_line("mall-product-detail", times=len(relevant))
    ui.result(f"找到 {len(items)} 个本店能用积分兑换的商品")
    return items


def _gm(scene: Scene) -> dict[str, Any]:
    return {"gmServiceCode": scene.gm_service} if scene.gm_service else {}


# ------------------------------------------------------------------ checkout
def checkout(client: Any, scene: Scene, plan: OrderPlan, prefs_take_way: str | None = None) -> dict[str, Any]:
    """Redeem the planned points coupons, price the cart, and create the order."""
    before: set[str] = set(plan.known_coupon_ids)
    new_coupons: list[tuple[str, str]] = []  # (couponId, couponCode) straight from redemption
    for item, n in plan.redemptions():
        def summary(d: Any, item: MarketItem = item, n: int = n) -> str:
            return f"用 {item.points * n:,} 积分换到 {item.name} x{n}"
        data = ui.call(client, "mall-create-order", {"skuId": int(item.sku_id), "count": n, "spuCategory": "1"},
                       summary=summary) or {}
        for cp in data.get("coupons") or []:
            for code in cp.get("couponCodes") or [""]:
                new_coupons.append((str(cp.get("couponId", "")), str(code)))

    # Find the freshly redeemed coupons in this store's coupon list.
    fresh: list[OwnedCoupon] = []
    if plan.redemptions():
        all_now = parse_store_coupons(ui.call(client, "query-store-coupons", scene.params(),
                                              summary=lambda d: "刚兑换的券已到账"))
        fresh = [c for c in all_now if c.coupon_id not in before]

    items: list[dict[str, Any]] = []
    cash: dict[str, int] = {}
    used: set[str] = set()
    for c in plan.choices:
        if c.kind == "coupon" and c.coupon:
            items.append({"productCode": c.coupon.product_code, "quantity": 1,
                          "couponId": c.coupon.coupon_id, "couponCode": c.coupon.coupon_code})
        elif c.kind == "points":
            hit = next((f for f in fresh if f.coupon_id not in used and names_match(f.product_name, c.unit.menu.name)), None)
            if hit:
                used.add(hit.coupon_id)
                items.append({"productCode": hit.product_code, "quantity": 1,
                              "couponId": hit.coupon_id, "couponCode": hit.coupon_code})
            elif new_coupons:  # fall back to the ids returned by the redemption itself
                cid, code = new_coupons.pop(0)
                items.append({"productCode": c.unit.menu.code, "quantity": 1, "couponId": cid, "couponCode": code})
            else:
                cash[c.unit.menu.code] = cash.get(c.unit.menu.code, 0) + 1
        else:
            cash[c.unit.menu.code] = cash.get(c.unit.menu.code, 0) + 1
    items += [{"productCode": code, "quantity": q} for code, q in cash.items()]

    base = dict(scene.params(), **_gm(scene))
    price = ui.call(client, "calculate-price", dict(base, items=items), summary=_price_summary) or {}
    order_args = dict(base, items=items)  # create-order requires orderType too
    if scene.address_id:
        order_args["addressId"] = scene.address_id
    take_way = _take_way(price, prefs_take_way)
    if scene.order_type == 1 and take_way:
        order_args["takeWayCode"] = take_way
    order = ui.call(client, "create-order", order_args,
                    summary=lambda d: f"订单 {(d or {}).get('orderId', '—')} · 待支付") or {}
    order["_price"] = price
    return order


def _price_summary(d: Any) -> str:
    d = d or {}
    try:
        s = f"实付 {ui.yuan(int(d.get('price')))}"
        if d.get("discount"):
            s += f"，优惠 {ui.yuan(int(d['discount']))}"
        if d.get("deliveryPrice"):
            s += f"（含配送费 {ui.yuan(int(d['deliveryPrice']))}）"
        return s
    except (TypeError, ValueError):
        return "价格已计算"


TAKE_WAYS = {"堂食": ("eat-in", "堂食"), "外带": ("out", "外带", "打包")}


def _take_way(price: dict[str, Any], prefer: str | None = None) -> str | None:
    """Code for how to take the food; the saved preference (堂食 / 外带) if the store offers it."""
    if prefer in TAKE_WAYS:
        for tw in price.get("takeWayList") or []:
            if isinstance(tw, dict):
                code = str(tw.get("takeWayCode") or tw.get("code") or "")
                text = f"{code} {tw.get('title', '')} {tw.get('takeWayDesc', '')} {tw.get('subtitle', '')}"
                if code and any(k in text for k in TAKE_WAYS[prefer]):
                    return code
    for tw in price.get("takeWayList") or []:
        if isinstance(tw, dict):
            code = tw.get("takeWayCode") or tw.get("code")
            if code:
                return str(code)
        elif isinstance(tw, str):
            return tw
    return None


def remember_order(prefs: Prefs, order_id: str) -> None:
    recent = [o for o in prefs.get("recent_orders", []) if o != order_id]
    prefs.set("recent_orders", ([order_id] + recent)[:5])


def scene_line(scene: Scene) -> Text:
    t = Text.assemble((scene.label, f"bold {ui.ACCENT}"), (" · ", ui.FAINT), (scene.store_name, ""))
    if scene.address_text:
        t.append(f" → {scene.address_text}", style=ui.DIM)
    if scene.reservation:
        t.append(f" · 预约 {scene.reservation}", style=ui.AMBER)
    if scene.gm_service_name:
        t.append(f" · {scene.gm_service_name}", style=ui.DIM)
    return t


Fetch = Callable[..., Any]


# ------------------------------------------------------------------ campaigns & live quote
def related_campaigns(client: Any, menu: list[MenuItem], units: list[Unit]) -> list[dict[str, Any]]:
    """Today's campaigns from the calendar that mention something on this store's menu."""
    from .content import parse_calendar

    def summary(d: Any) -> str:
        today = [x for x in parse_calendar(d) if x.tag.startswith("今")]
        return f"今天有 {len(today)} 个活动"
    try:
        items = parse_calendar(ui.call(client, "campaign-calendar", summary=summary))
    except ui.ShownError:
        return []  # campaigns are a nice-to-have; never block an order on them
    cart = {u.menu.name for u in units}
    out: list[dict[str, Any]] = []
    for x in items:
        if not x.tag.startswith("今"):
            continue
        text = f"{x.title} {x.intro}"
        hits = [m.name for m in menu if len(m.name) >= 2 and m.name in text]  # "派" would match "派对"
        if hits:
            out.append({"title": x.title, "items": hits, "in_cart": any(h in cart for h in hits)})
    # what's in the cart first; then at most two others, as ideas
    mine = [c for c in out if c["in_cart"]]
    return mine + [c for c in out if not c["in_cart"]][:max(0, 2 - len(mine))]


def quote(client: Any, scene: Scene, plan: OrderPlan) -> dict[str, Any] | None:
    """Live price for the cash + owned-coupon part of the cart (points lines are redeemed at checkout).

    Includes store promotions, delivery fee and group-meal discounts, which our estimate can't know.
    """
    items: list[dict[str, Any]] = []
    cash: dict[str, int] = {}
    points_lines = 0
    for c in plan.choices:
        if c.kind == "coupon" and c.coupon:
            items.append({"productCode": c.coupon.product_code, "quantity": 1,
                          "couponId": c.coupon.coupon_id, "couponCode": c.coupon.coupon_code})
        elif c.kind == "points":
            points_lines += 1
        else:
            cash[c.unit.menu.code] = cash.get(c.unit.menu.code, 0) + 1
    items += [{"productCode": code, "quantity": q} for code, q in cash.items()]
    if not items:
        return {"pay_fen": 0, "delivery_fen": 0, "promo_fen": 0, "points_lines": points_lines}

    def summary(d: Any) -> str:
        d = d or {}
        try:
            s = f"实时核价：现金部分 {ui.yuan(int(d['price']))}"
            if int(d.get("deliveryPrice") or 0):
                s += f"（含配送费 {ui.yuan(int(d['deliveryPrice']))}）"
            return s
        except (KeyError, TypeError, ValueError):
            return "已核价"
    d = ui.call(client, "calculate-price", dict(scene.params(), **_gm(scene), items=items), summary=summary) or {}
    try:
        pay = int(d["price"])
    except (KeyError, TypeError, ValueError):
        return None
    expected = sum(c.pay_fen for c in plan.choices if c.kind != "points")
    delivery = int(d.get("deliveryPrice") or 0)
    return {"pay_fen": pay, "delivery_fen": delivery,
            "promo_fen": max(0, expected + delivery - pay), "points_lines": points_lines}
