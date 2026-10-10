"""The last four server tools: group-meal promotions, survey coupons, lottery draw, party booking."""
import json
from datetime import date, timedelta

from typer.testing import CliRunner

from mcd_terminal.cli import _survey, app
from mcd_terminal.promos import parse_promotions, promo_status

# shaped like the query-promotions outputSchema
RULES = [
    {"promotionId": "R1", "promotionType": "31", "ruleCategory": 40, "products": [{"productCode": "", "type": "3"}],
     "ruleDetail": {"orderReduce": {"reduceInfo": [{"startDiscountPoint": "100", "reduceAmount": "10"},
                                                   {"startDiscountPoint": "200", "reduceAmount": "30"}]}}},
    {"promotionId": "R2", "promotionType": "33", "ruleCategory": 30,
     "products": [{"productCode": "COFFEE", "type": "2"}],
     "ruleDetail": {"orderDiscount": {"startDiscountPoint": "300", "discount": "30"}}},
]


def test_promotions_parse_reduce_and_discount():
    ps = parse_promotions(RULES)
    assert [p.text for p in ps] == ["满¥100减¥10 / 满¥200减¥30", "满¥300享7折（个别餐品除外）"]
    assert ps[1].covers("BURGER") and not ps[1].covers("COFFEE")


def test_promo_status_picks_best_and_next_tier():
    ps = parse_promotions(RULES)
    st = promo_status(ps, [("BURGER", 15000)])
    assert st["applied"] == {"rule": "满¥100减¥10", "saving_fen": 1000, "eligible_fen": 15000}
    assert st["next"]["rule"] == "满¥200减¥30" and st["next"]["gap_fen"] == 5000 and st["next"]["extra_saving_fen"] == 2000
    # 7 折 beats 满200减30 once reached; coffee doesn't count towards the discount rule
    st = promo_status(ps, [("BURGER", 30000), ("COFFEE", 5000)])
    assert st["applied"]["rule"] == "满¥300享7折" and st["applied"]["saving_fen"] == 9000
    assert promo_status(ps, [])["applied"] is None


def test_promotions_tolerate_odd_payloads():
    assert parse_promotions(None) == [] and parse_promotions({"list": [{"ruleDetail": {}}]}) == []


def test_survey_summary():
    s = _survey({"trade_no": "T1", "overall_satisfaction": 4, "coupon_title": "买一送一", "coupon_redeem_status": "可核销",
                 "coupon_order_food_types": "2", "coupon_trade_end_time": "2026-10-20 23:59:59"}, "T1")
    assert s["satisfaction"] == "满意" and s["usable"] and s["coupon_for"] == "外送"
    used = _survey({"coupon_title": "买一送一", "coupon_redeem_status": "已核销"}, "T2")
    assert not used["usable"] and used["order_id"] == "T2"
    assert _survey({"satisfaction_description": "一般"}, "T3")["usable"] is False


def _json(*args, stdin=None):
    res = CliRunner().invoke(app, ["--demo", "--json", *args], input=stdin)
    return json.loads(res.output.strip().splitlines()[-1])


def test_draw_never_runs_without_confirmation(tmp_path, monkeypatch):
    monkeypatch.setenv("MCD_HOME", str(tmp_path))
    body = _json("draw")
    assert body["status"] == "needs_confirmation" and body["cost"] == "本次消耗 100 积分"
    assert "--yes" in body["confirm_with"]   # (built from sys.argv, which is pytest's here)


def test_party_booking_sends_every_session_field(tmp_path, monkeypatch):
    monkeypatch.setenv("MCD_HOME", str(tmp_path))
    from mcd_terminal import cli
    from mcd_terminal.demo import DemoClient
    seen = {}

    class Spy(DemoClient):
        def _party_order_create(self, **kw):
            seen.update(kw)
            return super()._party_order_create(**kw)
    monkeypatch.setattr(cli.State, "client", property(lambda self: Spy()))
    body = _json("party", "生日派对", "-c", "上海", "--book", "--date", (date.today() + timedelta(days=3)).isoformat(), "--time", "10:30",
                 "--type", "拼团", "--count", "2", "-y")
    assert body["status"] == "booked", body
    assert seen["partyType"] == 2 and seen["count"] == 2 and seen["code"] == "310100"
    assert seen["storeCode"] == "1450001" and seen["id"] == 70131 and seen["timeStart"] == "10:30" and seen["leftNum"] == 9
    assert seen["skuId"] == 20701 and seen["partyTimeInfo"]["partyMin"] == 6
