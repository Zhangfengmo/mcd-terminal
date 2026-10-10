"""`mcd` — 麦麦交易终端: your McDonald's points, coupons and orders in one warm terminal."""
from __future__ import annotations

import json
import os
import re
import shlex
import sys
import time
from datetime import date, datetime, timedelta
from typing import Any, Callable, List, Optional

import typer
from rich.text import Text

from . import agent
from . import render as ui
from .client import McdClient, McdError
from .content import (
    find_nutrition, goods_text, parse_calendar, parse_mall_orders, parse_nutrition, status_hint,
)
from .demo import DemoClient
from .order import Unit, parse_menu, parse_wants, plan_order, price_from_menu, suggest_extras
from .ordering import (
    NotOnMenu, checkout, fmt_distance, group_promotions, load_menu, mall_options, owned_coupons, pick_scene, quote,
    related_campaigns, remember_order, resolve_units, scene_line,
)
from . import __version__
from .prefs import Prefs, clear_token, load_token, prefs_path, save_token, token_path
from .valuation import (
    Account, MarketItem, Plan, is_claimable, market_item, on_shelf, optimize, parse_bind_result,
    parse_claimable, parse_coupons, rank,
)


def _utf8_stdio() -> None:
    """Always emit UTF-8.

    When output is piped on Windows (scripts, AI agents using --json), Python falls back to
    the legacy code page (e.g. cp1252) and crashes on Chinese text. Packaged builds also ignore
    PYTHONIOENCODING, so we fix the streams here. Real consoles are already UTF-8 and untouched.
    """
    for stream in (sys.stdout, sys.stderr):
        enc = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        if enc != "utf8" and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


_utf8_stdio()

app = typer.Typer(
    add_completion=False,
    # Never print local variables on a crash: they could include the user's token.
    pretty_exceptions_enable=False,
    pretty_exceptions_show_locals=False,
    invoke_without_command=True,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
    help="✻ 麦麦交易终端：积分、优惠券和点餐，一个终端全搞定。直接运行 [bold]mcd[/] 看今日简报。",
)
address_app = typer.Typer(help="收货地址：查看和添加。", invoke_without_command=True)
app.add_typer(address_app, name="address")
config_app = typer.Typer(help="默认设置：门店、收货地址、点餐方式、积分用法，设一次以后都不用再填。",
                         invoke_without_command=True)
app.add_typer(config_app, name="config")
skill_app = typer.Typer(help="给 AI agent 用的 Skill：查看或安装使用指南。", no_args_is_help=True)
app.add_typer(skill_app, name="skill")

REQUIRED_TOOLS = [
    "now-time-info", "query-my-account", "query-my-coupons", "available-coupons", "auto-bind-coupons",
    "campaign-calendar", "mall-points-products", "mall-product-detail", "mall-create-order",
    "mall-order-list", "mall-order-detail", "query-nearby-stores",
    "delivery-query-addresses", "delivery-create-address", "delivery-query-stores", "query-meal-assistance",
    "query-meals", "query-meal-detail", "query-store-coupons", "calculate-price", "create-order",
    "query-order", "order-list", "cancel-order", "list-nutrition-foods", "query-lottery-info", "query-my-prizes",
    "query-party-city", "query-party-store", "query-party-store-date", "query-party-store-session",
    "party-order-create", "draw-lottery", "query-promotions", "query-survey-coupon",
]


class State:
    demo: bool = False
    json: bool = False
    result: dict[str, Any] = {}
    _client: Any = None
    _prefs: Prefs | None = None

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = DemoClient() if self.demo else McdClient()
        return self._client

    @property
    def prefs(self) -> Prefs:
        if self._prefs is None:
            if self.demo and os.environ.get("MCD_WEB_DEMO"):
                # the web demo keeps its own settings file, so trying settings there sticks
                # between clicks without ever touching the real prefs.json
                self._prefs = Prefs(name="prefs-demo.json")
            else:
                self._prefs = Prefs(persist=not self.demo)
        return self._prefs


state = State()


@app.callback()
def main(
    ctx: typer.Context,
    demo: bool = typer.Option(False, "--demo", help="使用离线演示数据，无需 Token。"),
    as_json: bool = typer.Option(False, "--json", "-j", help="给 AI / 脚本用：只输出一个 JSON 对象，从不弹确认框。"),
    version: bool = typer.Option(False, "--version", "-V", help="显示版本号。", is_eager=True),
) -> None:
    if version:
        typer.echo(f"mcd-terminal {__version__}")
        raise typer.Exit()
    state.demo = demo
    state.json = as_json
    state._prefs = None
    ui.set_quiet(as_json)
    if ctx.invoked_subcommand is None:
        today()


def _run(command: str, fn: Callable[[], None]) -> None:
    """Banner, run, footer; turn errors into a clean `⏺` line and exit code."""
    start = time.monotonic()
    state.result = {}
    if not state.json:
        ui.banner(command, state.demo)
    try:
        fn()
    except ui.ShownError as e:
        _emit(command, error=str(e))
        raise typer.Exit(1)
    except McdError as e:
        ui.error(str(e))
        _emit(command, error=str(e))
        raise typer.Exit(1)
    except KeyboardInterrupt:
        ui.result(Text("已中断", style=ui.DIM))
        raise typer.Exit(130)
    finally:
        if state._client is not None:
            state._client.close()
            state._client = None
    ui.footer(time.monotonic() - start)
    _emit(command)


def _emit(command: str, error: str | None = None) -> None:
    """In --json mode, print exactly one JSON object to stdout."""
    if not state.json:
        return
    body: dict[str, Any] = {"ok": error is None, "command": command, "demo": state.demo}
    if error is not None:
        body["error"] = error
    body.update(state.result)
    typer.echo(json.dumps(body, ensure_ascii=False, default=str))


def _out(**fields: Any) -> None:
    state.result.update(fields)


_SAME_FLAG = {"--dry-run": ("--dry-run", "-n"), "--yes": ("--yes", "-y"), "--json": ("--json", "-j")}


def _again(*, add: str = "", drop: str = "") -> str:
    """The command just run, with one flag added or dropped (for hints and confirm_with).

    Short and long spellings count as the same flag (-n / --dry-run, -y / --yes).
    """
    gone = _SAME_FLAG.get(drop, (drop,)) if drop else ()
    args = [a for a in sys.argv[1:] if a not in gone]
    if add and not any(a in args for a in _SAME_FLAG.get(add, (add,))):
        args.append(add)
    if not args or args[0].startswith("-") and len(args) < 2:
        return ""
    return " ".join(_q(a) for a in ["mcd", *args])


def _q(arg: str) -> str:
    """Shell-quote only when needed, so Chinese item names stay readable."""
    return arg if re.fullmatch(r"[^\s'\"$`\\;&|<>()*?#~!{}\[\]]+", arg) else shlex.quote(arg)


def _gate(yes: bool, ask: Callable[[], bool]) -> bool:
    """Confirmation for anything irreversible. Agents (--json) must re-run with --yes."""
    if yes:
        return True
    if state.json:
        _out(status="needs_confirmation", confirm_with=_again(add="--yes", drop="--dry-run") or None,
             note="会扣积分或创建订单。请先把方案告诉用户，得到明确同意后再加 --yes 重新执行。")
        return False
    ok = ask()
    if not ok:
        _out(status="cancelled")
    return ok


def _rows(data: Any, key: str = "list") -> list[dict[str, Any]]:
    if isinstance(data, dict):
        data = data.get(key) or data.get("list") or data.get("records") or []
    return data if isinstance(data, list) else []


def same_address(a: dict[str, Any], phone: str, street: str, detail: str) -> bool:
    """Saved address `a` is the one being added (the server masks phones as 152****6666)."""
    squash = lambda t: re.sub(r"\s+", "", str(t or ""))  # noqa: E731
    full = squash(a.get("fullAddress"))
    p = str(a.get("phone") or "")
    phone_ok = not p or p[-4:] == phone[-4:]
    return phone_ok and squash(street) in full and squash(detail) in full


def _set_address(a: dict[str, Any]) -> None:
    state.prefs.set("address_id", str(a.get("addressId")))
    state.prefs.set("address_text", str(a.get("fullAddress") or ""))
    who = " ".join(x for x in (str(a.get("contactName") or ""), str(a.get("phone") or "")) if x)
    state.prefs.set("address_contact", who or None)


def check_address(city: str, name: str, phone: str, street: str, detail: str, gender: str) -> dict[str, str]:
    """Validate and tidy a new delivery address; raises McdError with what to fix.

    The server accepts almost anything, but a wrong phone or a vague street means the rider
    can't find you, so check here before creating it.
    """
    squash = lambda t: re.sub(r"\s+", " ", (t or "").strip())  # noqa: E731
    city, name, street, detail = squash(city), squash(name), squash(street), squash(detail)
    phone = re.sub(r"[\s-]", "", phone or "")
    problems = []
    if not re.fullmatch(r"1[3-9]\d{9}", phone):
        problems.append("手机号要是 11 位、以 1 开头的数字")
    if not (1 <= len(name) <= 20) or re.fullmatch(r"\d+", name or "0"):
        problems.append("收货人写一个称呼就行（1–20 个字，不能全是数字）")
    if not re.fullmatch(r"[\u4e00-\u9fa5]{2,10}", city.rstrip("市")):
        problems.append("城市写中文城市名，例如 上海 或 上海市")
    if not (2 <= len(street) <= 60):
        problems.append("小区或楼宇写清楚一点（2–60 个字），例如 人民大道 200 号")
    if not (1 <= len(detail) <= 40):
        problems.append("门牌号不能空（最多 40 个字），例如 3 楼 302")
    g = {"男": "先生", "女": "女士", "先生": "先生", "女士": "女士", "": ""}.get((gender or "").strip())
    if g is None:
        problems.append("称谓只能是 先生 或 女士（也可以不填）")
    if problems:
        raise McdError("地址还差一点：" + "；".join(problems))
    if not city.endswith(("市", "州", "盟", "地区")):
        city += "市"
    return {"city": city, "contactName": name, "phone": phone, "address": street, "addressDetail": detail,
            **({"gender": g} if g else {})}


def _account() -> Account:
    def summary(d: Any) -> str:
        a = Account.from_payload(d or {})
        s = f"可用 {a.available:,} 积分"
        return s + (f"，{a.at_risk:,} 即将过期" if a.at_risk else "")
    return Account.from_payload(ui.call(state.client, "query-my-account", summary=summary) or {})


def _nutrition(quiet: bool = False) -> list:
    if quiet:
        try:
            return parse_nutrition(state.client.call("list-nutrition-foods"))
        except McdError:
            return []
    return parse_nutrition(ui.call(state.client, "list-nutrition-foods",
                                   summary=lambda d: f"{len(parse_nutrition(d))} 款餐品的营养数据"))


