"""Offline demo data source.

Responses mirror the formats documented in the official mcd-mcp-server README
(JSON `data` payloads, Markdown for coupon tools), so demo mode exercises the
same parsing and rendering code as live mode. All values are made up.
"""
from __future__ import annotations

import os
import time
from datetime import date, timedelta
from typing import Any

from .client import McdError

# spuId -> (name, points, extTradePrice, spuCategory)
_PRODUCTS: dict[int, tuple[str, int, str, str]] = {
    542: ("中杯拿铁/美式", 500, "17", "1"),
    551: ("麦辣鸡腿堡", 900, "23.5", "1"),
    563: ("中份薯条", 400, "12", "1"),
    570: ("麦乐鸡 5 块", 600, "14.5", "1"),
    588: ("圆筒冰淇淋", 150, "5", "1"),
    590: ("巨无霸", 1200, "25", "1"),
    604: ("早餐猪柳蛋麦满分套餐", 1100, "21", "1"),
    612: ("麦旋风", 700, "15", "1"),
    630: ("汉堡造型钥匙扣", 1800, "39", "2"),
}


def _sku_id(spu_id: int) -> int:
    return 10000 + spu_id


# Store menu: code -> (name, price)
_MENU: dict[str, tuple[str, str]] = {
    "920100": ("巨无霸", "25"),
    "920101": ("巨无霸套餐", "39"),
    "920200": ("中杯拿铁", "17"),
    "920201": ("中杯美式", "15"),
    "920300": ("中份薯条", "12"),
    "920301": ("大份薯条", "14"),
    "920400": ("麦乐鸡 5 块", "14.5"),
    "920500": ("麦辣鸡腿堡", "23.5"),
    "920600": ("圆筒冰淇淋", "5"),
    "920700": ("麦旋风", "15"),
}

# Store promotions shown as menu tags; calculate-price applies them.
_TAGS: dict[str, list[str]] = {"920500": ["第二份半价"]}

# Which menu items a redeemed points-mall coupon covers.
_MALL_COVERS: dict[int, list[str]] = {
    542: ["920200", "920201"], 551: ["920500"], 563: ["920300"], 570: ["920400"],
    588: ["920600"], 590: ["920100"], 612: ["920700"],
}

_STORES = [
    {"storeCode": "1450001", "beCode": "145000101", "storeName": "麦当劳人民广场餐厅",
     "address": "上海市黄浦区西藏中路 268 号", "distance": "320m"},
    {"storeCode": "1450002", "beCode": "145000201", "storeName": "麦当劳南京东路餐厅",
     "address": "上海市黄浦区南京东路 300 号", "distance": "780m"},
]


