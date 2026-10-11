from datetime import date
from types import SimpleNamespace as NS

from mcd_terminal import campaigns as cmp


def row(day, title, intro=""):
    return NS(day=day, tag="", title=title, intro=intro, detail="", image="")


def test_merge_groups_days_and_classifies():
    today = date(2026, 10, 11)
    got = cmp.merge([row("10月10日", "周边联名徽章"), row("10月11日", "麦咖啡拿铁第二杯半价"),
                     row("10月12日", "麦咖啡拿铁第二杯半价"), row("10月20日", "早餐厚松饼上新")], today)
    by = {c.title: c for c in got}
    latte = by["麦咖啡拿铁第二杯半价"]
    assert latte.when == "today" and latte.range == "10/11 – 10/12" and latte.district[1] == "咖啡山丘"
    assert by["早餐厚松饼上新"].when == "soon" and by["早餐厚松饼上新"].district[1] == "早餐小镇"
    assert by["周边联名徽章"].when == "past" and by["周边联名徽章"].toy == "有周边"
    assert [c.when for c in got] == ["today", "soon", "past"]


def test_items_on_menu_prefers_specific_names():
    c = cmp.Campaign("蓝莓爆爆珠麦旋风 配 中份薯条")
    menu = [NS(name=n) for n in ["麦旋风", "蓝莓爆爆珠麦旋风", "中份薯条", "巨无霸"]]
    assert [m.name for m in cmp.items_on_menu(c, menu)] == ["蓝莓爆爆珠麦旋风", "中份薯条"]


def test_find_exact_then_partial():
    cs = [cmp.Campaign("早餐示例"), cmp.Campaign("早餐示例加长版")]
    assert [c.title for c in cmp.find(cs, "早餐示例")] == ["早餐示例"]
    assert len(cmp.find(cs, "早餐")) == 2
