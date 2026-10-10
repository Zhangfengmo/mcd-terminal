"""Games: the real-time ones are simulated tick by tick; the menu ones run on demo data through the same engine."""
import json
import random
from datetime import date

from typer.testing import CliRunner

from mcd_terminal.cli import app
from mcd_terminal.games.fortune import draw
from mcd_terminal.games.fries import ITEMS, TRAY, Fries
from mcd_terminal.games.guess import hint, puzzle
from mcd_terminal.games.kitchen import Kitchen, reel_of
from mcd_terminal.games.stack import Stack
from mcd_terminal.order import MenuItem


def test_fries_catching_scores_and_fire_costs_a_life():
    g = Fries(seed=1)
    g.drops.clear()
    from mcd_terminal.games.fries import Drop, H
    g.drops.append(Drop(g.x, H - 1.2, "burger"))
    g.step(0.1)
    assert g.score == ITEMS["burger"][1] and g.caught["burger"] == 1
    g.drops.append(Drop(g.x + TRAY - 1, H - 1.2, "hot"))
    g.step(0.1)
    assert g.lives == 2 and g.combo == 0
    g.move(-100)
    assert g.x == 0
    for _ in range(3):
        g.drops.append(Drop(0, H - 1.2, "hot"))
        g.step(0.1)
    assert g.over


def test_stack_cuts_overhang_and_ends_on_a_miss():
    g = Stack(seed=2)
    top = g.tower[-1]
    g.moving.x = top.x + 3
    g.drop()
    assert g.layers == 1 and g.tower[-1].w == top.w - 3
    g.moving.x = g.tower[-1].x
    g.drop()
    assert g.perfect == 1 and g.layers == 2
    g.moving.x = g.tower[-1].x + g.tower[-1].w + 1
    g.drop()
    assert g.over


def test_maidle_hints():
    assert hint(2350, 2330) == "hit" and hint(2600, 2330) == "warm_high" and hint(1000, 2330) == "low"


def _kitchen():
    menu = [MenuItem("1", "巨无霸", 2500), MenuItem("2", "中份薯条", 1200), MenuItem("3", "中杯可口可乐", 900),
            MenuItem("4", "麦旋风", 1500), MenuItem("5", "巨无霸套餐", 3900)]
    return Kitchen(None, menu, [], [], 0, {"巨无霸": 518, "中份薯条": 330})


def test_reels_and_rolling_respect_budget():
    assert reel_of("巨无霸套餐") is None and reel_of("中份薯条") == "side" and reel_of("麦旋风") == "sweet"
    k = _kitchen()
    items, plan = k.roll(random.Random(1), ["main", "side", "drink"], max_pay=5000)
    assert [m.name for m in items] == ["巨无霸", "中份薯条", "中杯可口可乐"] and plan.pay_fen == 4600
    assert k.roll(random.Random(1), ["main", "side"], max_pay=100) is None
    assert puzzle(k, date(2026, 10, 10)) == puzzle(k, date(2026, 10, 10))      # same puzzle all day


def test_fortune_is_stable_for_a_day():
    assert draw("2026-10-10", ["巨无霸"]) == draw("2026-10-10", ["巨无霸"])
    assert draw("2026-10-10", [])["lucky"] == "薯条"


def _json(*args):
    res = CliRunner().invoke(app, ["--demo", "--json", *args])
    return json.loads(res.output.strip().splitlines()[-1])


def test_play_json_for_the_web_arcade(tmp_path, monkeypatch):
    monkeypatch.setenv("MCD_HOME", str(tmp_path))
    slot = _json("play", "slot", "--budget", "30")
    assert slot["status"] == "rolled" and slot["combo"]["pay_yuan"] <= 30 and len(slot["combo"]["items"]) == 3
    g = _json("play", "guess")
    assert g["status"] == "puzzle" and g["cart"] and g["answer"]["pay_yuan"] <= g["answer"]["original_yuan"]
    f = _json("play", "fortune")
    assert f["fortune"]["lot"]
    bad = CliRunner().invoke(app, ["--demo", "--json", "play", "fries"])
    assert bad.exit_code != 0