class DemoClient:
    def __init__(self, today: date | None = None) -> None:
        fixed = os.environ.get("MCD_DEMO_NOW", "")[:10]
        self.today = today or (date.fromisoformat(fixed) if fixed else date.today())
        self.available = 1880
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._orders = 0
        self._draws = 0
        self._won: list[dict[str, Any]] = []
        # couponId -> store coupon (title, code, {productCode: (productName, couponPrice)})
        self._store_coupons: dict[str, tuple[str, str, dict[str, tuple[str, str]]]] = {
            "OWN-NUGGETS": ("11.9元麦乐鸡", "MCDD11NUGGETS", {"C920400": ("麦乐鸡 5 块", "11.9")}),
            "OWN-FRIES": ("9.9元薯你最甜", "MCDD99FRIES", {"C920300": ("中份薯条", "9.9")}),
        }
        try:
            self.delay = float(os.environ.get("MCD_DEMO_DELAY", "0"))
        except ValueError:
            self.delay = 0.0

    def call(self, tool: str, args: dict[str, Any] | None = None) -> Any:
        args = args or {}
        self.calls.append((tool, args))
        if self.delay:
            time.sleep(self.delay)
        handler = getattr(self, "_" + tool.replace("-", "_"), None)
        if handler is None:
            raise McdError(f"演示模式暂不支持工具 {tool}")
        return handler(**args)

    url = "演示数据"

    def list_tools(self) -> list[str]:
        """Every tool this demo answers, named like the live server's tools."""
        return sorted(n[1:].replace("_", "-") for n in dir(self)
                      if n.startswith("_") and not n.startswith("__") and callable(getattr(self, n))
                      and n not in ("_price_items", "_mall_physical", "_group_saving", "_party_detail"))

    def close(self) -> None:
        pass

    # ---- account -------------------------------------------------------
    def _query_my_account(self) -> dict[str, Any]:
        return {
            "availablePoint": str(self.available),
            "accumulativePoint": "17240.5",
            "currency": "麦当劳积分",
            "currentMouthExpirePoint": "0",
            "expiredPoint": "320",
            "frozenPoint": "30",
            "lastMouthExpirePoint": "0",
            "nextMouthExpirePoint": "1480",
            "usedPoint": "15030.5",
        }

    def _query_my_coupons(self) -> str:
        t = self.today
        rows = [
            ("9.9元薯你最甜", "9.9", t - timedelta(days=20), t + timedelta(days=2), "到店专用、外送专用"),
            ("11.9元麦乐鸡", "11.9", t - timedelta(days=5), t + timedelta(days=9), "到店专用"),
            ("早餐 12 元套餐券", "12", t - timedelta(days=1), t + timedelta(days=40), "到店专用、外送专用"),
        ]
        out = [f"# 您的优惠券列表\n\n共 {len(rows)} 张可用优惠券\n"]
        for title, price, start, end, tags in rows:
            out.append(
                f"## {title}\n- **优惠**: ¥{price} (用券价格)\n"
                f"- **有效期**: {start:%Y-%m-%d} 00:00-{end:%Y-%m-%d} 23:59\n"
                f"- **领取时间**: 今日收到\n- **标签**: {tags}\n"
            )
        return "\n".join(out)

    # ---- mall ----------------------------------------------------------
    def _mall_points_products(self, catRuleIds: str | None = None) -> list[dict[str, Any]]:
        return [
            {
                "spuName": f"{name}{pts}积分",
                "spuId": spu,
                "spuImage": "",
                "point": str(pts),
                "shopId": 2,
                "selling": "",
                "upTime": f"{self.today:%Y-%m-01} 00:00:00",
                "downTime": f"{self.today + timedelta(days=60):%Y-%m-%d} 23:59:59",
                "catName": "玩具" if cat == "2" else "到店专用",
                "status": 2,
                "price": "0",
            }
            for spu, (name, pts, _, cat) in _PRODUCTS.items()
        ] + [  # point "0" entries are paid events (parties, tastings)
            {"spuName": "生日派对（演示数据）", "spuId": 701, "spuImage": "", "point": "0", "shopId": 5,
             "selling": "主题装饰、游戏和蛋糕，小朋友的专属生日会", "upTime": "2026-01-01 00:00:00",
             "downTime": f"{self.today + timedelta(days=80):%Y-%m-%d} 23:59:59", "catName": "生日类派对", "status": 2, "price": "58"},
            {"spuName": "小小厨师体验营（演示数据）", "spuId": 702, "spuImage": "", "point": "0", "shopId": 5,
             "selling": "走进后厨，亲手做一个汉堡", "upTime": "2026-01-01 00:00:00",
             "downTime": f"{self.today + timedelta(days=80):%Y-%m-%d} 23:59:59", "catName": "品鉴会", "status": 2, "price": "72"},
        ] + [  # the live listing also keeps items whose window has passed
            {"spuName": "9.9元薯条两件套", "spuId": 598, "spuImage": "", "point": "200", "shopId": 2,
             "selling": "", "upTime": "2026-01-01 00:00:00", "downTime": "2026-03-21 23:59:59",
             "catName": "到店专用", "status": 2, "price": "0"},
        ]

    def _party_detail(self, spu: int) -> dict[str, Any]:
        name, price, ptype = {701: ("生日派对（演示数据）", "58", -1), 702: ("小小厨师体验营（演示数据）", "72", 2)}[spu]
        return {"spuName": name, "spuId": spu, "images": [], "shopId": 5, "partyType": ptype,
                "partyPeople": "6-12", "partyAge": "4-12", "partyRange": 3,
                "note": "<p>1. 派对预约：请提前3天预订</p><p>2. 拼团未在截止前凑够人数将自动取消并退款</p>",
                "spuLimit": {"ruleType": 1, "rule": "", "cycle": 0, "limitCount": -1, "baseCount": 1, "limitSingle": 29},
                "detail": "",
                "skuList": [{"skuId": 20000 + spu, "points": "0", "price": price, "specList": []}], "spuCategory": "1"}

    def _mall_product_detail(self, spuId: int) -> dict[str, Any]:
        if int(spuId) in (701, 702):
            return self._party_detail(int(spuId))
        if int(spuId) not in _PRODUCTS:
            raise McdError("商品已下架")
        name, pts, price, cat = _PRODUCTS[int(spuId)]
        return {
            "spuName": f"{name}{pts}积分",
            "spuId": spuId,
            "images": [],
            "shopId": 2,
            "note": "兑换后 30 天内有效",
            "detail": "",
            # extTradePrice is what you still pay when using the coupon: 0 for these free-item coupons
            "skuList": [{"skuId": _sku_id(int(spuId)), "points": str(pts), "extTradePrice": "0",
                         "price": "0", "specList": []}],
            "categoryRuleId": f"{cat}>9",
            "spuCategory": cat,
        }

    def _mall_create_order(self, skuId: int, count: int = 1, spuCategory: str = "1",
                           addressId: str = "") -> dict[str, Any]:
        spu = int(skuId) - 10000
        if spu not in _PRODUCTS:
            raise McdError(f"skuId {skuId} 不存在")
        if str(spuCategory) == "2":
            return self._mall_physical(spu, count, addressId)
        cost = _PRODUCTS[spu][1] * count
        if cost > self.available:
            raise McdError("积分不足")
        self.available -= cost
        self._orders += 1
        for k in range(count):
            cid = f"PTS-{spu}-{self._orders}-{k + 1}"
            products = {f"P{code}": (_MENU[code][0], "0") for code in _MALL_COVERS.get(spu, [])}
            self._store_coupons[cid] = (f"{_PRODUCTS[spu][0]} 积分兑换券", f"MCDDPTS{spu}{k + 1:02d}", products)
        codes = [f"MCDDEMO{self._orders:02d}{k + 1:02d}{spu:06d}" for k in range(count)]
        return {
            "orderId": f"ECS-DEMO-{self._orders:04d}",
            "coupons": [{"couponId": "DEMO", "couponCodes": codes, "orderItemStatus": 1}],
            "orderStatus": 30,
            "status": 1,
        }

    # ---- 麦麦省 --------------------------------------------------------
    def _available_coupons(self) -> str:
        return (
            "### 麦麦省优惠券列表：\n"
            "- 优惠券标题：11.9元麦乐鸡 \\\n  状态：已领取 \\\n"
            "- 优惠券标题：9.9元薯你最甜 \\\n  状态：未领取 \\\n"
            "- 优惠券标题：13.9元麦辣鸡翅 \\\n  状态：未领取 \\\n"
        )

    def _auto_bind_coupons(self) -> str:
        return (
            "### 🎉 领券结果\n\n**总计**: 2 张优惠券\n**成功**: 2 张\n**失败**: 0 张\n\n"
            "#### ✅ 成功领取的优惠券：\n\n- **9.9元薯你最甜**\n- **13.9元麦辣鸡翅**\n"
        )

    # ---- ordering ------------------------------------------------------
    def _query_nearby_stores(self, searchType: int = 1, beType: int = 1, city: str = "", keyword: str = "") -> list:
        return [dict(st, businessStatus=True, reservation=False) for st in _STORES]

    def _delivery_query_addresses(self) -> dict[str, Any]:
        return {"addresses": [{"addressId": "A1", "contactName": "麦麦", "phone": "152****6666",
                               "fullAddress": "上海市黄浦区人民大道 200 号 3 楼"}]}

    def _delivery_query_stores(self, addressId: str = "", beType: int = 2) -> list:
        return [dict(_STORES[0], businessStatus=True, reservation=False)]

    def _query_meals(self, **_: Any) -> dict[str, Any]:
        return {
            "categories": [{"name": "人气热卖", "meals": [{"code": c, "tags": _TAGS.get(c, [])} for c in _MENU]}],
            "meals": {c: {"name": n, "currentPrice": p} for c, (n, p) in _MENU.items()},
        }

    def _query_store_coupons(self, **_: Any) -> list:
        return [
            {"title": title, "couponId": cid, "couponCode": code,
             "tradeDateTime": f"{self.today:%Y-%m-%d} 00:00:00-{self.today + timedelta(days=30):%Y-%m-%d} 23:59:59",
             "products": [{"productCode": pc, "productName": pn} for pc, (pn, _) in products.items()]}
            for cid, (title, code, products) in self._store_coupons.items()
        ]

    def _price_items(self, items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int, int]:
        rows, original, total = [], 0, 0
        for it in items:
            code, qty = str(it["productCode"]), int(it.get("quantity", 1))
            if code in _MENU:
                name, price = _MENU[code]
                unit = int(float(price) * 100)
                orig = sub = unit * qty
                if "第二份半价" in _TAGS.get(code, []):
                    sub -= (qty // 2) * (unit // 2)
            else:
                cid = str(it.get("couponId", ""))
                if cid not in self._store_coupons or code not in self._store_coupons[cid][2]:
                    raise McdError(f"优惠券 {cid} 不能用于商品 {code}")
                name, cprice = self._store_coupons[cid][2][code]
                menu_code = code[1:]
                orig = int(float(_MENU[menu_code][1]) * 100) * qty
                sub = int(float(cprice) * 100) * qty
            rows.append({"productCode": code, "productName": name, "quantity": qty,
                         "originalSubtotal": orig, "subtotal": sub})
            original += orig
            total += sub
        return rows, original, total

    def _calculate_price(self, items: list[dict[str, Any]], beType: int = 1, storeCode: str = "",
                         gmServiceCode: str = "", **_: Any) -> dict[str, Any]:
        rows, original, total = self._price_items(items)
        if int(beType) == 6:   # 企业团餐：按所选助餐服务的满折
            total -= self._group_saving(rows, storeCode, gmServiceCode)
        delivery = 600 if int(beType) in (2, 6) else 0
        return {
            "productOriginalPrice": original, "productPrice": total,
            "deliveryOriginalPrice": delivery, "deliveryPrice": delivery,
            "originalPrice": original + delivery, "discount": original - total, "price": total + delivery,
            "productList": rows,
            "takeWayList": [] if int(beType) == 2 else [{"code": "eat-in", "title": "堂食", "subtitle": "店内用餐"},
                                                         {"code": "take-out", "title": "外带", "subtitle": "打包带走"}],
            "mealAssistanceList": [],
        }

    def _create_order(self, items: list[dict[str, Any]], storeCode: str = "", beType: int = 1,
                      gmServiceCode: str = "", **_: Any) -> dict[str, Any]:
        price = self._calculate_price(items, beType=beType, storeCode=storeCode, gmServiceCode=gmServiceCode)
        for it in items:  # coupons are consumed by the order
            self._store_coupons.pop(str(it.get("couponId", "")), None)
        self._orders += 1
        oid = f"10309387{self._orders:020d}"
        store = next((st for st in _STORES if st["storeCode"] == storeCode), _STORES[0])
        return {
            "orderId": oid, "payId": f"PAY{self._orders:08d}",
            "payH5Url": f"https://m.mcd.cn/mcp/scanToPay?orderId={oid}",
            "orderDetail": {"orderStatus": "待支付", "storeName": store["storeName"],
                            "realTotalAmount": f"{price['price'] / 100:g}",
                            "totalDiscountAmount": f"{price['discount'] / 100:g}"},
        }

    def _order_list(self) -> dict[str, Any]:
        t = self.today
        combo = ("巨无霸套餐", 1, [("巨无霸", 1), ("中份薯条", 1), ("中杯可口可乐", 1)])
        rows = [
            ("1030938700000000000000000001", "制作中", t, 12, [("巨无霸", 1), ("中杯拿铁", 1)], "25"),
            ("1030938700000000000000000002", "订单已完成", t - timedelta(days=1), 19, [combo], "39"),
            ("1030938700000000000000000003", "订单已完成", t - timedelta(days=2), 8, [("猪柳麦满分", 1), ("中杯美式", 1)], "21"),
            ("1030938700000000000000000000", "已完成", t - timedelta(days=4), 12,
             [("麦辣鸡腿堡", 2), ("中份薯条", 1), ("中杯可口可乐", 1)], "38.5"),
            ("1030938700000000000000000004", "订单已完成", t - timedelta(days=6), 15, [("麦乐鸡 5 块", 2), ("麦旋风", 1)], "36"),
            ("1030938700000000000000000005", "订单已取消", t - timedelta(days=9), 12, [("麦辣鸡腿堡", 1)], "23.5"),
            ("1030938700000000000000000006", "订单已完成", t - timedelta(days=13), 18,
             [("麦辣鸡腿堡", 1), ("大份薯条", 1), ("圆筒冰淇淋", 1)], "42.5"),
            ("1030938700000000000000000007", "订单已完成", t - timedelta(days=20), 12, [combo], "39"),
        ]

        def product(p: tuple) -> dict[str, Any]:
            if len(p) == 3:   # a combo, listed with its parts like the live server does
                name, q, parts = p
                return {"productName": name, "quantity": q,
                        "comboItemList": [{"name": n, "quantity": k, "productCode": ""} for n, k in parts]}
            return {"productName": p[0], "quantity": p[1]}
        return {"list": [
            {"orderId": oid, "orderStatus": st, "createTime": f"{day:%Y-%m-%d} {hh:02d}:21:08",
             "storeCode": _STORES[0]["storeCode"], "storeName": _STORES[0]["storeName"],
             "beType": "1", "orderType": "1", "realTotalAmount": amt,
             "orderProductList": [product(p) for p in items]}
            for oid, st, day, hh, items, amt in rows]}

    def _query_survey_coupon(self, orderId: str) -> dict[str, Any]:
        if not str(orderId).endswith("0000"):
            raise McdError("无匹配的答卷")
        t = self.today
        return {"trade_no": str(orderId), "survey_id": "0002", "status": 1,
                "finish_time": f"{t - timedelta(days=4):%Y-%m-%d} 13:02:11", "overall_satisfaction": 5,
                "satisfaction_description": "非常满意", "coupon_title": "满意度问卷专享 买一送一（演示）",
                "coupon_trade_start_time": f"{t - timedelta(days=4):%Y-%m-%d} 00:00:00",
                "coupon_trade_end_time": f"{t + timedelta(days=3):%Y-%m-%d} 23:59:59",
                "coupon_redeem_status": "可核销", "coupon_available_redeem_count": 1, "coupon_order_food_types": "1"}

    def _cancel_order(self, orderId: str, cancelReasonCode: str = "1") -> dict[str, Any]:
        return {"orderId": orderId, "cancelResult": True}

    # ---- menu extras ---------------------------------------------------
    def _query_meal_detail(self, code: str, **_: Any) -> dict[str, Any]:
        code = str(code)
        if code not in _MENU:
            raise McdError(f"餐品 {code} 不存在")
        name, price = _MENU[code]
        if code == "920101":
            rounds = [
                {"id": 1, "name": "主食", "quantity": 1, "choices": [{"code": "920100", "name": "巨无霸", "quantity": 1}]},
                {"id": 2, "name": "小食", "quantity": 1, "choices": [{"code": "920300", "name": "中份薯条", "quantity": 1}]},
                {"id": 3, "name": "饮料", "quantity": 1, "choices": [{"code": "9300", "name": "中杯可口可乐", "quantity": 1}]},
            ]
        else:
            rounds = [{"id": 1, "name": name, "quantity": 1, "choices": [{"code": code, "name": name, "quantity": 1}]}]
        return {"code": code, "price": price, "rounds": rounds}

    def _list_nutrition_foods(self) -> str:
        rows = [
            ("巨无霸", 2167, 518, 26, 27, 43, 1015, 140),
            ("中份薯条", 1381, 330, 4, 16, 42, 220, 15),
            ("大份薯条", 1724, 412, 5, 20, 53, 275, 18),
            ("麦乐鸡 5 块", 925, 221, 12, 13, 13, 480, 10),
            ("麦辣鸡腿堡", 2181, 521, 25, 26, 46, 1120, 60),
            ("中杯拿铁", 548, 131, 7, 6, 12, 105, 240),
            ("中杯美式", 25, 6, 0, 0, 1, 5, 5),
            ("圆筒冰淇淋", 607, 145, 4, 5, 22, 60, 120),
            ("麦旋风", 1255, 300, 7, 10, 46, 160, 210),
            ("猪柳麦满分", 1288, 308, 16, 16, 24, 781, 213),
            ("中杯可口可乐", 548, 131, 0, 0, 33, 10, 0),
        ]
        head = "{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:\n"
        body = "".join(f"  {n},null,{kj},{kc},{p},{f},{c},{na},{ca}\n" for n, kj, kc, p, f, c, na, ca in rows)
        return f"[{len(rows)}]" + head + body

    # ---- address / group meal -------------------------------------------
    def _delivery_create_address(self, city: str, contactName: str, phone: str, address: str,
                                 addressDetail: str, gender: str = "") -> dict[str, Any]:
        return {"addressId": "A2", "contactName": contactName, "phone": phone[:3] + "****" + phone[-4:],
                "fullAddress": f"{city}{address} {addressDetail}"}

    def _query_meal_assistance(self, **_: Any) -> dict[str, Any]:
        return {
            "mealAssistanceItems": [
                {"gmServiceCode": "GMS001", "gmServiceName": "保鲜速达", "serviceItems": ["准时送达&餐品保温"],
                 "selected": True, "enable": True},
                {"gmServiceCode": "GMS002", "gmServiceName": "专人分餐", "serviceItems": ["独立分装&餐品保温", "送餐到桌/到人"],
                 "enable": True},
            ],
            "promotions": ["保鲜速达: 满300享78折/满500享74折", "专人分餐: 满300享88折/满500享84折"],
        }

    def _query_promotions(self, storeCode: str, orderType: int = 2, beType: int = 6, beCode: str = "",
                          reservationDate: str = "") -> list:
        """Shaped like the live server: one 满折 tier per rule, split by 助餐服务 (gmServiceCode)."""
        if int(beType) != 6:
            raise McdError("仅企业团餐场景可用")
        t = self.today
        rules = [("GMS001", "300", "22"), ("GMS001", "500", "26"), ("GMS002", "300", "12"), ("GMS002", "500", "16")]
        return [{"promotionId": f"DEMO{k:04d}", "promotionType": "33", "ruleCategory": 30, "beTypes": ["6"],
                 "startTime": f"{t:%Y-%m-01} 00:00:00", "endTime": f"{t + timedelta(days=60):%Y-%m-%d} 23:59:59",
                 "gmServiceCode": svc, "products": [{"type": "2", "productCode": "9900016058"}],
                 "ruleDetail": {"orderDiscount": {"discount": off, "startDiscountPoint": th}}}
                for k, (svc, th, off) in enumerate(rules, 1)]

    def _group_saving(self, rows: list[dict[str, Any]], storeCode: str, service: str) -> int:
        from .promos import for_service, parse_promotions, promo_status
        lines = [(r["productCode"], r["subtotal"]) for r in rows if r["productCode"] in _MENU]
        st = promo_status(for_service(parse_promotions(self._query_promotions(storeCode)), service), lines)
        return st["applied"]["saving_fen"] if st["applied"] else 0

    # ---- order tracking ------------------------------------------------
    def _query_order(self, orderId: str) -> dict[str, Any]:
        if str(orderId).endswith("0000"):   # the finished order in order-list
            return {"orderId": orderId, "orderStatus": "已完成", "storeName": _STORES[0]["storeName"],
                    "orderProductList": [{"productName": "麦辣鸡腿堡", "quantity": 2, "price": "35.25"},
                                         {"productName": "中份薯条", "quantity": 1, "price": "12"}],
                    "realTotalAmount": "38.5", "totalDiscountAmount": "8.75", "deliveryInfo": {}, "pickupCode": "A088",
                    "takeWay": "eat-in", "createTime": f"{self.today - timedelta(days=4):%Y-%m-%d} 12:21:08"}
        return {
            "orderId": orderId, "orderStatus": "制作中", "storeName": _STORES[0]["storeName"],
            "orderProductList": [{"productName": "巨无霸", "quantity": 1, "price": "25"},
                                 {"productName": "中杯拿铁", "quantity": 1, "price": "0"}],
            "realTotalAmount": "25", "totalDiscountAmount": "17",
            "deliveryInfo": {}, "pickupCode": "A127", "takeWay": "takeout",
            "createTime": f"{self.today:%Y-%m-%d} 12:21:08",
        }

    # ---- calendar / time -----------------------------------------------
    # ---- party booking (read-only lookups) -------------------------------
    def _query_party_city(self, spuId: int) -> list:
        return [{"code": 310100, "name": "上海市", "initial": "S", "latitude": 31.23, "longitude": 121.47, "sortNo": 1},
                {"code": 110100, "name": "北京市", "initial": "B", "latitude": 39.90, "longitude": 116.40, "sortNo": 2}]

    def _query_party_store(self, code: str, latitude: float | None = None, longitude: float | None = None,
                           spuId: int | None = None) -> list:
        return [{"code": "1450001", "name": "麦当劳人民广场餐厅", "shortName": "人民广场", "address": "西藏中路 268 号",
                 "distance": 1200, "distanceText": "1.2km", "cityName": "上海市", "businessStatus": 1},
                {"code": "1450002", "name": "麦当劳南京东路餐厅", "shortName": "南京东路", "address": "南京东路 300 号",
                 "distance": 2300, "distanceText": "2.3km", "cityName": "上海市", "businessStatus": 1}]

    def _query_party_store_date(self, storeCode: str, spuId: int) -> list:
        # like the live server: bookable from 3 days ahead (the 提前 3 天预订 rule)
        return [{"date": f"{self.today + timedelta(days=k):%Y-%m-%d}", "spuId": spuId, "storeCode": storeCode} for k in (3, 4, 10)]

    def _query_party_store_session(self, storeCode: str, spuId: int, dateStr: str) -> list:
        k = (date.fromisoformat(dateStr) - self.today).days
        joined = {3: 3, 4: 0, 10: 5}.get(k, 0)        # how many already signed up for the morning session
        base = int(spuId) * 100 + k * 10
        return [{"id": base + 1, "timeStart": "10:30", "timeEnd": "12:00", "leftNum": 12 - joined, "partyMin": 6, "partyMax": 12,
                 "price": 5800},
                {"id": base + 2, "timeStart": "14:30", "timeEnd": "16:00", "leftNum": 0, "partyMin": 6, "partyMax": 12, "price": 5800}]

    def _party_order_create(self, partyType: int, spuId: int = 0, skuId: int = 0, code: str = "", storeCode: str = "",
                            dateStr: str = "", id: Any = None, timeStart: str = "", timeEnd: str = "", leftNum: int = 0,
                            count: int = 1, partyTimeInfo: dict[str, Any] | None = None) -> dict[str, Any]:
        if int(partyType) not in (1, 2):
            raise McdError("请选择包场或拼团")
        if not (storeCode and dateStr and id is not None and timeStart):
            raise McdError("场次信息不完整")
        if not leftNum:
            raise McdError("该场次已约满")
        self._orders += 1
        oid = f"PTY{self._orders:010d}"
        price = ((partyTimeInfo or {}).get("price") or 5800) * int(count)    # per person
        return {"orderId": oid, "orderStatus": 10, "status": 1, "amount": f"{price / 100:g}", "point": 0,
                "payH5Url": f"https://m.mcd.cn/mcp/scanToPay?orderId={oid}",
                "goods": [{"spuId": spuId, "skuId": skuId, "count": count, "price": f"{price / 100:g}",
                           "spuName": "生日派对（演示数据）" if int(spuId) == 701 else "派对活动（演示数据）"}]}

    # ---- lottery ------------------------------------------------------------
    def _query_lottery_info(self) -> dict[str, Any]:
        t = self.today
        return {
            "activityCode": "DEMO-LOTTERY", "activityName": "积分抽奖（演示数据）", "activityStatusText": "进行中",
            "beginTime": f"{t - timedelta(days=5):%Y-%m-%d} 00:00:00", "endTime": f"{t + timedelta(days=20):%Y-%m-%d} 23:59:59",
            "drawPoint": "100", "drawTypeText": "消耗积分抽奖", "availableTimes": None, "availablePoint": str(self.available),
            "drawDecision": {"resourceEligible": self.available >= 100, "reason": None if self.available >= 100 else "积分不足",
                             "nextConsumption": {"type": "POINTS", "points": "100", "chances": 0, "text": "本次消耗 100 积分"}},
            "prizes": [{"name": "麦旋风兑换券（演示）", "imageUrl": "", "typeText": "优惠券"},
                       {"name": "汉堡造型钥匙扣（演示）", "imageUrl": "", "typeText": "实物"},
                       {"name": "50 积分（演示）", "imageUrl": "", "typeText": "积分"}],
        }

    def _draw_lottery(self) -> dict[str, Any]:
        if self.available < 100:
            return {"status": {"code": "POINT_NOT_ENOUGH", "message": "积分不足，无法抽奖"}, "win": None, "prizes": None}
        self.available -= 100
        self._draws += 1
        win = self._draws % 2 == 1      # demo: first draw wins, then alternates
        prizes = [{"name": "麦旋风兑换券（演示）", "imageUrl": "", "typeText": "优惠券",
                   "validDateInfo": f"{self.today:%Y-%m-%d} 至 {self.today + timedelta(days=7):%Y-%m-%d} 可用"}] if win else []
        for p in prizes:
            self._won.insert(0, {"id": f"W{self._draws}", "name": p["name"], "imageUrl": "", "prizeType": 1,
                                 "recordTime": f"{self.today:%Y-%m-%d} 12:30:00", "status": 1, "statusText": "可用",
                                 "timeRemindText": "7 天后过期"})
        return {"status": {"code": "SUCCESS", "message": "抽奖成功"}, "win": win, "prizes": prizes,
                "consumePoint": "100", "remainPoint": str(self.available), "remainChance": None}

    def _query_my_prizes(self, pageNum: str = "1", pageSize: str = "10") -> dict[str, Any]:
        t = self.today
        return {"pageNum": 1, "pageSize": int(pageSize), "hasMore": False, "nextCursor": None, "prizes": self._won + [
            {"id": "P1", "name": "圆筒冰淇淋兑换券（演示）", "imageUrl": "", "prizeType": 1,
             "recordTime": f"{t - timedelta(days=2):%Y-%m-%d} 12:03:00", "status": 1, "statusText": "可用",
             "timeRemindText": "5 天后过期"},
            {"id": "P0", "name": "20 积分（演示）", "imageUrl": "", "prizeType": 3,
             "recordTime": f"{t - timedelta(days=9):%Y-%m-%d} 09:41:00", "status": 2, "statusText": "已领取",
             "timeRemindText": None},
        ]}

    def _now_time_info(self) -> dict[str, Any]:
        from datetime import datetime
        fixed = os.environ.get("MCD_DEMO_NOW")
        now = datetime.strptime(fixed, "%Y-%m-%d %H:%M") if fixed else datetime.now()
        return {"formatted": f"{now:%Y-%m-%d %H:%M:%S}", "date": f"{now:%Y-%m-%d}", "year": now.year,
                "month": now.month, "day": now.day, "dayOfWeek": now.strftime("%A").upper(),
                "timezone": "GMT+08:00"}

    def _campaign_calendar(self, specifiedDate: str | None = None) -> str:
        t = self.today
        d = lambda n: f"{(t + timedelta(days=n)).month}月{(t + timedelta(days=n)).day}日"  # noqa: E731
        return (
            f"### 当前时间：{t:%Y-%m-%d} 12:00:00\n### 活动列表：\n"
            f"#### {d(-1)} 往期回顾\n"
            "-   **活动标题**：周边示例活动（演示数据）🎁\\\n    **活动内容介绍**：演示用的示例活动\n"
            f"#### {d(0)} 今日\n"
            "-   **活动标题**：麦辣鸡腿堡第二份半价（演示数据）🍗\\\n"
            "    **活动内容介绍**：演示用的示例活动\n"
            "-   **活动标题**：早餐示例活动（演示数据）☀️\\\n    **活动内容介绍**：演示用的示例活动\n"
            f"#### {d(2)} 即将开始\n"
            "-   **活动标题**：甜品示例活动（演示数据）🍦\\\n    **活动内容介绍**：演示用的示例活动\n"
        )

    # ---- mall orders / physical ----------------------------------------
    def _mall_physical(self, spu: int, count: int, addressId: str) -> dict[str, Any]:
        if not addressId:
            raise McdError("实物商品需要收货地址 addressId")
        cost = _PRODUCTS[spu][1] * count
        if cost > self.available:
            raise McdError("积分不足")
        self.available -= cost
        self._orders += 1
        return {"orderId": f"ECS-DEMO-{self._orders:04d}", "orderStatus": 1, "status": 1,
                "orderDetailVo": {"orderStatusTitle": "待发货", "realTotalPoints": str(cost),
                                  "goods": [{"spuName": _PRODUCTS[spu][0], "count": count}]},
                "addressVO": self._delivery_query_addresses()["addresses"][0]}

    def _mall_order_list(self, lastId: int | None = None, size: int | None = None) -> list:
        t = self.today
        rows = [
            ("ECS1211037028709736448", "已完成", "中杯拿铁/美式", "", 1, "500", t - timedelta(days=3)),
            ("ECS1211037028709736001", "已完成", "麦乐鸡 5 块", "", 1, "600", t - timedelta(days=12)),
            ("ECS1211037028709735550", "已发货", "汉堡造型钥匙扣", "经典款", 1, "2000", t - timedelta(days=30)),
        ]
        return [{"hasNext": False, "lastId": 0, "list": [
            {"orderId": oid, "orderStatusTitle": st, "shopName": "麦麦商城", "totalCount": n,
             "createTime": f"{day:%Y-%m-%d} 10:12:00", "realTotalPoints": pts,
             "goods": [{"spuName": name, "skuName": sku, "count": n}]}
            for oid, st, name, sku, n, pts, day in rows]}]

    def _mall_order_detail(self, orderId: str) -> dict[str, Any]:
        page = self._mall_order_list()[0]["list"]
        hit = next((o for o in page if o["orderId"] == orderId), None)
        if not hit:
            raise McdError(f"没有找到订单 {orderId}")
        return dict(hit, orderStatusSubTitle="感谢兑换", customerServicePhone="4009-200-205",
                    realTotalAmount="0", payTime=hit["createTime"])