# ================================================================== today
@app.command()
def today() -> None:
    """今日简报：问候、积分和券的到期提醒、可领的券、今天的活动。"""
    def go() -> None:
        now, acct_d, coupons_d, claim_d, cal_d = ui.gather(state.client, [
            ("now-time-info", None), ("query-my-account", None), ("query-my-coupons", None),
            ("available-coupons", None), ("campaign-calendar", None),
        ], "整理今日简报")
        now = now or {}
        try:
            stamp = datetime.strptime(str(now.get("formatted")), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            stamp = datetime.now()
        acct = Account.from_payload(acct_d or {})
        coupons = parse_coupons(coupons_d)
        claimable = [t for t, st in parse_claimable(claim_d) if is_claimable(st)]
        campaigns = [x for x in parse_calendar(cal_d) if x.tag.startswith("今")]

        last = state.prefs.get("last_order")
        suggestion = "mcd order " + (" ".join(last) if last else ui.meal_pick(stamp.hour))
        _out(now=stamp.isoformat(timespec="minutes"), greeting=ui.greeting(stamp.hour),
             points=agent.account(acct),
             expiring_coupons=[agent.coupon(cp, stamp.date()) for cp in coupons
                               if cp.end and 0 <= cp.days_left(stamp.date()) <= 3],
             claimable=claimable, campaigns_today=[{"title": x.title, "intro": x.intro} for x in campaigns],
             suggestion=suggestion)

        week = "一二三四五六日"[stamp.weekday()]
        ui.say(Text.assemble((ui.greeting(stamp.hour), "bold"),
                             (f"  今天是 {stamp.month} 月 {stamp.day} 日，周{week}。", "")))
        console = ui.console
        console.print()
        rows: list[tuple[str, Text]] = []
        if acct.at_risk:
            rows.append(("⏳", Text.assemble(
                (f"你有 {acct.available:,} 积分，其中 ", ""), (f"{acct.at_risk:,}", f"bold {ui.RED}"),
                (" 两个月内会过期 → ", ""), ui.cmd("mcd spend --expiring"))))
        else:
            rows.append(("💰", Text(f"你有 {acct.available:,} 积分，近两个月都不会过期，放心攒着。")))
        soon = sorted([cp for cp in coupons if cp.end and 0 <= cp.days_left(stamp.date()) <= 3],
                      key=lambda cp: cp.end)
        for cp in soon[:2]:
            d = cp.days_left(stamp.date())
            when = "今天" if d == 0 else ("明天" if d == 1 else f"{d} 天后")
            rows.append(("🎟", Text.assemble((cp.title, "bold"), (f" {when}到期，别忘了用", ""))))
        if claimable:
            rows.append(("🎁", Text.assemble((f"麦麦省还有 {len(claimable)} 张券没领（{'、'.join(claimable[:2])}）→ ", ""),
                                             ui.cmd("mcd claim"))))
        for cpg in campaigns[:2]:
            rows.append(("📅", Text(cpg.title)))
        if last:
            rows.append(("🍔", Text.assemble((f"{ui.meal_hint(stamp.hour)}，再来一份上次的？ → ", ""),
                                             ui.cmd("mcd order " + " ".join(last)))))
        else:
            rows.append(("🍔", Text.assemble((f"{ui.meal_hint(stamp.hour)} → ", ""),
                                             ui.cmd("mcd order " + ui.meal_pick(stamp.hour)))))
        ui.bullets(rows)
    _run("today", go)


# ================================================================== points & coupons
@app.command()
def portfolio() -> None:
    """持仓：积分、到期风险、手里的优惠券。"""
    def go() -> None:
        acct = _account()
        coupons = parse_coupons(ui.call(
            state.client, "query-my-coupons",
            summary=lambda d: f"持有 {len(parse_coupons(d))} 张优惠券"))
        _out(points=agent.account(acct), coupons=[agent.coupon(cp, date.today()) for cp in coupons])
        ui.portfolio(acct, coupons, date.today())
    _run("portfolio", go)


def _points_of(row: dict[str, Any]) -> int:
    try:
        return int(float(row.get("point") or 0))
    except (TypeError, ValueError):
        return 0


def _now() -> datetime:
    fixed = os.environ.get("MCD_DEMO_NOW") if state.demo else None
    return datetime.strptime(fixed, "%Y-%m-%d %H:%M") if fixed else datetime.now()


def _value_menu() -> list:
    """Menu of the remembered pickup store, so points coupons can be valued at real prices."""
    from .ordering import Scene, load_menu
    st = state.prefs.get("store_pickup")
    if not st and state.demo:
        st = {"code": "1450001", "be": "", "name": "麦当劳人民广场餐厅"}
    if not st:
        return []
    try:
        return load_menu(state.client, Scene("pickup", st["code"], st.get("be", ""), st["name"]))
    except McdError:
        return []


def _scan_market(limit: int) -> list[MarketItem]:
    listings = ui.call(state.client, "mall-points-products",
                       summary=lambda d: f"积分商城共 {len(_rows(d))} 个商品")
    now = _now()
    # point "0" entries are paid events (parties, tastings); some entries are past their window
    rows = [r for r in _rows(listings) if _points_of(r) > 0 and on_shelf(r, now)][:limit]
    items: list[MarketItem] = []
    failed = 0
    with ui.thinking("比价中") as spin:
        for n, row in enumerate(rows, 1):
            spin.detail = f"({n}/{len(rows)}) {row.get('spuName', '')}"
            try:
                detail = state.client.call("mall-product-detail", {"spuId": int(row["spuId"])})
            except (McdError, KeyError, ValueError):
                detail, failed = None, failed + 1
            items.append(market_item(row, detail))
    if rows:
        ui.tool_line("mall-product-detail", times=len(rows))
        ui.result(f"{len(rows)} 个在售商品" + (f"，{failed} 个详情获取失败" if failed else ""))
    if items:
        menu = _value_menu()
        matched = price_from_menu(items, menu) if menu else 0
        if not menu:
            ui.tip(Text.assemble(("还不知道你常去哪家店，先用 ", ""), ui.cmd("mcd order <餐品> --dry-run"),
                                 (" 选一次门店，就能按门店价格估算积分值多少钱", "")))
        elif matched < len(items):
            ui.tip(f"{len(items) - matched} 个对不上门店的单品价格（组合、任选、实物或这家店没有），没有估值")
    return items


@app.command()
def market(
    limit: int = typer.Option(30, help="最多估值多少个商品（每个商品需要一次详情调用）。"),
    physical: bool = typer.Option(True, "--physical/--no-physical", help="是否显示实物周边。"),
) -> None:
    """行情：积分商城里哪样最值，按“每积分值几分钱”排序。"""
    def go() -> None:
        items = rank(_scan_market(limit))
        if not physical:
            items = [i for i in items if not i.is_physical]
        _out(items=[agent.market_item(i) for i in items])
        ui.market(items)
    _run("market", go)


@app.command()
def spend(
    budget: Optional[int] = typer.Option(None, help="指定预算积分，默认用全部可用积分。"),
    expiring: bool = typer.Option(False, "--expiring", help="只花两个月内会过期的积分。"),
    max_each: int = typer.Option(2, help="同一商品最多换几份。"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="只看方案，不兑换。"),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过确认（积分扣除不可撤销）。"),
    limit: int = typer.Option(30, help="最多参与计算的商品数。"),
) -> None:
    """清仓：在预算内凑出最值的兑换组合，确认后一键兑换。"""
    def go() -> None:
        acct = _account()
        if expiring:
            b, reason = min(acct.at_risk, acct.available), "清仓快过期的积分："
        else:
            b, reason = (min(budget, acct.available) if budget is not None else acct.available), ""
        if b <= 0:
            _out(status="nothing_to_do", points=agent.account(acct))
            ui.say(Text("近两个月没有积分过期，不用着急 🎉", style=ui.GREEN) if expiring else "可用积分为 0。")
            return
        p = optimize(_scan_market(limit), b, max_each=max_each)
        _out(status="planned", plan=agent.spend_plan(p))
        ui.plan(p, reason)
        if not p.picks:
            return
        if dry_run:
            ui.next_steps([f"mcd spend{' --expiring' if expiring else ''}"], "去掉 -n（--dry-run），确认后就会兑换")
            return
        if not _gate(yes, lambda: _confirm_plan(p)):
            return
        _out(status="done", redeemed=[_redeem(item.sku_id, n, item.name) for item, n in p.picks])
        ui.say(Text.assemble(("换好啦，", ""), (f"{p.points_used:,}", f"bold {ui.ACCENT}"),
                             (" 积分都变成了吃的。券在 ", ""), ui.cmd("mcd portfolio"), (" 里能看到。", "")))
    _run("spend", go)


def _confirm_plan(p: Plan) -> bool:
    details = [Text.assemble((f"{i.name} x{n}", ""), (f"   {i.points * n:,} 积分", ui.DIM)) for i, n in p.picks]
    details.append(Text(f"共 {p.points_used:,} 积分 · 扣除后不可撤销", style=ui.AMBER))
    return ui.ask("积分兑换", details, "按这个方案兑换吗？", ("是，全部兑换", "先不了"))


def _redeem(sku_id: int, count: int, name: str = "") -> dict[str, Any]:
    def summary(d: Any) -> list[str]:
        d = d or {}
        codes = [c for cp in d.get("coupons") or [] for c in cp.get("couponCodes") or []]
        out = [f"已兑换 {name or 'skuId ' + str(sku_id)} x{count} · 订单 {d.get('orderId', '—')}"]
        if codes:
            out.append(f"券码 {', '.join(codes)}")
        return out
    d = ui.call(state.client, "mall-create-order", {"skuId": int(sku_id), "count": int(count), "spuCategory": "1"},
                summary=summary) or {}
    return {"name": name or None, "sku_id": int(sku_id), "count": int(count), "order_id": d.get("orderId"),
            "coupon_codes": [c for cp in d.get("coupons") or [] for c in cp.get("couponCodes") or []]}


@app.command()
def buy(
    sku_id: int = typer.Argument(..., help="商品 skuId，在 mcd market 里能看到。"),
    count: int = typer.Option(1, "--count", "-n", min=1, help="兑换数量。"),
    address: Optional[str] = typer.Option(None, "--address", help="实物周边的收货地址 ID（见 mcd address）。"),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过确认。"),
) -> None:
    """用积分兑换：餐品券直接到账，实物周边加 --address 寄到家。"""
    def go() -> None:
        physical = address is not None
        details = [f"skuId {sku_id} x{count}" + ("，寄到地址 " + address if physical else ""),
                   Text("积分扣除后不可撤销", style=ui.AMBER)]
        _out(status="planned", sku_id=sku_id, count=count, address_id=address)
        if not _gate(yes, lambda: ui.ask("积分兑换", details, "确认兑换吗？", ("是", "先不了"))):
            return
        if not physical:
            _out(status="done", redeemed=[_redeem(sku_id, count)])
            return
        def summary(d: Any) -> list[str]:
            d = d or {}
            vo = d.get("orderDetailVo") or {}
            addr = (d.get("addressVO") or {}).get("fullAddress", "")
            return [f"订单 {d.get('orderId', '—')} · {vo.get('orderStatusTitle', '已提交')}"] + (
                [f"寄往 {addr}"] if addr else [])
        d = ui.call(state.client, "mall-create-order",
                    {"skuId": int(sku_id), "count": int(count), "addressId": address, "spuCategory": "2"},
                    summary=summary) or {}
        _out(status="done", order={"order_id": d.get("orderId"),
                                   "status": (d.get("orderDetailVo") or {}).get("orderStatusTitle"),
                                   "ship_to": (d.get("addressVO") or {}).get("fullAddress")})
        ui.say("下单成功，周边寄出后用 mcd history 就能看到进度。")
    _run("buy", go)


@app.command()
def claim(yes: bool = typer.Option(False, "--yes", "-y", help="跳过确认。")) -> None:
    """麦麦省：看看有什么券可以领，一键领完。"""
    def go() -> None:
        listing = ui.call(state.client, "available-coupons")
        rows = parse_claimable(listing)
        pending = [t for t, s in rows if is_claimable(s)]
        _out(status="planned", coupons=[{"title": t, "status": s} for t, s in rows], claimable=pending)
        if rows:
            ui.result(f"{len(rows)} 张券，{len(pending)} 张可领")
            ui.checklist([(t, not is_claimable(s), "" if is_claimable(s) else s) for t, s in rows])
        else:
            ui.result("没有解析到券列表")
        if rows and not pending:
            _out(status="nothing_to_do")
            ui.say(Text("能领的都领过了 ✓", style=ui.GREEN))
            return
        if not _gate(yes, lambda: ui.ask("麦麦省领券", [f"一键领取 {len(pending) or '全部'} 张可领的券"],
                                         "要领取吗？", ("是", "先不了"))):
            return
        bound = ui.call(state.client, "auto-bind-coupons")
        ok, failed, titles = parse_bind_result(bound)
        _out(status="done", claimed=titles, succeeded=ok, failed=failed)
        if ok is not None:
            ui.result(f"成功 {ok} 张" + (f"，失败 {failed} 张" if failed else ""))
        ui.checklist([(t, True, "") for t in titles])
        ui.say(Text.assemble(("领好了，点餐时会自动帮你用上。查看到期时间：", ""), ui.cmd("mcd portfolio")))
    _run("claim", go)


# ================================================================== ordering
def _mode(delivery: bool, drive: bool, group: bool, pickup: bool = False) -> str:
    """The flag given, else the saved default (mcd config mode), else pickup."""
    if sum([delivery, drive, group, pickup]) > 1:
        raise McdError("--pickup、--delivery、--drive、--group 只能选一个")
    if delivery or drive or group or pickup:
        return "delivery" if delivery else "drive" if drive else "group" if group else "pickup"
    saved = state.prefs.get("mode")
    return saved if saved in MODE_NAMES else "pickup"


MODE_NAMES = {"pickup": "到店自取", "delivery": "麦乐送", "drive": "得来速"}


def _points_cap(points: Optional[int], no_points: bool) -> Optional[int]:
    """--points / --no-points win; otherwise the saved policy (mcd config points)."""
    if no_points:
        return 0
    if points is not None:
        return points
    saved = state.prefs.get("points")
    if saved == "off":
        return 0
    return saved if isinstance(saved, int) else None


_SCENE_HELP = {
    "delivery": "麦乐送外送到家。",
    "drive": "得来速车道取餐。",
    "group": "企业团餐（外送，含助餐服务）。",
    "city": "城市，例如 上海。用过一次会记住。",
    "near": "在哪附近找门店，例如 人民广场。用过一次会记住这家店。",
    "address": "外送地址 ID（见 mcd address），默认用上次的。",
    "at": "预约时间，格式 'YYYY-MM-DD HH:MM'。",
    "service": "团餐助餐服务，例如 专人分餐。",
    "pick": "选第几家门店（默认最近的第 1 家）。",
}


@app.command()
def order(
    items: List[str] = typer.Argument(..., help="想吃什么，例如：巨无霸 薯条 麦乐鸡x2（数量写 x2 或 2份）"),
    pickup: bool = typer.Option(False, "--pickup", "-p", help="到店自取（默认；mcd config mode 可改默认方式）。"),
    delivery: bool = typer.Option(False, "--delivery", "-d", help=_SCENE_HELP["delivery"]),
    drive: bool = typer.Option(False, "--drive", help=_SCENE_HELP["drive"]),
    group: bool = typer.Option(False, "--group", help=_SCENE_HELP["group"]),
    city: Optional[str] = typer.Option(None, "--city", "-c", help=_SCENE_HELP["city"]),
    near: Optional[str] = typer.Option(None, "--near", "-l", help=_SCENE_HELP["near"]),
    address: Optional[str] = typer.Option(None, "--address", help=_SCENE_HELP["address"]),
    at: Optional[str] = typer.Option(None, "--at", help=_SCENE_HELP["at"]),
    service: Optional[str] = typer.Option(None, "--service", help=_SCENE_HELP["service"]),
    pick: int = typer.Option(1, "--pick", help=_SCENE_HELP["pick"]),
    points: Optional[int] = typer.Option(None, "--points", help="最多用多少积分，默认能用就用。"),
    no_points: bool = typer.Option(False, "--no-points", help="这单不用积分。"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="只看怎么付最省，不下单。"),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过确认。"),
) -> None:
    """点餐：自动把已有的券和积分叠加进来，算出最省的付法，确认后下单。"""
    def go() -> None:
        c = state.client
        wants = parse_wants(items)
        if not wants:
            raise McdError("告诉我想吃什么，例如：mcd order 巨无霸 中杯拿铁")
        scene = pick_scene(c, state.prefs, _mode(delivery, drive, group, pickup), city, near, address, at, service, pick)
        menu = load_menu(c, scene)
        try:
            units = resolve_units(wants, menu)
        except NotOnMenu as e:
            _not_on_menu(e)
        owned, known_ids = owned_coupons(c, scene, units, menu)
        expiring = False
        cap = _points_cap(points, no_points)
        if cap == 0:
            budget, mall = 0, []
        else:
            acct = _account()
            expiring = acct.at_risk > 0
            budget = min(acct.available, cap) if cap is not None else acct.available
            mall = mall_options(c, units, menu) if budget > 0 else []
            if scene.mode in ("delivery", "group"):
                mall = [m for m in mall if not m.in_store_only]  # 到店专用 coupons can't be used for delivery
        campaigns = related_campaigns(c, menu, units)
        promos = group_promotions(c, scene)

        def build(us: list) -> tuple[Any, list, Any]:
            p = plan_order(us, owned, mall, budget)
            p.known_coupon_ids = known_ids
            return p, suggest_extras(p, menu, owned, mall, budget, date.today()), None

        plan, extras, _ = build(units)
        kcal = _kcal([u.menu.name for u in units])
        show_plan(scene, plan, kcal, campaigns)
        _promo_tips(promos, plan, menu)
        q = quote(c, scene, plan)
        ui.quote_line(q, plan.pay_fen)
        _out_order(scene, plan, kcal, campaigns, q, extras, budget)

        # Idle coupons / leftover points / store promos: offer to add them.
        if extras and not yes and not dry_run and not state.json:
            left = budget - plan.points_used
            lines = [ui.extra_text(x, left, expiring) for x in extras]
            names = [x.menu.name for x in extras]
            options = (["带上", "不用了"] if len(extras) == 1 else
                       ["都带上", f"只带{names[0]}", f"只带{names[1]}", "不用了"])
            pick_i = ui.select("顺便带上？", lines, "这些不加白不加：", options)
            chosen = [] if pick_i is None or pick_i == len(options) - 1 else (
                extras if pick_i == 0 else [extras[pick_i - 1]])
            if pick_i is not None and not chosen:
                ui.step("顺便带上？", ui.dim("不用了，按原方案"))
            if chosen:
                units = units + [Unit(x.menu.name, x.menu) for x in chosen]
                plan, extras, _ = build(units)
                kcal = _kcal([u.menu.name for u in units])
                ui.step("顺便带上？", Text.assemble(("带上了 ", ui.DIM), ("、".join(x.menu.name for x in chosen), ui.GREEN),
                                                  ("，重新算了一遍：", ui.DIM)))
                show_plan(scene, plan, kcal, [])
                _promo_tips(promos, plan, menu)
                q = quote(c, scene, plan)
                ui.quote_line(q, plan.pay_fen)
                _out_order(scene, plan, kcal, campaigns, q, extras, budget)
        elif extras and not state.json:
            ui.console.print()
            for x in extras:
                ui.tip(ui.extra_text(x, budget - plan.points_used, expiring))

        if dry_run:
            ui.next_steps([_without("--dry-run")], "去掉 -n（--dry-run），确认后就会下单")
            return
        if not _gate(yes, lambda: _confirm_order(scene, plan, q)):
            return
        result = checkout(c, scene, plan, state.prefs.get("take_way"))
        oid = str(result.get("orderId", ""))
        if oid:
            remember_order(state.prefs, oid)
        state.prefs.set("last_order", [u.menu.name for u in units])
        price = result.get("_price") or {}
        pay = price.get("price") if isinstance(price.get("price"), int) else plan.pay_fen
        _out(status="ordered", order={
            "order_id": oid or None, "pay_url": result.get("payH5Url"), "pay_yuan": agent.yuan(pay),
            "next": "把 pay_url 发给用户，由用户自己打开付款；付款后可用 mcd --json track 查看进度"})
        if result.get("payH5Url"):
            ui.pay_link(str(result["payH5Url"]), pay)
        saved = plan.original_fen - (pay if isinstance(pay, int) else plan.pay_fen)
        ui.console.print()
        if saved >= 500:
            ui.tip(f"这单省了 {ui.yuan(saved)}，够买 {saved // 500} 个圆筒冰淇淋 🍦  付完款用 mcd track 看进度")
        else:
            ui.tip("付完款用 mcd track 看看做到哪一步了")
    _run("order", go)


def _not_on_menu(e: "NotOnMenu") -> None:
    """Offer the closest items and a ready-to-run command instead of a dead end."""
    swap = {w: alts[0] for w, alts in e.alternatives.items() if alts}
    retry = None
    if len(swap) == len(e.missing):
        out = []
        for a in sys.argv[1:]:
            parsed = parse_wants([a]) if not a.startswith("-") else []
            if parsed and parsed[0][0] in swap:
                name, n = parsed[0]
                a = swap[name] + (f"x{n}" if n > 1 else "")
            elif parsed and parsed[0][1] > 1 and "*" in a:
                a = f"{parsed[0][0]}x{parsed[0][1]}"   # no quoting needed, zsh-safe
            out.append(a)
        retry = " ".join(_q(a) for a in ["mcd", *out])
    _out(status="not_on_menu", missing=e.missing, alternatives=e.alternatives, retry_with=retry)
    ui.error(str(e))
    if retry and not state.json:
        ui.next_steps([retry], "换成店里有的再算一次")
    raise ui.ShownError(str(e))


def _promo_tips(promos: list, plan: Any, menu: list) -> None:
    """团餐满减满折：这单享受哪一档、再加多少能到下一档。金额以核价为准。"""
    if not promos:
        return
    from .promos import promo_status
    lines = [(ch.unit.menu.code, ch.pay_fen) for ch in plan.choices if ch.kind not in ("coupon", "points")]
    st = promo_status(promos, lines)
    a, n = st["applied"], st["next"]
    fill = None
    if n:   # 凑单：最便宜的、价格够补上差额的一样
        fits = sorted((m for m in menu if m.price_fen and m.price_fen >= n["gap_fen"]), key=lambda m: m.price_fen)
        fill = fits[0] if fits else None
    _out(group_promotions={
        "rules": [p.text for p in promos],
        "applied": {"rule": a["rule"], "saving_yuan": agent.yuan(a["saving_fen"])} if a else None,
        "next": {"rule": n["rule"], "add_yuan": agent.yuan(n["gap_fen"]), "extra_saving_yuan": agent.yuan(n["extra_saving_fen"]),
                 "fill_with": fill.name if fill else None} if n else None,
        "note": "现金部分参与满减满折，积分兑换和用券的餐品不算；以核价为准"})
    if a:
        ui.tip(Text.assemble(("团餐优惠 ", ui.ACCENT), (f"{a['rule']}，这单能省 ", ""), (ui.yuan(a["saving_fen"]), f"bold {ui.GREEN}")))
    if n:
        ui.tip(Text.assemble(("再加 ", ""), (ui.yuan(n["gap_fen"]), f"bold {ui.AMBER}"), (f" 就能{n['rule']}，", ""),
                             (f"再多省 {ui.yuan(n['extra_saving_fen'])}", ui.GREEN),
                             (f"（加一份{fill.name} {ui.yuan(fill.price_fen)} 就够）" if fill else "", ui.DIM)))


def show_plan(scene: Any, plan: Any, kcal: int, campaigns: list) -> None:
    ui.console.print()
    ui.console.print(ui._indent(scene_line(scene)))
    ui.order_plan(plan)
    if kcal or campaigns or scene.mode in ("delivery", "group"):
        ui.console.print()
    for cp in campaigns:
        ui.tip(Text.assemble(("今日活动 ", ui.ACCENT), (cp["title"], "")))
    if kcal:
        ui.tip(f"这一餐大约 {kcal:,} 千卡，吃饱好好干活 💪" if kcal < 1200 else
               f"这一餐大约 {kcal:,} 千卡，量有点大，叫上同事一起吃更香 🙂")
    if scene.mode == "delivery":
        ui.tip("配送费以核价为准")
    elif scene.mode == "group":
        ui.tip("团餐满额折扣以核价为准")


def _out_order(scene: Any, plan: Any, kcal: int, campaigns: list, q: dict | None, extras: list, budget: int) -> None:
    left = budget - plan.points_used
    _out(status="planned", scene=agent.scene(scene), plan=agent.order_plan(plan), kcal=kcal or None,
         quote=({"pay_yuan": agent.yuan(q["pay_fen"]), "delivery_yuan": agent.yuan(q["delivery_fen"]),
                 "promo_saving_yuan": agent.yuan(q["promo_fen"]),
                 "note": "现金和已有券部分的实时价格（含配送费、门店活动、团餐折扣）；积分兑换的商品另计 0 元"}
                if q else None),
         campaigns_today=campaigns,
         suggestions=[{"kind": x.kind, "add": x.menu.name, "code": x.menu.code, "pay_yuan": agent.yuan(x.pay_fen),
                       "saving_yuan": agent.yuan(x.saving_fen), "points": x.points or None,
                       "coupon": x.coupon.title if x.coupon else None, "days_left": x.days_left,
                       "message": ui.extra_text(x, left, False).plain,
                       "command": _again(add=x.menu.name, drop="--yes") or None} for x in extras])


def _without(flag: str) -> str:
    """The command the user just ran, minus one flag (for 'next step' hints)."""
    return _again(drop=flag) or "mcd order …"


def _kcal(names: list[str]) -> int:
    table = _nutrition(quiet=True)
    total = 0
    for n in names:
        hit = find_nutrition(n, table)
        if hit is None:
            return 0  # a partial number would mislead
        total += hit.kcal
    return total


def _confirm_order(scene: Any, plan: Any, q: dict | None = None) -> bool:
    details: list[str | Text] = [scene_line(scene)]
    for item, n in plan.redemptions():
        details.append(Text.assemble(("兑换 ", ui.ACCENT), (f"{item.name} x{n}", ""),
                                     (f"   {item.points * n:,} 积分（不可撤销）", ui.DIM)))
    pay = q["pay_fen"] if q else plan.pay_fen
    details.append(Text.assemble(("下单 ", ui.ACCENT), (f"{len(plan.choices)} 件，", ""),
                                 ("核价后实付 " if q else "预计实付 ", ""),
                                 (ui.yuan(pay), f"bold {ui.GREEN}"), ("，付款在下一步由你完成", ui.DIM)))
    return ui.ask("确认下单", details, "就这么点？", ("好，下单", "先不了"))


@app.command()
def menu(
    search: Optional[str] = typer.Argument(None, help="只看名字里带这个词的，例如 薯条。"),
    detail: Optional[str] = typer.Option(None, "--detail", help="查看某个餐品（编码）的套餐组成。"),
    pickup: bool = typer.Option(False, "--pickup", "-p", help="到店自取的菜单（默认方式见 mcd config）。"),
    delivery: bool = typer.Option(False, "--delivery", "-d", help=_SCENE_HELP["delivery"]),
    drive: bool = typer.Option(False, "--drive", help=_SCENE_HELP["drive"]),
    group: bool = typer.Option(False, "--group", help=_SCENE_HELP["group"]),
    city: Optional[str] = typer.Option(None, "--city", "-c", help=_SCENE_HELP["city"]),
    near: Optional[str] = typer.Option(None, "--near", "-l", help=_SCENE_HELP["near"]),
    address: Optional[str] = typer.Option(None, "--address", help=_SCENE_HELP["address"]),
    at: Optional[str] = typer.Option(None, "--at", help=_SCENE_HELP["at"]),
    limit: int = typer.Option(40, help="最多显示多少款。"),
) -> None:
    """菜单：门店现在能点什么、多少钱、多少热量；--detail 看套餐里有什么。"""
    def go() -> None:
        c = state.client
        scene = pick_scene(c, state.prefs, _mode(delivery, drive, group, pickup), city, near, address, at, None)
        if detail:
            d = ui.call(c, "query-meal-detail", dict(scene.params(), code=detail),
                        summary=lambda d: str((d or {}).get("name") or detail)) or {}

            def choice(ch: dict[str, Any]) -> str:
                extra = str(ch.get("diffPrice") or "").replace(" ", "")
                return str(ch.get("name", "")) + ("" if extra in ("", "+¥0") else f"（{extra}）")

            rounds = d.get("rounds") or []
            mods = [v.get("name") for it in (d.get("modification") or {}).get("items") or []
                    for v in it.get("values") or [] if v.get("name")]
            _out(store=scene.store_name, detail={"code": detail, "name": d.get("name"), "price_yuan": d.get("price"),
                                                 "rounds": [{"name": r.get("name"), "quantity": r.get("quantity", 1),
                                                             "choices": [choice(ch) for ch in r.get("choices") or []]}
                                                            for r in rounds],
                                                 "adjustable": mods})
            if not rounds:
                ui.say(f"{d.get('name') or detail} 是单品" + (f"，可以调整：{'、'.join(mods)}" if mods else "。"))
                return
            rows = []
            for r in rounds:
                chs = [choice(ch) for ch in r.get("choices") or []]
                shown = " / ".join(chs[:4]) + (f" 等 {len(chs)} 种" if len(chs) > 4 else "")
                rows.append([ui.dim(r.get("name", "")), shown,
                             ui.faint(f"x{r.get('quantity', 1)}")])
            ui.say(f"{d.get('name') or '这个套餐'}里有这些（第一个是默认）：")
            ui.console.print()
            ui.simple_table([("", "left"), ("", "left"), ("", "right")], rows)
            return
        items = load_menu(c, scene)
        if search:
            items = [m for m in items if search.lower() in m.name.lower()]
        table = _nutrition(quiet=True)
        items = sorted(items, key=lambda m: m.price_fen)[:limit]
        _out(store=scene.store_name, scene=agent.scene(scene), items=[
            {"code": m.code, "name": m.name, "price_yuan": agent.yuan(m.price_fen),
             "original_price_yuan": agent.yuan(m.original_fen) if m.original_fen and m.original_fen > m.price_fen else None,
             "category": m.category or None, "tags": list(m.tags), "image": m.image or None,
             "kcal": (find_nutrition(m.name, table).kcal if find_nutrition(m.name, table) else None)} for m in items])
        ui.say(f"{scene.store_name} 有 {len(items)} 款" + (f"带「{search}」的" if search else "") + "餐品：")
        ui.console.print()
        rows = []
        for m in items:
            n = find_nutrition(m.name, table)
            rows.append([m.name, ui.yuan(m.price_fen), ui.dim(f"{n.kcal} 千卡" if n else "—"), ui.faint(m.code)])
        ui.simple_table([("餐品", "left"), ("价格", "right"), ("热量", "right"), ("编码", "right")], rows)
        if items:
            ui.console.print()
            ui.tip(Text.assemble(("想点哪个直接说：", ui.DIM), ui.cmd(f"mcd order {items[0].name}")))
    _run("menu", go)


@app.command()
def nutrition(
    search: Optional[str] = typer.Argument(None, help="只看名字里带这个词的。"),
    sort: str = typer.Option("kcal", help="排序：kcal / protein。"),
) -> None:
    """营养：每款餐品的热量、蛋白质、脂肪、碳水和钠。"""
    def go() -> None:
        table = _nutrition()
        if search:
            table = [n for n in table if search in n.name]
        key = (lambda n: -n.protein) if sort == "protein" else (lambda n: n.kcal)
        table = sorted(table, key=key)
        _out(items=[{"name": n.name, "kcal": n.kcal, "protein_g": n.protein, "fat_g": n.fat,
                     "carbs_g": n.carbs, "sodium_mg": n.sodium} for n in table])
        ui.say(f"{len(table)} 款餐品，按{'蛋白质从高到低' if sort == 'protein' else '热量从低到高'}：")
        ui.console.print()
        ui.simple_table(
            [("餐品", "left"), ("千卡", "right"), ("蛋白质", "right"), ("脂肪", "right"), ("碳水", "right"), ("钠 mg", "right")],
            [[n.name, Text(str(n.kcal), style="bold"), f"{n.protein:g}g", f"{n.fat:g}g", f"{n.carbs:g}g",
              ui.dim(f"{n.sodium:g}")] for n in table])
    _run("nutrition", go)


@app.command()
def stores(
    drive: bool = typer.Option(False, "--drive", help="只看支持得来速的门店。"),
    city: Optional[str] = typer.Option(None, "--city", "-c", help=_SCENE_HELP["city"]),
    near: Optional[str] = typer.Option(None, "--near", "-l", help="在哪附近找；不填则列出收藏的门店。"),
    use: Optional[int] = typer.Option(None, "--use", help="把第几家设为以后点餐的默认门店。"),
) -> None:
    """门店：附近或收藏的麦当劳，--use 设为默认。"""
    def go() -> None:
        mode = "drive" if drive else "pickup"
        city_ = city or state.prefs.get("city")
        if near and not city_:
            raise McdError("按位置找门店需要城市，例如：--city 上海 --near 人民广场")
        args = {"searchType": 2, "beType": 5 if drive else 1, "city": city_, "keyword": near} if near \
            else {"searchType": 1, "beType": 5 if drive else 1}
        rows = _rows(ui.call(state.client, "query-nearby-stores", args,
                             summary=lambda d: f"找到 {len(_rows(d))} 家"))
        current = (state.prefs.get(f"store_{mode}") or {}).get("code")
        _out(stores=[{"index": i, "name": st.get("storeName"), "store_code": st.get("storeCode"),
                      "distance": st.get("distance"), "address": st.get("address"),
                      "open": st.get("businessStatus", True), "default": str(st.get("storeCode")) == str(current)}
                     for i, st in enumerate(rows, 1)])
        ui.console.print()
        ui.simple_table(
            [("#", "right"), ("门店", "left"), ("距离", "right"), ("", "left"), ("地址", "left")],
            [[ui.faint(str(i)), st["storeName"], ui.dim(fmt_distance(st.get("distance"))),
              Text("营业中", style=ui.GREEN) if st.get("businessStatus", True) else Text("休息中", style=ui.DIM),
              ui.dim(st.get("address", "") or "") if str(st["storeCode"]) != str(current)
              else Text("默认门店", style=ui.ACCENT)]
             for i, st in enumerate(rows, 1)])
        if use and 1 <= use <= len(rows):
            st = rows[use - 1]
            state.prefs.set(f"store_{mode}", {"code": st["storeCode"], "be": st.get("beCode", ""), "name": st["storeName"]})
            if near and city_:
                state.prefs.set("city", city_)
            _out(default_set=st["storeName"])
            ui.say(Text.assemble(("记住了，以后点餐默认去 ", ""), (st["storeName"], "bold"), ("。", "")))
        elif rows:
            ui.console.print()
            ui.tip(Text.assemble(("设为默认门店：", ui.DIM), ui.cmd("mcd stores --use 1" + (f" --near {near}" if near else ""))))
    _run("stores", go)


@address_app.callback()
def address_list(ctx: typer.Context) -> None:
    """查看收货地址。"""
    if ctx.invoked_subcommand is not None:
        return

    def go() -> None:
        data = ui.call(state.client, "delivery-query-addresses") or {}
        addrs = data.get("addresses") if isinstance(data, dict) else data
        addrs = addrs or []
        ui.result(f"{len(addrs)} 个收货地址")
        current = state.prefs.get("address_id")
        _out(addresses=[{"address_id": a.get("addressId"), "contact": a.get("contactName"), "phone": a.get("phone"),
                         "address": a.get("fullAddress"), "default": str(a.get("addressId")) == str(current)}
                        for a in addrs])
        if addrs:
            ui.console.print()
            ui.simple_table([("ID", "left"), ("收货人", "left"), ("地址", "left"), ("", "left")],
                            [[ui.faint(str(a.get("addressId"))), f"{a.get('contactName', '')} {a.get('phone', '')}",
                              a.get("fullAddress", ""),
                              Text("默认", style=ui.ACCENT) if str(a.get("addressId")) == str(current) else ""]
                             for a in addrs])
        else:
            ui.say(Text.assemble(("还没有地址，加一个：", ""), ui.cmd("mcd address add --help")))
    _run("address", go)


@address_app.command("add")
def address_add(
    city: str = typer.Option(..., "--city", "-c", help="城市，例如 上海市。"),
    name: str = typer.Option(..., "--name", help="收货人。"),
    phone: str = typer.Option(..., "--phone", help="11 位手机号。"),
    street: str = typer.Option(..., "--street", help="小区/楼宇，例如 人民大道 200 号。"),
    detail: str = typer.Option(..., "--detail", help="门牌号，例如 3 楼 302。"),
    gender: str = typer.Option("", "--gender", help="先生 / 女士。"),
) -> None:
    """添加一个收货地址。"""
    def go() -> None:
        args = check_address(city, name, phone, street, detail, gender)
        existing = _rows(ui.call(state.client, "delivery-query-addresses",
                                 summary=lambda d: f"{len(_rows(d, 'addresses'))} 个收货地址"), "addresses")
        same = next((a for a in existing if same_address(a, args["phone"], args["address"], args["addressDetail"])), None)
        if same:
            _set_address(same)
            _out(address={"address_id": same.get("addressId"), "address": same.get("fullAddress")}, reused=True)
            ui.say(Text.assemble(("这个地址已经有了，不重复添加，设为默认：", ""), (same.get("fullAddress", ""), "bold")))
            return
        if len(existing) >= 10:
            raise McdError("已经有 10 个收货地址了，先在麦当劳 App 里删掉不用的再添加")
        d = ui.call(state.client, "delivery-create-address", args,
                    summary=lambda d: f"{(d or {}).get('fullAddress', '')}（ID {(d or {}).get('addressId', '—')}）") or {}
        _out(address={"address_id": d.get("addressId"), "address": d.get("fullAddress")})
        if d.get("addressId"):
            _set_address(d)
        ui.say(Text.assemble(("地址加好了，以后外送就送这里：", ""), ui.cmd("mcd order 巨无霸 --delivery")))
        if state.prefs.get("mode") != "delivery":
            ui.tip(Text.assemble(("想默认外送、不用每次加 --delivery：", ui.DIM), ui.cmd("mcd config mode delivery")))
    _run("address add", go)


# ================================================================== config
POINTS_HELP = "auto（能用就用，默认）/ off（点餐不用积分）/ 数字（每单最多用多少积分）"


def _config_rows() -> list[tuple[str, str, str, str]]:
    """(key, label, value, how to change)."""
    p = state.prefs
    store = lambda m: (p.get(f"store_{m}") or {}).get("name") or "—（第一次点餐时自动选，或手动设置）"  # noqa: E731
    pts = p.get("points")
    pts_text = "点餐不用积分" if pts == "off" else f"每单最多 {pts:,} 积分" if isinstance(pts, int) else "能用就用"
    return [
        ("mode", "点餐方式", MODE_NAMES.get(p.get("mode") or "pickup", "到店自取"), "mcd config mode pickup|delivery|drive"),
        ("store", "到店门店", store("pickup"), "mcd config store --city 上海 --near 人民广场"),
        ("drive_store", "得来速门店", store("drive"), "mcd config store --drive --city 上海 --near 人民广场"),
        ("address", "收货地址", (p.get("address_text") or (f"ID {p.get('address_id')}" if p.get("address_id") else "—"))
         + (f"（{p.get('address_contact')}）" if p.get("address_contact") else ""),
         "mcd config address [地址ID]"),
        ("city", "城市", p.get("city") or "—", "mcd config city 上海"),
        ("points", "积分", pts_text, "mcd config points auto|off|1000"),
        ("take_way", "取餐", p.get("take_way") or "门店默认", "mcd config take-way 堂食|外带"),
    ]


@config_app.callback()
def config_show(ctx: typer.Context) -> None:
    """查看默认设置。"""
    if ctx.invoked_subcommand is not None:
        return

    def go() -> None:
        rows = _config_rows()
        p = state.prefs
        _out(config={k: v for k, _, v, _ in rows}, file=str(prefs_path()),
             raw={"mode": p.get("mode") or "pickup", "store": p.get("store_pickup"), "drive_store": p.get("store_drive"),
                  "address_id": p.get("address_id"), "address": p.get("address_text"), "address_contact": p.get("address_contact"),
                  "city": p.get("city"), "points": p.get("points"), "take_way": p.get("take_way")})
        ui.say("你的默认设置（点餐时不用再填，命令里的参数优先）：")
        ui.console.print()
        ui.simple_table([("", "left"), ("", "left"), ("修改", "left")],
                        [[ui.dim(label), value, ui.faint(how)] for _, label, value, how in rows])
        ui.console.print()
        ui.tip(f"保存在 {prefs_path()}，不含 Token；清空用 mcd config reset")
    _run("config", go)


@config_app.command("mode")
def config_mode(mode: str = typer.Argument(..., help="pickup 到店自取 / delivery 麦乐送 / drive 得来速")) -> None:
    """默认点餐方式。"""
    def go() -> None:
        m = {"自取": "pickup", "到店": "pickup", "外送": "delivery", "外卖": "delivery", "麦乐送": "delivery",
             "得来速": "drive"}.get(mode, mode)
        if m not in MODE_NAMES:
            raise McdError("点餐方式只能是 pickup（到店自取）、delivery（麦乐送）或 drive（得来速）")
        state.prefs.set("mode", m)
        _out(mode=m)
        ui.say(Text.assemble(("以后点餐默认 ", ""), (MODE_NAMES[m], "bold"),
                             ("；临时换一种加 --pickup / --delivery / --drive。", "")))
        if m == "delivery" and not state.prefs.get("address_id"):
            ui.tip(Text.assemble(("还没有默认收货地址：", ui.DIM), ui.cmd("mcd config address")))
    _run("config mode", go)


@config_app.command("store")
def config_store(
    city: Optional[str] = typer.Option(None, "--city", "-c", help="城市，例如 上海。"),
    near: Optional[str] = typer.Option(None, "--near", "-l", help="在哪附近，例如 人民广场。不填会问你。"),
    pick: int = typer.Option(1, "--pick", help="选第几家（默认最近的）。"),
    drive: bool = typer.Option(False, "--drive", help="设置得来速门店。"),
) -> None:
    """默认门店：按位置找一家，记住它。"""
    from .ordering import _ask_place, _remember_store, _search_stores

    def go() -> None:
        mode = "drive" if drive else "pickup"
        c_, n_ = city or state.prefs.get("city"), near
        if not (c_ and n_):
            place = _ask_place()
            if not place:
                raise McdError("告诉我城市和地点，例如：mcd config store --city 上海 --near 人民广场")
            c_, n_ = place
        stores = _search_stores(state.client, 5 if drive else 1, c_, n_)
        if not stores:
            raise McdError(f"{c_}{n_}附近没找到营业中的门店，换个地点试试")
        ui.console.print()
        ui.simple_table([("#", "right"), ("门店", "left"), ("距离", "right"), ("地址", "left")],
                        [[ui.faint(str(i)), st["storeName"], ui.dim(fmt_distance(st.get("distance"))),
                          ui.dim(st.get("address", "") or "")] for i, st in enumerate(stores[:5], 1)])
        scene = _remember_store(state.prefs, mode, stores, pick)
        state.prefs.set("city", c_)
        _out(store={"name": scene.store_name, "store_code": scene.store_code}, mode=mode)
        ui.say(Text.assemble(("记住了，以后", ""), ("得来速" if drive else "到店", ""), ("默认去 ", ""),
                             (scene.store_name, "bold"), ("。", "")))
    _run("config store", go)


@config_app.command("address")
def config_address(address_id: Optional[str] = typer.Argument(None, help="地址 ID（mcd address 里能看到）。")) -> None:
    """默认收货地址：从已有地址里选一个。"""
    def go() -> None:
        addrs = _rows(ui.call(state.client, "delivery-query-addresses",
                              summary=lambda d: f"{len(_rows(d, 'addresses'))} 个收货地址"), "addresses")
        if not addrs:
            raise McdError("还没有收货地址，先加一个（只需一次）：mcd address add --city 上海市 --name 你的名字 "
                           "--phone 手机号 --street 小区或楼宇 --detail 门牌号")
        if address_id:
            chosen = next((a for a in addrs if str(a.get("addressId")) == str(address_id)), None)
            if chosen is None:
                raise McdError(f"没有 ID 为 {address_id} 的地址，用 mcd address 看看")
        elif len(addrs) == 1:
            chosen = addrs[0]
        else:
            labels = [f"{a.get('fullAddress', '')}  {a.get('contactName', '')}" for a in addrs[:3]]
            i = ui.select("默认收货地址", [], "选一个：", [*labels, "先不设"])
            if i is None or i >= len(labels):
                _out(status="cancelled")
                return
            chosen = addrs[i]
        _set_address(chosen)
        _out(address={"address_id": chosen.get("addressId"), "address": chosen.get("fullAddress")})
        ui.say(Text.assemble(("记住了，外送默认送到 ", ""), (chosen.get("fullAddress", ""), "bold"), ("。", "")))
    _run("config address", go)


@config_app.command("city")
def config_city(city: str = typer.Argument(..., help="城市，例如 上海。")) -> None:
    """默认城市（按位置找门店时用）。"""
    def go() -> None:
        state.prefs.set("city", city.strip())
        _out(city=city.strip())
        ui.say(f"记住了，默认城市是 {city.strip()}。")
    _run("config city", go)


@config_app.command("points")
def config_points(policy: str = typer.Argument(..., help=POINTS_HELP)) -> None:
    """点餐时积分怎么用。"""
    def go() -> None:
        v = policy.strip().lower()
        if v in ("auto", "on", "默认", "能用就用"):
            state.prefs.set("points", None)
            text = "能用就用"
        elif v in ("off", "no", "0", "不用"):
            state.prefs.set("points", "off")
            text = "点餐不用积分"
        elif v.isdigit():
            state.prefs.set("points", int(v))
            text = f"每单最多 {int(v):,} 积分"
        else:
            raise McdError(f"积分设置可以是：{POINTS_HELP}")
        _out(points=state.prefs.get("points"))
        ui.say(f"记住了，点餐时积分：{text}。单次可以用 --points / --no-points 覆盖。")
    _run("config points", go)


@config_app.command("take-way")
def config_take_way(way: str = typer.Argument(..., help="堂食 / 外带")) -> None:
    """到店取餐默认堂食还是外带（门店不支持时用门店默认）。"""
    from .ordering import TAKE_WAYS

    def go() -> None:
        w = {"eat-in": "堂食", "take-out": "外带", "takeout": "外带", "打包": "外带"}.get(way, way)
        if w not in TAKE_WAYS:
            raise McdError("只能是 堂食 或 外带")
        state.prefs.set("take_way", w)
        _out(take_way=w)
        ui.say(f"记住了，到店默认{w}。")
    _run("config take-way", go)


@config_app.command("reset")
def config_reset(key: Optional[str] = typer.Argument(None, help="只清一项：mode / store / drive_store / address / city / points / take_way")) -> None:
    """清空默认设置（不影响 Token 和麦当劳账号里的地址）。"""
    keys = {"mode": ["mode"], "store": ["store_pickup"], "drive_store": ["store_drive"],
            "address": ["address_id", "address_text", "address_contact"], "city": ["city"], "points": ["points"],
            "take_way": ["take_way"], "take-way": ["take_way"]}

    def go() -> None:
        if key and key not in keys:
            raise McdError("可以清的项：" + " / ".join(k for k in keys if k != "take-way"))
        for k in (keys[key] if key else [k for ks in keys.values() for k in ks]):
            state.prefs.unset(k)
        _out(reset=key or "all")
        ui.say("清好了。" if key else "默认设置都清空了，下次点餐会重新帮你选门店。")
    _run("config reset", go)


@app.command()
def track(order_id: Optional[str] = typer.Argument(None, help="订单号，默认看最近一单。")) -> None:
    """订单进度：做到哪了、取餐码、送到哪了。"""
    def go() -> None:
        oid = order_id or _latest_order()
        if not oid:
            raise McdError("还没有最近的订单，给个订单号试试：mcd track <订单号>")
        d = ui.call(state.client, "query-order", {"orderId": oid},
                    summary=lambda d: f"{(d or {}).get('storeName', '')} · {(d or {}).get('orderStatus', '')}") or {}
        status = str(d.get("orderStatus", ""))
        hint = status_hint(status)
        info_ = d.get("deliveryInfo") or {}
        _out(order={"order_id": d.get("orderId", oid), "status": status, "hint": hint or None,
                    "store": d.get("storeName"), "pickup_code": d.get("pickupCode") or None,
                    "locker_code": d.get("lockerCode") or None, "pay_yuan": d.get("realTotalAmount"),
                    "discount_yuan": d.get("totalDiscountAmount"),
                    "delivery_address": info_.get("deliveryAddress") or None,
                    "expected_delivery": info_.get("expectDeliveryTime") or None,
                    "items": [{"name": p.get("productName"), "quantity": p.get("quantity", 1)}
                              for p in d.get("orderProductList") or []]})
        ui.say(Text.assemble((status or "状态未知", f"bold {ui.ACCENT}"), (f"  {hint}" if hint else "", "")))
        finished = any(w in status for w in ("完成", "取消", "退款"))
        if d.get("pickupCode") and not finished:
            ui.console.print()
            ui.big_code("取餐码", str(d["pickupCode"]))
        if d.get("lockerCode"):
            ui.big_code("取餐柜", str(d["lockerCode"]))
        info = d.get("deliveryInfo") or {}
        if info.get("deliveryAddress"):
            ui.console.print()
            ui.tip(f"送往 {info.get('deliveryAddress', '')} {info.get('addressDetail', '')}"
                   + (f" · 预计 {info['expectDeliveryTime']}" if info.get("expectDeliveryTime") else ""))
        rows = [[p.get("productName", ""), ui.faint(f"x{p.get('quantity', 1)}"), ui.dim(f"¥{p.get('price', '')}")]
                for p in d.get("orderProductList") or []]
        if rows:
            ui.console.print()
            ui.simple_table([("餐品", "left"), ("", "right"), ("", "right")], rows)
            ui.console.print(ui._indent(Text.assemble(
                ("实付 ", ui.DIM), (f"¥{d.get('realTotalAmount', '—')}", f"bold {ui.GREEN}"),
                (f"   优惠 ¥{d.get('totalDiscountAmount', '0')}", ui.DIM))))
    _run("track", go)


def _latest_order() -> str | None:
    """The order this terminal placed most recently, else the newest one on the account."""
    oid = next(iter(state.prefs.get("recent_orders", [])), None)
    if oid:
        return oid
    rows = _rows(ui.call(state.client, "order-list", summary=lambda d: f"{len(_rows(d))} 笔订单"))
    return str(rows[0].get("orderId")) if rows and rows[0].get("orderId") else None


def _order_items(o: dict[str, Any]) -> str:
    items = o.get("orderProductList") or []
    text = "、".join(f"{p.get('productName', '')}" + (f" x{p['quantity']}" if int(p.get("quantity") or 1) > 1 else "")
                    for p in items[:3])
    return text + (f" 等 {len(items)} 样" if len(items) > 3 else "")


@app.command()
def orders(size: int = typer.Option(10, help="显示最近多少笔。")) -> None:
    """点餐记录：最近点过什么（积分商城的兑换见 mcd history）。"""
    def go() -> None:
        rows = _rows(ui.call(state.client, "order-list", summary=lambda d: f"最近 {len(_rows(d))} 笔订单"))[:size]
        _out(orders=[{"order_id": o.get("orderId"), "time": o.get("createTime"), "store": o.get("storeName"),
                      "status": o.get("orderStatus"), "pay_yuan": o.get("realTotalAmount"),
                      "items": [{"name": p.get("productName"), "quantity": p.get("quantity", 1)}
                                for p in o.get("orderProductList") or []]} for o in rows])
        if not rows:
            ui.say(Text.assemble(("还没有点过餐，来一单？", ""), ui.cmd("mcd order 巨无霸 --dry-run")))
            return
        ui.console.print()
        ui.simple_table(
            [("时间", "left"), ("餐品", "left"), ("实付", "right"), ("状态", "left"), ("订单号", "left")],
            [[ui.dim(str(o.get("createTime", ""))[5:16]), _order_items(o), f"¥{o.get('realTotalAmount', '—')}",
              Text(str(o.get("orderStatus", "")), style=ui.GREEN if "完成" in str(o.get("orderStatus")) else ui.AMBER),
              ui.faint(str(o.get("orderId", "")))] for o in rows])
        ui.console.print()
        ui.tip(Text.assemble(("看某一单的进度：", ""), ui.cmd("mcd track <订单号>")))
        ui.tip(Text.assemble(("吃完填过满意度问卷？看看送了什么券：", ""), ui.cmd("mcd survey")))
    _run("orders", go)


SATISFACTION = {5: "非常满意", 4: "满意", 3: "一般", 2: "不满意", 1: "很不满意"}


def _survey(d: Any, oid: str) -> dict[str, Any] | None:
    if not isinstance(d, dict):
        return None
    sat = d.get("overall_satisfaction")
    way = {"1": "到店/自取", "2": "外送"}.get(str(d.get("coupon_order_food_types") or ""), None)
    title = d.get("coupon_title") or None
    status = d.get("coupon_redeem_status") or None
    return {"order_id": str(d.get("trade_no") or oid), "answered_at": d.get("finish_time") or None,
            "satisfaction": d.get("satisfaction_description") or (SATISFACTION.get(sat) if isinstance(sat, int) else None),
            "coupon": title, "coupon_status": status, "coupon_for": way,
            "coupon_left": d.get("coupon_available_redeem_count"),
            "valid_from": d.get("coupon_trade_start_time") or None, "valid_to": d.get("coupon_trade_end_time") or None,
            "usable": bool(title) and status != "已核销"}


def _survey_line(s: dict[str, Any] | None, oid: str) -> str:
    if not s or not s["coupon"]:
        return f"订单 …{oid[-6:]}：填过问卷，没有奖券"
    return f"订单 …{oid[-6:]}：{s['coupon']}" + (f"（{s['coupon_status']}）" if s["coupon_status"] else "")


def _surveys(order_ids: list[str]) -> list[dict[str, Any]]:
    out = []
    for oid in order_ids:
        with ui.thinking():
            try:
                d = state.client.call("query-survey-coupon", {"orderId": oid})
            except McdError:
                d = None   # 这单没填过问卷：服务端会说“无匹配的答卷”
        ui.tool_line("query-survey-coupon")
        if d is None:
            ui.result(Text(f"订单 …{oid[-6:]}：没有问卷记录", style=ui.DIM))
            continue
        ui.result(_survey_line(_survey(d, oid), oid))
        s = _survey(d, oid)
        if s:
            out.append(s)
    return out


@app.command()
def survey(
    order_id: Optional[str] = typer.Argument(None, help="订单号；不填就查最近几笔已完成的订单。"),
    size: int = typer.Option(5, "--size", help="不填订单号时，查最近几笔。"),
) -> None:
    """问卷奖券：吃完填的满意度问卷送了什么券、什么时候到期、用没用过。"""
    def go() -> None:
        if order_id:
            ids = [order_id]
        else:
            rows = _rows(ui.call(state.client, "order-list", summary=lambda d: f"最近 {len(_rows(d))} 笔订单"))
            ids = [str(o["orderId"]) for o in rows if o.get("orderId") and "完成" in str(o.get("orderStatus", ""))][:max(size, 1)]
            if not ids:
                _out(surveys=[])
                ui.say("最近没有已完成的订单。吃完记得填问卷，常常会送券 🎟")
                return
        found = _surveys(ids)
        _out(surveys=found)
        if not found:
            ui.say("这些订单都没有问卷记录。下次吃完留意小票或 App 里的满意度问卷，填完一般会送券。")
            return
        usable = [x for x in found if x["usable"]]
        ui.say(f"找到 {len(found)} 份问卷" + (f"，其中 {len(usable)} 张奖券还能用" if usable else "，奖券都用过了"))
        ui.console.print()
        ui.simple_table([("订单", "left"), ("你的评价", "left"), ("奖券", "left"), ("状态", "left"), ("有效期至", "left")],
                        [[ui.faint(x["order_id"][-8:]), x["satisfaction"] or "—", x["coupon"] or ui.dim("没有奖券"),
                          Text(x["coupon_status"] or "", style=ui.GREEN if x["usable"] else ui.DIM),
                          ui.dim(str(x["valid_to"] or "")[:10] + (f" · {x['coupon_for']}" if x["coupon_for"] else ""))]
                         for x in found])
        if usable:
            ui.console.print()
            ui.tip("问卷奖券在你的券包里，点餐时 mcd 会把能用的券一起算进最省方案：mcd order …")
    _run("survey", go)


CANCEL_REASONS = {"1": "改主意了", "2": "重复下单", "3": "点错了/点多了/点少了",
                  "4": "地址/电话填错了", "5": "送达时间选错了", "-1": "其它原因"}


@app.command()
def cancel(
    order_id: Optional[str] = typer.Argument(None, help="订单号，默认取消最近一单。"),
    reason: str = typer.Option("1", "--reason", help="取消原因：1 改主意了，2 重复下单，3 点错了，4 地址/电话填错，5 送达时间选错，-1 其它。"),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过确认。"),
) -> None:
    """取消一笔点餐订单（积分商城的兑换不能在这里取消）。"""
    def go() -> None:
        if reason not in CANCEL_REASONS:
            raise McdError("--reason 只能是 1、2、3、4、5 或 -1")
        oid = order_id or _latest_order()
        if not oid:
            raise McdError("没找到最近的订单，给个订单号：mcd cancel <订单号>")
        d = ui.call(state.client, "query-order", {"orderId": oid},
                    summary=lambda d: f"{(d or {}).get('storeName', '')} · {(d or {}).get('orderStatus', '')}") or {}
        items = _order_items(d) or oid
        _out(status="planned", order_id=oid, items=items, order_status=d.get("orderStatus"),
             reason=CANCEL_REASONS[reason])
        details = [f"{items} · ¥{d.get('realTotalAmount', '—')}", f"原因：{CANCEL_REASONS[reason]}",
                   Text("取消后不能恢复", style=ui.AMBER)]
        if not _gate(yes, lambda: ui.ask("取消订单", details, "确定取消这一单吗？", ("是，取消", "不取消了"))):
            return
        r = ui.call(state.client, "cancel-order", {"orderId": oid, "cancelReasonCode": reason},
                    summary=lambda r: "已取消" if (r or {}).get("cancelResult") else "没有取消成功") or {}
        ok = bool(r.get("cancelResult"))
        _out(status="done" if ok else "failed", cancelled=ok)
        if not ok:
            raise McdError("门店没有接受取消，可能已经开始制作了，可以联系门店处理")
        ui.say("这单已经取消了。如果已经付过款，退款会原路退回。")
    _run("cancel", go)


def _lottery(d: Any) -> dict[str, Any] | None:
    if not isinstance(d, dict) or not d.get("activityName"):
        return None
    nxt = ((d.get("drawDecision") or {}).get("nextConsumption") or {})
    return {"name": d.get("activityName"), "status": d.get("activityStatusText"),
            "begin": d.get("beginTime"), "end": d.get("endTime"), "draw_points": d.get("drawPoint"),
            "rule": d.get("drawTypeText"), "chances_left": d.get("availableTimes"),
            "eligible": (d.get("drawDecision") or {}).get("resourceEligible"),
            "next_cost": nxt.get("text") or None, "reason": (d.get("drawDecision") or {}).get("reason"),
            "next_points": nxt.get("points"), "next_chances": nxt.get("chances"),
            "then": (((d.get("drawDecision") or {}).get("fallbackConsumption") or {}).get("text")) or None,
            "prizes": [{"name": x.get("name"), "image": x.get("imageUrl") or None, "type": x.get("typeText")}
                       for x in d.get("prizes") or []]}


def _my_prizes(d: Any) -> list[dict[str, Any]]:
    rows = (d or {}).get("prizes") if isinstance(d, dict) else d
    return [{"id": x.get("id"), "name": x.get("name"), "image": x.get("imageUrl") or None,
             "status": x.get("statusText"), "won_at": x.get("recordTime"), "remind": x.get("timeRemindText")}
            for x in rows or [] if isinstance(x, dict)]


@app.command()
def events() -> None:
    """派对和体验：生日派对、亲子活动、品鉴会这些要付费报名的活动（积分商城里 0 积分的那些）。"""
    def go() -> None:
        rows = _rows(ui.call(state.client, "mall-points-products",
                             summary=lambda d: f"积分商城共 {len(_rows(d))} 个商品"))
        now = _now()
        found = [r for r in rows if _points_of(r) == 0 and on_shelf(r, now)]
        items = [{"name": r.get("spuName"), "spu_id": r.get("spuId"), "category": r.get("catName") or None,
                  "price_yuan": float(r["price"]) if str(r.get("price") or "").replace(".", "", 1).isdigit() else None,
                  "intro": r.get("selling") or None, "image": r.get("spuImage") or None,
                  "until": str(r.get("downTime") or "")[:10] or None} for r in found]
        _out(events=items)
        if not items:
            ui.say("现在没有可以报名的派对或体验活动。")
            return
        ui.say(f"有 {len(items)} 个派对和体验活动可以报名：")
        ui.console.print()
        ui.simple_table([("活动", "left"), ("类型", "left"), ("价格", "right"), ("截止", "left")],
                        [[i["name"] or "", ui.dim(i["category"] or ""),
                          f"¥{i['price_yuan']:g}" if i["price_yuan"] is not None else "—", ui.faint(i["until"] or "")]
                         for i in items])
        ui.console.print()
        ui.tip(Text.assemble(("看场次、预约：", ""), ui.cmd(f"mcd party {_q(str(items[0]['name'] or ''))[:12]} --book")))
    _run("events", go)


# ================================================================== reminders
def _remind_at(day: date, at: str, now: datetime) -> datetime:
    h, m = (int(x) for x in at.split(":", 1))
    when = datetime(day.year, day.month, day.day, h, m)
    if when <= now:  # today's slot already passed: remind in a few minutes instead of in the past
        when = now.replace(second=0, microsecond=0) + timedelta(minutes=5)
    return when


def _campaign_days(cal: Any, title: str, today: date) -> tuple[str, list[date]] | None:
    hits = [c for c in parse_calendar(cal) if title in c.title]
    if not hits:
        return None
    days = []
    for c in hits:
        m = re.search(r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日", c.day)
        if m:
            days.append(date(int(m.group(1) or today.year), int(m.group(2)), int(m.group(3))))
    return hits[0].title, sorted(set(days))


@app.command()
def remind(
    what: str = typer.Argument(..., help="coupons 快过期的券 / points 快过期的积分 / campaign 某个活动 / party 派对场次"),
    title: Optional[str] = typer.Option(None, "--title", "-t", help="活动或派对名字（campaign / party 时用，写一部分就行）。"),
    day: Optional[str] = typer.Option(None, "--date", help="指定日期 YYYY-MM-DD（party 时必填，campaign 默认下一次活动日）。"),
    at: str = typer.Option("10:00", "--at", help="几点提醒，HH:MM。"),
    days: int = typer.Option(7, "--days", help="coupons：提醒多少天内到期的券。"),
    to_ics: bool = typer.Option(False, "--ics", help="不用提醒事项，生成日历文件（.ics）。"),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过确认。"),
) -> None:
    """提醒：把券和积分的到期日、活动开始、派对场次放进系统的提醒事项或日历。"""
    from .remind import Reminder, add_to_macos_reminders, is_macos, open_file, write_ics

    def go() -> None:
        if not re.fullmatch(r"\d{1,2}:\d{2}", at):
            raise McdError("--at 的格式是 HH:MM，例如 10:00")
        now = _now()
        today = now.date()
        items: list[Reminder] = []
        if what == "coupons":
            coupons = parse_coupons(ui.call(state.client, "query-my-coupons",
                                            summary=lambda d: f"{len(parse_coupons(d))} 张券"))
            for cp in coupons:
                if cp.end and 0 <= (cp.end - today).days <= days:
                    items.append(Reminder(f"🎟 {cp.title} 今天到期", _remind_at(cp.end, at, now),
                                          f"用券价 ¥{cp.price}；用 mcd order 点餐会自动用上" if cp.price else "用 mcd order 点餐会自动用上"))
        elif what == "points":
            acct = _account()
            if acct.at_risk:
                def last_day(d: date) -> date:
                    return (d.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
                month_end = last_day(today)
                if not acct.expiring_this_month:
                    month_end = last_day(month_end + timedelta(days=1))
                n = acct.expiring_this_month or acct.expiring_next_month
                items.append(Reminder(f"⏳ {n:,} 麦当劳积分月底过期", _remind_at(month_end - timedelta(days=3), at, now),
                                      "运行 mcd spend --expiring，把快过期的积分换成吃的"))
        elif what in ("campaign", "event"):
            if not title:
                raise McdError("告诉我是哪个活动：mcd remind campaign --title 活动名的一部分")
            cal = ui.call(state.client, "campaign-calendar", summary=lambda d: f"{len(parse_calendar(d))} 条活动")
            found = _campaign_days(cal, title, today)
            if not found:
                raise McdError(f"活动日历里没找到「{title}」")
            name, ds = found
            target = datetime.strptime(day, "%Y-%m-%d").date() if day else next((d for d in ds if d >= today), None)
            if target is None:
                raise McdError("这个活动已经结束了")
            items.append(Reminder(f"🍟 麦当劳活动：{name}", _remind_at(target, at, now), "活动详情：mcd calendar 或 mcd web"))
        elif what == "party":
            if not (title and day):
                raise McdError("派对提醒需要名字和日期：mcd remind party --title 派对名 --date YYYY-MM-DD --at 14:00")
            items.append(Reminder(f"🎈 {title}", _remind_at(datetime.strptime(day, "%Y-%m-%d").date(), at, now),
                                  "还没约的话：mcd party <名字> --book；约好了记得准时到店签到"))
        else:
            raise McdError("要提醒什么？coupons、points、campaign 或 party")

        _out(status="planned", reminders=[{"title": r.title, "at": r.when.isoformat(timespec="minutes")} for r in items])
        if not items:
            _out(status="nothing_to_do")
            ui.say("没有需要提醒的。" if what != "coupons" else f"{days} 天内没有快到期的券。")
            return
        mac = is_macos() and not to_ics and not state.demo
        where = f"提醒事项（列表「麦麦提醒」）" if mac else "日历文件（.ics），用你的日历应用打开"
        details = [f"{r.when:%m-%d %H:%M}  {r.title}" for r in items] + [Text(f"加到：{where}", style=ui.DIM)]
        if not _gate(yes, lambda: ui.ask("添加提醒", details, "要添加吗？", ("好", "先不了"))):
            return
        if mac:
            results = []
            for r in items:
                try:
                    results.append(add_to_macos_reminders(r))
                except RuntimeError as e:
                    raise McdError(str(e))
            created = results.count("created")
            _out(status="done", method="reminders", created=created, existed=len(results) - created)
            ui.say(f"加好了：{created} 条新提醒" + (f"，{len(results) - created} 条之前就有" if len(results) > created else "")
                   + "，在“提醒事项”的「麦麦提醒」列表里。")
            return
        from .prefs import home
        path = write_ics(items, home() / "reminders")
        opened = False if state.demo or state.json else open_file(path)
        _out(status="done", method="ics", file=str(path), opened=opened)
        ui.say(Text.assemble(("日历文件已生成：", ""), (str(path), "bold")))
        ui.tip("已经用默认的日历应用打开，确认导入就行" if opened else "双击这个文件，用日历应用（Outlook、日历等）导入")
    _run("remind", go)


# ================================================================== party booking (read-only)
def _party_match(rows: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    evs = [r for r in rows if _points_of(r) == 0]
    if name.isdigit():
        return next((r for r in evs if str(r.get("spuId")) == name), None)
    return next((r for r in evs if name in str(r.get("spuName", ""))), None)


PARTY_TYPES = {1: "包场", 2: "拼团"}


def _party_type(value: str | None) -> int | None:
    if value is None:
        return None
    v = value.strip()
    if v in ("1", "包场"):
        return 1
    if v in ("2", "拼团"):
        return 2
    raise McdError("--type 只能是 包场 或 拼团")


def _fen_of(v: Any) -> int | None:
    if isinstance(v, int):
        return v
    try:
        return round(float(str(v)) * 100)
    except (TypeError, ValueError):
        return None


@app.command()
def party(
    name: str = typer.Argument(..., help="派对或体验活动的名字（写一部分就行）或 spuId，见 mcd events。"),
    city: Optional[str] = typer.Option(None, "--city", "-c", help="城市，默认用 mcd config 里的城市。"),
    pick: int = typer.Option(1, "--pick", help="选第几家门店（默认最近的）。"),
    dates: int = typer.Option(3, "--dates", help="看最近几天的场次。"),
    book: bool = typer.Option(False, "--book", "-b", help="预约一个场次：选好后下单，扫码付款。"),
    day: Optional[str] = typer.Option(None, "--date", help="预约哪天，YYYY-MM-DD。"),
    at: Optional[str] = typer.Option(None, "--time", help="预约哪个场次，写开始时间，例如 10:30。"),
    count: Optional[int] = typer.Option(None, "--count", help="参加人数。"),
    kind: Optional[str] = typer.Option(None, "--type", help="包场 或 拼团（活动两种都支持时需要选）。"),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过确认。"),
) -> None:
    """派对场次：哪个城市、哪家店、哪天几点还能约；加 --book 直接预约，扫码付款。"""
    def go() -> None:
        c = state.client
        rows = _rows(ui.call(c, "mall-points-products", summary=lambda d: f"积分商城共 {len(_rows(d))} 个商品"))
        ev = _party_match(rows, name)
        if not ev:
            raise McdError(f"没找到「{name}」这个派对或体验活动，用 mcd events 看看有哪些")
        spu = int(ev["spuId"])
        cities = _rows(ui.call(c, "query-party-city", {"spuId": spu}, summary=lambda d: f"{len(_rows(d))} 个城市可以约"))
        want = (city or state.prefs.get("city") or "").replace("市", "")
        ct = next((x for x in cities if want and want in str(x.get("name", ""))), None)
        if ct is None:
            _out(event=ev.get("spuName"), cities=[x.get("name") for x in cities], status="choose_city")
            names = "、".join(str(x.get("name")) for x in cities[:12])
            raise McdError(f"告诉我在哪个城市：mcd party {name} --city 上海" + (f"（可选：{names}）" if names else ""))
        stores = _rows(ui.call(c, "query-party-store", {"code": str(ct.get("code")), "latitude": ct.get("latitude"),
                                                          "longitude": ct.get("longitude"), "spuId": spu},
                               summary=lambda d: f"{ct.get('name')} 有 {len(_rows(d))} 家店可以办"))
        if not stores:
            raise McdError(f"{ct.get('name')} 暂时没有门店可以办这个活动")
        st = stores[min(max(pick, 1), len(stores)) - 1]
        ds = _rows(ui.call(c, "query-party-store-date", {"storeCode": str(st.get("code")), "spuId": spu},
                           summary=lambda d: f"{st.get('name')} 有 {len(_rows(d))} 天可以约"))
        if day:
            ds = [d for d in ds if str(d.get("date")) == day] or ds[:0]
            if not ds:
                raise McdError(f"{st.get('name')} {day} 这天约不了，去掉 --date 看看有哪些日子")
        out_days, raw = [], []
        for d in ds[:max(dates, 1)]:
            sessions = _rows(ui.call(c, "query-party-store-session",
                                     {"storeCode": str(st.get("code")), "spuId": spu, "dateStr": d.get("date")},
                                     summary=lambda x, d=d: f"{d.get('date')}：{len(_rows(x))} 个场次"))
            raw += [(str(d.get("date")), x) for x in sessions]
            out_days.append({"date": d.get("date"), "sessions": [
                {"start": x.get("timeStart"), "end": x.get("timeEnd"), "left": x.get("leftNum"),
                 "min": x.get("partyMin"), "max": x.get("partyMax"),
                 "price_yuan": agent.yuan(x.get("price")) if isinstance(x.get("price"), int) else x.get("price")}
                for x in sessions]})
        store_out = {"name": st.get("name"), "code": st.get("code"), "address": st.get("address"),
                     "distance": st.get("distanceText") or st.get("distance")}
        _out(status="listed", event=ev.get("spuName"), spu_id=spu, city=ct.get("name"), store=store_out,
             other_stores=[x.get("name") for x in stores[:6] if x is not st], days=out_days,
             note="想预约：加 --book（可配 --date --time --count），确认后下单、扫码付款")
        if not book:
            ui.say(Text.assemble((str(ev.get("spuName")), "bold"), (f"  ·  {ct.get('name')} {st.get('name')}", "")))
            ui.console.print()
            rows_ = []
            for d in out_days:
                for x in d["sessions"] or [{"start": "—", "end": "", "left": 0}]:
                    rows_.append([d["date"] or "", f"{x.get('start') or ''}–{x.get('end') or ''}",
                                  Text(f"余 {x.get('left')}", style=ui.GREEN if (x.get("left") or 0) > 0 else ui.DIM),
                                  f"¥{x['price_yuan']:g}" if isinstance(x.get("price_yuan"), (int, float)) else ""])
            ui.simple_table([("日期", "left"), ("场次", "left"), ("", "left"), ("价格", "right")], rows_)
            ui.console.print()
            ui.tip(Text.assemble(("想预约：", ""), ui.cmd(_again(add="--book") or f"mcd party {name} --book"),
                                 ("（会一步步选场次和人数，确认后才下单）", ui.DIM)))
            return
        _book_party(ev, spu, ct, st, raw, at, count, kind, yes)
    _run("party", go)


def _book_party(ev: dict[str, Any], spu: int, ct: dict[str, Any], st: dict[str, Any],
                raw: list[tuple[str, dict[str, Any]]], at: str | None, count: int | None,
                kind: str | None, yes: bool) -> None:
    """party-order-create：城市 → 门店 → 日期 → 场次 → 类型和人数 → 确认 → 下单付款。"""
    c = state.client
    open_ = [(d, x) for d, x in raw if (x.get("leftNum") or 0) > 0]
    if at:
        open_ = [(d, x) for d, x in open_ if str(x.get("timeStart", "")).startswith(at)]
    if not open_:
        _out(status="no_session")
        raise McdError("这几天的场次都约满了，换一天（--date）或换一家店（--pick 2）试试")
    label = lambda d, x: f"{d} {x.get('timeStart')}–{x.get('timeEnd')}（余 {x.get('leftNum')}）"
    if len(open_) > 1 and not at:
        if state.json or yes:
            _out(status="choose_session", sessions=[{"date": d, "time": x.get("timeStart"), "left": x.get("leftNum")}
                                                    for d, x in open_],
                 note="用 --date 和 --time 指定一个场次再预约")
            ui.say("有几个场次可以约，用 --date 和 --time 选一个")
            return
        i = ui.select("选个场次", [], "哪一场？", [label(d, x) for d, x in open_[:6]] + ["先不约"])
        if i is None or i >= min(len(open_), 6):
            _out(status="cancelled")
            return
        open_ = [open_[i]]
    d, x = open_[0]
    detail = ui.call(c, "mall-product-detail", {"spuId": spu},
                     summary=lambda r: str((r or {}).get("spuName") or ev.get("spuName"))) or {}
    if str(detail.get("shopId", "5")) != "5":
        raise McdError("这个活动不支持在线预约，请在麦当劳 App 里报名")
    sku = (detail.get("skuList") or [{}])[0]
    fixed = detail.get("partyType", sku.get("partyType"))
    fixed = int(fixed) if str(fixed).lstrip("-").isdigit() else -1
    ptype = fixed if fixed in (1, 2) else _party_type(kind)
    if ptype is None:
        if state.json or yes:
            _out(status="choose_type", options=["包场", "拼团"], note="这个活动包场、拼团都可以，用 --type 选一个")
            ui.say("包场还是拼团？用 --type 包场 或 --type 拼团")
            return
        j = ui.select("包场还是拼团？", ["包场：整场只有你们", "拼团：和其他家庭一起参加"], "选哪种？", ["包场", "拼团", "先不约"])
        if j is None or j == 2:
            _out(status="cancelled")
            return
        ptype = j + 1
    elif kind and _party_type(kind) != fixed and fixed in (1, 2):
        raise McdError(f"这个活动只能{PARTY_TYPES[fixed]}")
    lo, hi, left = x.get("partyMin"), x.get("partyMax"), x.get("leftNum")
    n = count or (lo if ptype == 1 and lo else 1)
    if n < 1 or (hi and n > hi) or (ptype == 2 and left and n > left):
        raise McdError(f"人数不对：这一场 {lo or 1}–{hi or '不限'} 人" + (f"，还剩 {left} 个位置" if ptype == 2 and left else ""))
    price = _fen_of(x.get("price"))
    summary_ = {"event": ev.get("spuName"), "store": st.get("name"), "date": d, "time": f"{x.get('timeStart')}–{x.get('timeEnd')}",
                "type": PARTY_TYPES[ptype], "count": n, "price_yuan": agent.yuan(price) if price is not None else None}
    _out(status="planned", booking=summary_)
    details = [Text.assemble((str(ev.get("spuName")), "bold")),
               f"{ct.get('name')} {st.get('name')}",
               Text.assemble((f"{d}  {x.get('timeStart')}–{x.get('timeEnd')}", f"bold {ui.ACCENT}")),
               f"{PARTY_TYPES[ptype]} · {n} 人",
               Text("场次价格 " + (ui.yuan(price) if price is not None else "以下单页为准") + "，下一步扫码付款；退改以活动规则为准", style=ui.DIM)]
    if not _gate(yes, lambda: ui.ask("预约派对", details, "就约这一场吗？", ("好，预约", "先不约"))):
        return
    args = {"spuId": spu, "skuId": sku.get("skuId"), "partyType": ptype, "code": str(ct.get("code")),
            "storeCode": str(st.get("code")), "dateStr": d, "id": x.get("id"), "timeStart": x.get("timeStart"),
            "timeEnd": x.get("timeEnd"), "leftNum": left, "count": n,
            "partyTimeInfo": {k: x.get(k) for k in ("id", "leftNum", "partyMax", "partyMin", "price", "timeStart", "timeEnd")}}
    r = ui.call(c, "party-order-create", args,
                summary=lambda r: f"订单 {(r or {}).get('orderId', '')} · 待支付") or {}
    url = r.get("payH5Url") or ""
    amount = _fen_of(r.get("amount")) if r.get("amount") not in (None, "") else price
    _out(status="booked", booking=summary_, order={"order_id": r.get("orderId"), "pay_url": url or None,
                                                   "pay_yuan": agent.yuan(amount) if amount is not None else None,
                                                   "next": "把 pay_url 发给用户，由用户自己打开付款"})
    if url:
        ui.pay_link(url, amount)
    else:
        ui.say("预约已提交，付款请在麦当劳 App 的订单里完成。")
    ui.console.print()
    ui.tip(Text.assemble(("别忘了那天：", ""), ui.cmd(f"mcd remind party --title {_q(str(ev.get('spuName')))} --date {d} --at {x.get('timeStart')}")))


@app.command()
def prizes() -> None:
    """奖品：积分抽奖在送什么、我抽中过什么（抽奖用 mcd draw，会先确认）。"""
    def go() -> None:
        c = state.client
        try:
            lot = _lottery(ui.call(c, "query-lottery-info", summary=lambda d: str((d or {}).get("activityName") or "暂无抽奖活动")))
        except McdError as e:
            lot = None
            ui.result(Text(str(e), style=ui.DIM))
        try:
            mine = _my_prizes(ui.call(c, "query-my-prizes", {"pageSize": "20"},
                                      summary=lambda d: f"{len(_my_prizes(d))} 个奖品"))
        except McdError as e:
            mine = []
            ui.result(Text(str(e), style=ui.DIM))
        _out(lottery=lot, my_prizes=mine)
        if lot:
            ui.say(Text.assemble((lot["name"] or "积分抽奖", "bold"), (f"  {lot['status'] or ''}", ui.ACCENT)))
            when = " ~ ".join(x for x in (lot["begin"], lot["end"]) if x)
            ui.result(*(x for x in (when, f"抽一次：{lot['next_cost'] or (str(lot['draw_points']) + ' 积分')}",
                                     lot["reason"]) if x))
            if lot["prizes"]:
                ui.console.print()
                ui.simple_table([("奖池", "left"), ("类型", "left")],
                                [[p["name"] or "", ui.dim(p["type"] or "")] for p in lot["prizes"]])
        else:
            ui.say("现在没有积分抽奖活动。")
        ui.console.print()
        if mine:
            ui.simple_table([("我的奖品", "left"), ("状态", "left"), ("中奖时间", "left"), ("", "left")],
                            [[p["name"] or "", Text(p["status"] or "", style=ui.GREEN if "可用" in (p["status"] or "") else ui.DIM),
                              ui.dim(str(p["won_at"] or "")[:10]), ui.faint(p["remind"] or "")] for p in mine])
        else:
            ui.tip("还没有抽中过奖品")
        if lot and lot["eligible"] is not False:
            ui.tip(Text.assemble(("想抽一次：", ""), ui.cmd("mcd draw"), ("（会先告诉你这次扣多少，确认后才抽）", ui.DIM)))
    _run("prizes", go)


@app.command()
def draw(yes: bool = typer.Option(False, "--yes", "-y", help="已经看过本次消耗并确认，直接抽。")) -> None:
    """积分抽奖：先告诉你这次会扣多少次数或积分，你确认后只抽一次（不会自动连抽）。"""
    def go() -> None:
        c = state.client
        lot = _lottery(ui.call(c, "query-lottery-info",
                               summary=lambda d: str((d or {}).get("activityName") or "暂无抽奖活动")))
        if not lot:
            raise McdError("现在没有积分抽奖活动")
        _out(lottery=lot)
        if lot["eligible"] is False:
            _out(status="not_eligible")
            raise McdError(lot["reason"] or "这次不能抽：次数或积分不够")
        cost = lot["next_cost"] or (f"消耗 {lot['draw_points']} 积分" if lot["draw_points"] else "按活动规则消耗")
        details: list[Any] = [Text.assemble(("活动 ", ui.DIM), (lot["name"] or "", "bold")),
                              Text.assemble(("" if cost.startswith("本次") else "本次 ", ui.DIM), (cost, f"bold {ui.AMBER}"))]
        if lot["then"]:
            details.append(Text(f"本次优先消耗次数；次数用完后将改为{lot['then']}", style=ui.DIM))
        if lot["prizes"]:
            details.append(Text("奖池：" + "、".join(p["name"] or "" for p in lot["prizes"][:5]), style=ui.DIM))
        _out(status="planned", cost=cost)
        if not _gate(yes, lambda: ui.ask("积分抽奖", details, "确定抽一次吗？", ("抽一次", "先不抽"))):
            return
        r = ui.call(c, "draw-lottery", summary=lambda r: "抽中了！" if (r or {}).get("win") else
                    ((r or {}).get("status") or {}).get("message") or "这次没中") or {}
        st = r.get("status") or {}
        if st.get("code") and str(st.get("code")).upper() != "SUCCESS":
            _out(status="failed", message=st.get("message"))
            raise McdError(str(st.get("message") or "抽奖没有成功"))
        won = [{"name": x.get("name"), "image": x.get("imageUrl") or None, "type": x.get("typeText"),
                "valid": x.get("validDateInfo")} for x in r.get("prizes") or []]
        _out(status="drawn", win=bool(r.get("win")), won=won, consumed_points=r.get("consumePoint"),
             points_left=r.get("remainPoint"), chances_left=r.get("remainChance"))
        if r.get("win") and won:
            ui.say(Text.assemble(("🎉 抽中了 ", ""), ("、".join(w["name"] or "" for w in won), f"bold {ui.GREEN}")))
            for w in won:
                if w["valid"]:
                    ui.tip(f"{w['name']}：{w['valid']}")
            ui.tip(Text.assemble(("奖品在这里：", ""), ui.cmd("mcd prizes")))
        else:
            ui.say("这次没中，下次好运 🍀")
        left = [f"剩余积分 {r['remainPoint']}" if r.get("remainPoint") not in (None, "") else "",
                f"剩余次数 {r['remainChance']}" if r.get("remainChance") is not None else ""]
        if any(left):
            ui.tip("，".join(x for x in left if x))
    _run("draw", go)


@app.command()
def history(
    order_id: Optional[str] = typer.Argument(None, help="查看某一笔兑换的详情。"),
    size: int = typer.Option(10, help="显示最近多少笔。"),
) -> None:
    """兑换记录：近一年在积分商城换过什么。"""
    def go() -> None:
        c = state.client
        if order_id:
            d = ui.call(c, "mall-order-detail", {"orderId": order_id}) or {}
            _out(order={"order_id": d.get("orderId"), "goods": goods_text(d), "status": d.get("orderStatusTitle"),
                        "time": d.get("createTime") or d.get("payTime"),
                        "points": d.get("realTotalPoints") or d.get("totalPoints"),
                        "amount_yuan": d.get("realTotalAmount")})
            ui.say(Text.assemble((goods_text(d), "bold"), (f"  {d.get('orderStatusTitle', '')}", ui.ACCENT)))
            ui.console.print()
            ui.simple_table([("", "left"), ("", "left")], [
                [ui.dim("订单号"), str(d.get("orderId", ""))],
                [ui.dim("时间"), str(d.get("createTime") or d.get("payTime") or "")],
                [ui.dim("积分"), str(d.get("realTotalPoints") or d.get("totalPoints") or "—")],
                [ui.dim("金额"), f"¥{d.get('realTotalAmount', '0')}"],
                [ui.dim("客服"), str(d.get("customerServicePhone", ""))],
            ])
            return
        orders, _ = parse_mall_orders(ui.call(c, "mall-order-list", {"size": size},
                                              summary=lambda d: f"最近 {len(parse_mall_orders(d)[0])} 笔兑换"))
        _out(orders=[{"order_id": o.get("orderId"), "time": o.get("createTime"), "goods": goods_text(o),
                      "points": o.get("realTotalPoints"), "status": o.get("orderStatusTitle")} for o in orders])
        if not orders:
            ui.say("还没有兑换记录，看看积分能换什么：mcd market")
            return
        ui.console.print()
        ui.simple_table(
            [("时间", "left"), ("兑换", "left"), ("积分", "right"), ("状态", "left"), ("订单号", "left")],
            [[ui.dim(str(o.get("createTime", ""))[:10]), goods_text(o), str(o.get("realTotalPoints", "—")),
              Text(str(o.get("orderStatusTitle", "")), style=ui.GREEN if "完成" in str(o.get("orderStatusTitle")) else ui.AMBER),
              ui.faint(str(o.get("orderId", "")))] for o in orders])
    _run("history", go)


@app.command()
def calendar(day: Optional[str] = typer.Option(None, "--date", help="查看某天前后的活动，格式 YYYY-MM-DD。")) -> None:
    """活动日历：今天和最近几天有什么活动。"""
    def go() -> None:
        args = {"specifiedDate": day} if day else None
        items = parse_calendar(ui.call(state.client, "campaign-calendar", args,
                                       summary=lambda d: f"{len(parse_calendar(d))} 个活动"))
        _out(campaigns=[{"day": it.day, "tag": it.tag, "title": it.title, "intro": it.intro, "detail": it.detail or None,
                         "image": it.image or None} for it in items])
        if not items:
            ui.say("这段时间没有活动。")
            return
        last_day = None
        for it in items:
            if (it.day, it.tag) != last_day:
                last_day = (it.day, it.tag)
                style = ui.ACCENT if it.tag.startswith("今") else (ui.DIM if "往期" in it.tag else "bold")
                ui.console.print()
                ui.console.print(ui._indent(Text.assemble((it.day, style), (f"  {it.tag}", ui.FAINT))))
            ui.console.print(ui._indent(Text.assemble(("• ", ui.FAINT), (it.title, "" if "往期" not in it.tag else ui.DIM)), 4))
            if it.intro and "往期" not in it.tag:
                ui.console.print(ui._indent(ui.dim(it.intro), 6))
    _run("calendar", go)


@app.command()
def doctor() -> None:
    """检查 Token 和连接，看看服务端提供了哪些工具。"""
    def go() -> None:
        client = state.client
        source = ("演示模式，不需要 Token" if state.demo else
                  "环境变量 MCD_MCP_TOKEN" if os.environ.get("MCD_MCP_TOKEN") else f"{token_path()}")
        with ui.thinking("连接中"):
            tools = client.list_tools()
        _out(token_source=source)
        ui.console.print()
        ui.console.print(Text.assemble((ui.BULLET + " ", ui.GREEN), ("tools/list", "bold"), (" (MCP)", ui.DIM)))
        ui.result(f"已连接 {client.url}，共 {len(tools)} 个工具", f"Token 来自 {source}")
        missing = [t for t in REQUIRED_TOOLS if t not in tools]
        for t in REQUIRED_TOOLS:
            ok = t not in missing
            ui.console.print(Text.assemble(("     ", ""), ("✓ " if ok else "✗ ", ui.GREEN if ok else ui.RED),
                                           (t, "" if ok else ui.RED)))
        extra = [t for t in tools if t not in REQUIRED_TOOLS]
        _out(connected=True, url=client.url, tools=len(tools), missing=missing, extra=extra)
        if extra:
            ui.result(f"服务端还有 {len(extra)} 个新工具：{'、'.join(extra)}")
        if missing:
            ui.say(Text(f"有 {len(missing)} 个工具不可用，相关命令可能用不了。", style=ui.AMBER))
        else:
            ui.say(Text("一切正常，开吃吧。", style=ui.GREEN))
    _run("doctor", go)


# ================================================================== login
@app.command()
def login(
    token: Optional[str] = typer.Option(None, "--token", help="直接传入 Token（给脚本用）；不传则安全地提示输入。"),
) -> None:
    """登录：粘贴一次 MCP Token，之后就不用再管了。"""
    def go() -> None:
        t = (token or "").strip()
        if not t and not state.json:
            ui.say(Text.assemble(("在 ", ""), ("https://open.mcd.cn/mcp", f"underline {ui.ACCENT}"),
                                 (" 用手机号登录，点「控制台 → 激活」复制 Token，粘贴到下面（输入不会显示）：", "")))
            ui.console.print()
            t = typer.prompt("  MCP Token", hide_input=True, prompt_suffix=" › ").strip()
        if not t:
            raise McdError("没有拿到 Token。用 mcd login 再试一次，或者 mcd login --token <Token>")
        client = DemoClient() if state.demo else McdClient(token=t)
        try:
            with ui.thinking("验证中"):
                tools = client.list_tools()
        finally:
            client.close()
        if state.demo:  # never overwrite a real saved token from demo mode
            _out(logged_in=False, demo=True, tools=len(tools))
            ui.result(f"演示模式：流程正常（{len(tools)} 个工具），Token 没有保存")
            return
        path = save_token(t)
        _out(logged_in=True, tools=len(tools), token_file=str(path))
        ui.console.print()
        ui.console.print(Text.assemble((ui.BULLET + " ", ui.GREEN), ("tools/list", "bold"), (" (MCP)", ui.DIM)))
        ui.result(f"Token 有效，麦当劳 MCP 提供 {len(tools)} 个工具")
        ui.say(Text.assemble(("登录好了。Token 保存在 ", ""), (str(path), "bold"), ("，只有你自己能读。", "")))
        ui.console.print()
        ui.tip(Text.assemble(("试试 ", ui.DIM), ui.cmd("mcd"), (" 看看今天的简报", ui.DIM)))
    _run("login", go)


@app.command()
def logout() -> None:
    """退出登录：删除本机保存的 Token。"""
    def go() -> None:
        removed = clear_token()
        _out(logged_out=removed)
        ui.say("已删除本机保存的 Token。" if removed else "本机没有保存的 Token。")
    _run("logout", go)


# ================================================================== skill (for AI agents)
@skill_app.command("show")
def skill_show() -> None:
    """打印给 AI 看的使用指南（SKILL.md）。没有技能系统的 agent 读这一份就够了。"""
    typer.echo(agent.skill_text())


@skill_app.command("install")
def skill_install(
    dir: Optional[str] = typer.Option(None, "--dir", help="技能目录，默认 ~/.claude/skills（Claude Code）。"),
) -> None:
    """把 Skill 安装到 agent 的技能目录，装好后 agent 会自动知道怎么用 mcd。"""
    path = agent.install_skill(dir)
    if state.json:
        typer.echo(json.dumps({"ok": True, "command": "skill install", "path": str(path)}, ensure_ascii=False))
    else:
        ui.say(Text.assemble(("Skill 装好了：", ""), (str(path), "bold")))
        ui.tip("重启或新开一个 agent 会话就能用。别的 agent 可以用 --dir 指定它的技能目录。")


# ================================================================== web
@app.command()
def web(
    port: int = typer.Option(0, "--port", help="端口，默认随机。"),
    no_open: bool = typer.Option(False, "--no-open", help="不自动打开浏览器。"),
    self_check: bool = typer.Option(False, "--self-test", hidden=True, help="自检后退出（测试用）。"),
) -> None:
    """网页版：在浏览器里看活动、点餐、扫码付款，和终端用的是同一个引擎。"""
    from .web import serve, self_test

    if state.json:
        raise typer.BadParameter("mcd web 是给人看的网页，不支持 --json")
    if self_check:
        results = self_test(state.demo)
        for name, ok in results:
            typer.echo(("✓ " if ok else "✗ ") + name)
        bad = [n for n, ok in results if not ok]
        typer.echo("web self-test passed" if not bad else f"web self-test failed: {', '.join(bad)}")
        raise typer.Exit(1 if bad else 0)
    ui.banner("web", state.demo)
    try:
        httpd, url = serve(demo=state.demo, port=port, open_browser=not no_open)
    except OSError as e:
        ui.error(f"启动失败：{e}")
        raise typer.Exit(1)
    ui.say(Text.assemble(("网页版已经打开：", ""), (url, f"underline {ui.ACCENT}")))
    ui.console.print()
    ui.tip("只在你这台电脑上可以访问，Token 不会发给网页。用完按 Ctrl+C 关掉。")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        ui.console.print()
        ui.result(Text("网页版已关闭", style=ui.DIM))


# ================================================================== short names
# `mcd o 巨无霸` is `mcd order 巨无霸`. Aliases are hidden from the command list and
# listed once in the epilog of `mcd -h` instead, so the list stays readable.
ALIASES = {"o": order, "m": menu, "t": track, "p": portfolio, "s": spend, "st": stores,
           "n": nutrition, "cal": calendar, "w": web}
for _alias, _fn in ALIASES.items():
    app.command(_alias, hidden=True)(_fn)
app.add_typer(config_app, name="c", hidden=True)
app.info.epilog = ("简写：[bold]o[/] order · [bold]m[/] menu · [bold]t[/] track · [bold]p[/] portfolio · "
                   "[bold]s[/] spend · [bold]st[/] stores · [bold]n[/] nutrition · [bold]c[/] config · "
                   "[bold]cal[/] calendar · [bold]w[/] web　　常用参数：-d 外送 · -n 只看不下单 · -y 跳过确认 · "
                   "-c 城市 · -l 附近 · -h 帮助\n\n"
                   "遇到问题或有想法，欢迎提 Issue：https://github.com/Zhangfengmo/mcd-terminal/issues")


if __name__ == "__main__":
    app()

