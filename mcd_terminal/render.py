"""Terminal UI in the visual language of Claude Code.

- `⏺ tool (MCP)` lines for each MCP call, with `⎿` result lines underneath
- a `✻` star spinner with a playful verb and elapsed time
- borderless tables indented under the bullet they belong to
- a rounded permission box with arrow-key selection before anything irreversible
"""
from __future__ import annotations

import os
import random
import sys
import time
from contextlib import contextmanager
from datetime import date
from typing import Any, Callable, Iterator, Sequence

from rich import box
from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.padding import Padding
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .valuation import Account, Coupon, MarketItem, Plan

# ------------------------------------------------------------------ theme
ACCENT = "#D97757"   # Claude clay
GREEN = "#4EBA65"
RED = "#FF6B80"
AMBER = "#E5A84B"
DIM = "grey58"
FAINT = "grey42"

BULLET = "⏺" if sys.platform == "darwin" else "●"
ELBOW = "⎿"
STAR_FRAMES = "·✢✳✶✻✽"

VERBS = ["炸薯条中", "煎肉饼中", "打奶昔中", "摇麦旋风中", "热油中", "夹生菜中",
         "撒盐中", "装袋中", "数积分中", "比价中", "排队取餐中", "叫号中"]

console = Console(highlight=False)
REAL_CONSOLE = console

# Agent mode (--json): human output is swallowed and prompts never block.
AUTO_DECLINE = False


def set_quiet(quiet: bool) -> None:
    """Swallow all human-facing output (used by --json), or restore it."""
    global console, AUTO_DECLINE
    import io
    console = Console(file=io.StringIO(), highlight=False) if quiet else REAL_CONSOLE
    AUTO_DECLINE = quiet


def _indent(r: RenderableType, n: int = 2) -> Padding:
    return Padding(r, (0, 0, 0, n), expand=False)


def _hang(prefix: Text, body: Text) -> Table:
    """Prefix in its own column so wrapped lines stay aligned under the body."""
    g = Table.grid(padding=0)
    g.add_column(no_wrap=True)
    g.add_column(overflow="fold")
    g.add_row(prefix, body)
    return g


# ------------------------------------------------------------------ banner
def banner(command: str, demo: bool) -> None:
    title = Text()
    title.append("✻ ", style=ACCENT)
    title.append("欢迎使用", style="bold")
    title.append(" 麦麦交易终端", style=f"bold {ACCENT}")
    help_line = Text("  mcd --help 查看全部命令", style=DIM)
    meta = Text("  ", style=FAINT)
    meta.append(f"{command}", style=FAINT)
    meta.append("  ·  ", style=FAINT)
    meta.append("演示数据" if demo else "mcp.mcd.cn", style=AMBER if demo else FAINT)
    meta.append(f"  ·  {date.today():%Y-%m-%d}", style=FAINT)
    console.print(Panel(Group(title, Text(""), help_line, meta), box=box.ROUNDED,
                        border_style=ACCENT, padding=(0, 1), expand=False))


# ------------------------------------------------------------------ spinner
class _Thinking:
    """Ping-pong star spinner: `✻ 炸薯条中… (3s · ctrl+c 取消)  detail`."""

    def __init__(self, verb: str) -> None:
        self.verb = verb
        self.detail = ""
        self.start = time.monotonic()
        self._seq = STAR_FRAMES + STAR_FRAMES[-2:0:-1]

    def __rich__(self) -> Text:
        t = time.monotonic() - self.start
        t_txt = Text()
        t_txt.append(self._seq[int(t * 8) % len(self._seq)] + " ", style=ACCENT)
        t_txt.append(f"{self.verb}…", style=ACCENT)
        t_txt.append(f" ({t:.0f}s · ctrl+c 取消)", style=FAINT)
        if self.detail:
            t_txt.append(f"  {self.detail}", style=DIM)
        return t_txt


@contextmanager
def thinking(verb: str | None = None) -> Iterator[_Thinking]:
    spin = _Thinking(verb or random.choice(VERBS))
    with Live(spin, console=console, transient=True, refresh_per_second=12):
        yield spin


# ------------------------------------------------------------------ tool calls
def _args_text(args: dict[str, Any] | None) -> str:
    if not args:
        return ""
    return "(" + ", ".join(f"{k}: {v}" for k, v in args.items()) + ")"


def tool_line(name: str, args: dict[str, Any] | None = None, ok: bool = True, times: int = 1) -> None:
    console.print()
    t = Text()
    t.append(BULLET + " ", style=GREEN if ok else RED)
    t.append(name, style="bold")
    if times > 1:
        t.append(f" x{times}", style="bold")
    t.append(" (MCP)", style=DIM)
    t.append(_args_text(args), style=DIM)
    console.print(t)


def result(*lines: str | Text, style: str = DIM) -> None:
    """`  ⎿  first line` then aligned continuation lines."""
    for i, ln in enumerate(lines):
        prefix = Text(f"  {ELBOW}  " if i == 0 else "     ", style=FAINT)
        body = ln if isinstance(ln, Text) else Text(str(ln), style=style)
        console.print(_hang(prefix, body))


class ShownError(Exception):
    """An error already rendered to the user; just exit."""


def call(client: Any, name: str, args: dict[str, Any] | None = None,
         summary: Callable[[Any], str | Text | Sequence[str | Text]] | None = None) -> Any:
    """Run one MCP tool call with a spinner, then print `⏺ name` + `⎿ summary`."""
    from .client import McdError

    with thinking():
        try:
            data = client.call(name, args)
        except McdError as e:
            err = e
        else:
            err = None
    if err is not None:
        tool_line(name, ok=False)
        result(str(err), style=RED)
        raise ShownError(str(err)) from err
    tool_line(name)
    if summary:
        out = summary(data)
        result(*(out if isinstance(out, (list, tuple)) else [out]))
    return data


def say(message: str | Text) -> None:
    """An answer line, like Claude's own messages."""
    console.print()
    body = message if isinstance(message, Text) else Text(message)
    console.print(_hang(Text(BULLET + " "), body))


def tip(message: str | Text) -> None:
    body = message if isinstance(message, Text) else Text(message, style=DIM)
    console.print(_hang(Text("  ※ ", style=FAINT), body))


def footer(seconds: float) -> None:
    console.print()
    console.print(Text(f"✻ 出餐用时 {seconds:.1f}s", style=FAINT))


def error(message: str) -> None:
    console.print()
    console.print(_hang(Text(BULLET + " ", style=RED), Text(message, style=RED)))


# ------------------------------------------------------------------ helpers
def yuan(fen: int | None) -> str:
    return "—" if fen is None else f"¥{fen / 100:,.2f}"


def meter(ratio: float, width: int = 20, style: str = ACCENT) -> Text:
    ratio = max(0.0, min(ratio, 1.0))
    filled = round(ratio * width)
    t = Text("█" * filled, style=style)
    t.append("░" * (width - filled), style=FAINT)
    return t


def _table(*cols: tuple[str, str]) -> Table:
    tbl = Table(box=None, show_edge=False, pad_edge=False, padding=(0, 3, 0, 0),
                header_style=DIM)
    for name, justify in cols:
        tbl.add_column(name, justify=justify)  # type: ignore[arg-type]
    return tbl


def _days_style(d: int | None) -> str:
    if d is None:
        return DIM
    return RED if d <= 3 else (AMBER if d <= 7 else GREEN)


# ------------------------------------------------------------------ portfolio
def portfolio(acct: Account, coupons: list[Coupon], today: date) -> None:
    ratio = acct.at_risk / acct.available if acct.available else 0.0
    head = Text()
    head.append("可用 ")
    head.append(f"{acct.available:,}", style=f"bold {ACCENT}")
    head.append(" 积分")
    if acct.at_risk:
        head.append("，其中 ")
        head.append(f"{acct.at_risk:,}", style=f"bold {RED}")
        head.append(f" 将在两个月内过期（{ratio:.0%}）。")
    else:
        head.append("，近两个月没有积分过期。", style=GREEN)
    say(head)
    console.print()

    pts = _table(("积分", "left"), ("", "right"), ("", "left"))
    risk = RED if acct.at_risk else GREEN
    pts.add_row("可用", Text(f"{acct.available:,}", style="bold"), "")
    pts.add_row("本月到期", Text(f"{acct.expiring_this_month:,}", style=risk if acct.expiring_this_month else DIM), "")
    pts.add_row("下月到期", Text(f"{acct.expiring_next_month:,}", style=risk if acct.expiring_next_month else DIM),
                meter(ratio, style=RED) if acct.at_risk else Text(""))
    pts.add_row(Text("冻结", style=DIM), Text(f"{acct.frozen:,}", style=DIM), "")
    pts.add_row(Text("历史累计", style=DIM), Text(f"{acct.accumulated:,.0f}", style=DIM),
                Text(f"已用 {acct.used:,.0f}", style=FAINT))
    console.print(_indent(pts))
    console.print()

    cps = _table((f"优惠券 · {len(coupons)} 张", "left"), ("用券价", "right"), ("到期", "right"), ("", "right"))
    for c in sorted(coupons, key=lambda c: c.days_left(today) if c.end else 10**6):
        d = c.days_left(today)
        left = Text("—" if d is None else ("今天到期" if d == 0 else f"还剩 {d} 天"), style=_days_style(d))
        cps.add_row(c.title, f"¥{c.price}" if c.price else "—",
                    Text(f"{c.end:%m-%d}" if c.end else "—", style=DIM), left)
    if not coupons:
        cps.add_row(Text("暂无可用优惠券", style=DIM), "", "", "")
    console.print(_indent(cps))

    console.print()
    if acct.at_risk:
        tip(Text.assemble(("运行 ", DIM), ("mcd spend --expiring", ACCENT), (" 看看快过期的积分怎么换最划算", DIM)))
    elif not coupons:
        tip(Text.assemble(("运行 ", DIM), ("mcd claim", ACCENT), (" 一键领取麦麦省的券", DIM)))


# ------------------------------------------------------------------ market
def market(items: list[MarketItem]) -> None:
    priced = [i for i in items if i.fen_per_point]
    if priced:
        best = priced[0]
        say(Text.assemble(
            (f"估值了 {len(items)} 个商品，", ""), (best.name, "bold"), ("最划算：每积分值 ", ""),
            (f"{best.fen_per_point:.2f}", f"bold {ACCENT}"), (" 分。", ""),
        ))
    else:
        say(f"拉取到 {len(items)} 个商品，但都没有参考价，无法估值。")
    console.print()

    hi = max((i.fen_per_point for i in priced), default=1.0) or 1.0
    tbl = _table(("#", "right"), ("商品", "left"), ("积分", "right"), ("价值", "right"),
                 ("分/积分", "right"), ("", "left"), ("skuId", "right"))
    for n, i in enumerate(items, 1):
        fpp = i.fen_per_point
        name = Text(i.name)
        if i.is_physical:
            name.append(" 实物", style=FAINT)
        if fpp is None:
            rate, bar = Text("—", style=DIM), Text("")
        else:
            style = ACCENT if n <= 3 else DIM
            rate = Text(f"{fpp:.2f}", style=f"bold {ACCENT}" if n <= 3 else "")
            bar = meter(fpp / hi, width=12, style=style)
        tbl.add_row(Text(str(n), style=FAINT), name, f"{i.points:,}", yuan(i.value_fen), rate, bar,
                    Text(str(i.sku_id or "—"), style=FAINT))
    console.print(_indent(tbl))
    console.print()
    tip("价值 = 参考价减去用券时还要付的钱，只用于比较性价比，以门店价格为准")


# ------------------------------------------------------------------ plan
def plan(p: Plan, reason: str) -> None:
    if not p.picks:
        say(f"{reason}预算 {p.budget:,} 积分内没有可兑换的餐品券。")
        return
    avg = p.value_fen / p.points_used if p.points_used else 0
    say(Text.assemble(
        (f"{reason}用 ", ""), (f"{p.points_used:,}", f"bold {ACCENT}"), (" 积分换到 ", ""),
        (yuan(p.value_fen), f"bold {GREEN}"), (f"，平均 {avg:.2f} 分/积分", ""),
        (f"，剩 {p.leftover:,} 积分。", DIM),
    ))
    console.print()
    tbl = _table(("兑换方案", "left"), ("", "right"), ("积分", "right"), ("参考价值", "right"), ("skuId", "right"))
    for item, n in p.picks:
        tbl.add_row(Text.assemble(("+ ", GREEN), (item.name, "")), f"x{n}", f"{item.points * n:,}",
                    yuan((item.value_fen or 0) * n), Text(str(item.sku_id), style=FAINT))
    tbl.add_row(Text("  合计", style=DIM), "", Text(f"{p.points_used:,}", style="bold"),
                Text(yuan(p.value_fen), style=f"bold {GREEN}"), "")
    console.print(_indent(tbl))


def next_steps(commands: list[str], note: str = "") -> None:
    console.print()
    console.print(Text("  下一步", style=DIM))
    for c in commands:
        console.print(Text(f"    {c}", style=ACCENT))
    if note:
        console.print(Text(f"    {note}", style=FAINT))


def checklist(rows: list[tuple[str, bool, str]]) -> None:
    """Claude Code todo style: ☒ done / ☐ open."""
    for title, done, note in rows:
        t = Text("     ")
        if done:
            t.append("☒ ", style=GREEN)
            t.append(title, style=f"{DIM} strike")
        else:
            t.append("☐ ", style=ACCENT)
            t.append(title)
        if note:
            t.append(f"  {note}", style=FAINT)
        console.print(t)


# ------------------------------------------------------------------ permission prompt
def _read_key() -> str:
    """Return 'up', 'down', 'enter', 'esc', or a single character."""
    if os.name == "nt":  # pragma: no cover - Windows
        import msvcrt
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            return {"H": "up", "P": "down"}.get(msvcrt.getwch(), "")
        if ch == "\x03":
            raise KeyboardInterrupt
        return {"\r": "enter", "\x1b": "esc"}.get(ch, ch)

    import select
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        data = os.read(fd, 16)
        # Arrow keys arrive as ESC [ A / ESC [ B; over SSH or web terminals the bytes can be
        # split across reads, so give a lone ESC a moment before treating it as "cancel".
        while data.endswith(b"\x1b") or data in (b"\x1b[", b"\x1bO"):
            if not select.select([fd], [], [], 0.3)[0]:
                break
            data += os.read(fd, 16)
        text = data.decode("utf-8", "ignore")
        if text.startswith("\x1b"):
            if text[1:3] in ("[A", "OA"):
                return "up"
            if text[1:3] in ("[B", "OB"):
                return "down"
            return "esc" if text == "\x1b" else ""
        ch = text[:1]
        if ch == "\x03":
            raise KeyboardInterrupt
        return {"\n": "enter", "\r": "enter"}.get(ch, ch)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _prompt_box(title: str, details: Sequence[str | Text], question: str,
                options: Sequence[str], selected: int) -> Panel:
    body: list[RenderableType] = [Text(title, style="bold"), Text("")]
    for d in details:
        body.append(Text.assemble(("  ", ""), d if isinstance(d, Text) else Text(str(d))))
    body += [Text(""), Text(question)]
    for i, opt in enumerate(options):
        if i == selected:
            body.append(Text(f"❯ {i + 1}. {opt}", style=ACCENT))
        else:
            body.append(Text(f"  {i + 1}. {opt}"))
    return Panel(Group(*body), box=box.ROUNDED, border_style=ACCENT, padding=(0, 1), expand=False)


def ask_text(question: str, hint: str = "") -> str | None:
    """One line of free text (e.g. a location). None in agent mode or when left empty."""
    if AUTO_DECLINE:
        return None
    console.print()
    console.print(_hang(Text(BULLET + " ", style=ACCENT), Text(question, style="bold")))
    if hint:
        console.print(Text(f"  {hint}", style=DIM))
    console.print(Text("  › ", style=ACCENT), end="")
    try:
        answer = (sys.stdin.readline() or "").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if not (console.is_terminal and sys.stdin.isatty()):
        console.print(Text(answer, style=DIM))  # input isn't echoed when piped
    return answer or None


def select(title: str, details: Sequence[str | Text], question: str, options: Sequence[str]) -> int | None:
    """Claude Code style prompt. Returns the chosen option index, or None if dismissed.

    The last option is treated as the "no" answer (n / Esc pick it).
    """
    if AUTO_DECLINE:
        return None
    console.print()
    interactive = console.is_terminal and sys.stdin.isatty()
    if not interactive:
        console.print(_prompt_box(title, details, question, options, 0))
        console.print(Text(f"输入 1-{len(options)}（或 y/n）：", style=DIM), end="")
        answer = (sys.stdin.readline() or "").strip().lower()
        console.print(Text(answer, style=DIM))  # input isn't echoed when piped
        if answer in ("y", "yes", "是"):
            return 0
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return int(answer) - 1
        return len(options) - 1
    selected = 0
    with Live(_prompt_box(title, details, question, options, selected), console=console,
              transient=True, auto_refresh=False) as live:
        while True:
            key = _read_key()
            if key == "up":
                selected = (selected - 1) % len(options)
            elif key == "down":
                selected = (selected + 1) % len(options)
            elif key.isdigit() and 1 <= int(key) <= len(options):
                selected = int(key) - 1
                break
            elif key in ("y", "Y"):
                selected = 0
                break
            elif key in ("n", "N", "esc"):
                selected = len(options) - 1
                break
            elif key == "enter":
                break
            live.update(_prompt_box(title, details, question, options, selected), refresh=True)
    return selected


def ask(title: str, details: Sequence[str | Text], question: str = "要继续吗？",
        options: Sequence[str] = ("是", "否，取消")) -> bool:
    """Yes/no permission prompt. Returns True only for the first option."""
    choice = select(title, details, question, options)
    ok = choice == 0
    if choice is not None:
        console.print(Text.assemble((BULLET + " ", ACCENT if ok else DIM), (title, "bold")))
        result(Text("已确认" if ok else "已取消", style=GREEN if ok else DIM))
    return ok


def extra_text(x: Any, points_left: int, expiring: bool) -> Text:
    """One friendly line for a suggested add-on."""
    if x.kind == "points":
        if x.pay_fen:
            t = Text.assemble((f"剩下的 {points_left:,} 积分能换一张券，加一份", ""), (x.menu.name, "bold"),
                              ("只要 ", ""), (yuan(x.pay_fen), f"bold {GREEN}"),
                              (f"（{x.points:,} 积分，省 {yuan(x.saving_fen)}）", DIM))
        else:
            t = Text.assemble((f"剩下的 {points_left:,} 积分", ""), ("还能免费带一个", ""), (x.menu.name, "bold"),
                              (f"（{x.points:,} 积分，价值 {yuan(x.menu.price_fen)}）", DIM))
        if expiring:
            t.append("，这些积分快过期了", style=AMBER)
        return t
    if x.kind == "promo":
        return Text.assemble((x.menu.name, "bold"), ("第二份半价，再来一份只要 ", ""),
                             (yuan(x.pay_fen), f"bold {GREEN}"))
    when = ""
    if x.days_left is not None and 0 <= x.days_left <= 3:
        when = "今天" if x.days_left == 0 else ("明天" if x.days_left == 1 else f"{x.days_left} 天后")
    t = Text.assemble(("你有张「", ""), (x.coupon.title if x.coupon else "", "bold"), ("」", ""))
    if when:
        t.append(f"{when}就过期", style=AMBER)
    t.append("，带一份" + x.menu.name + "只要 ")
    t.append(yuan(x.pay_fen), style=f"bold {GREEN}")
    t.append(f"（省 {yuan(x.saving_fen)}）", style=DIM)
    return t


def quote_line(q: dict[str, Any] | None, plan_pay_fen: int) -> None:
    """Show how the live quote differs from our estimate."""
    if not q:
        return
    notes = []
    if q.get("promo_fen"):
        notes.append(f"门店活动再省 {yuan(q['promo_fen'])}")
    if q.get("delivery_fen"):
        notes.append(f"配送费 {yuan(q['delivery_fen'])}")
    if notes:
        tip(Text.assemble(("核价后实付 ", DIM), (yuan(q["pay_fen"]), f"bold {GREEN}"), (f"（{'，'.join(notes)}）", DIM)))


# ------------------------------------------------------------------ order
def order_plan(p: "OrderPlan") -> None:  # noqa: F821 - imported lazily to avoid a cycle
    n_coupon = sum(1 for c in p.choices if c.kind == "coupon")
    n_points = sum(1 for c in p.choices if c.kind == "points")
    how = []
    if n_coupon:
        how.append(f"{n_coupon} 张已有券")
    if p.points_used:
        how.append(f"{p.points_used:,} 积分")
    msg = Text.assemble((f"这单原价 {yuan(p.original_fen)}", ""))
    if how:
        msg.append("，用 " + " + ".join(how) + " 叠加后实付 ")
        msg.append(yuan(p.pay_fen), style=f"bold {GREEN}")
        msg.append("，省 ")
        msg.append(yuan(p.saving_fen), style=f"bold {ACCENT}")
        if p.points_used:
            pts_saving = sum(c.saving_fen for c in p.choices if c.kind == "points")
            msg.append(f"（积分部分 {pts_saving / p.points_used:.2f} 分/积分）", style=DIM)
        msg.append("。")
    else:
        msg.append("，没有可叠加的券或积分，按原价支付。")
    say(msg)
    console.print()

    # Merge identical lines: same item paid the same way.
    groups: dict[tuple, list] = {}
    for c in p.choices:
        key = (c.unit.menu.code, c.kind, c.coupon.coupon_id if c.coupon else "", c.mall.spu_id if c.mall else 0)
        if c.kind == "coupon":  # each coupon is its own line
            key = key + (id(c),)
        groups.setdefault(key, []).append(c)

    tbl = _table(("商品", "left"), ("", "right"), ("原价", "right"), ("怎么付", "left"), ("实付", "right"))
    for cs in groups.values():
        c, n = cs[0], len(cs)
        if c.kind == "coupon" and c.coupon:
            how_t = Text.assemble(("券 ", AMBER), (c.coupon.title, ""))
        elif c.kind == "points" and c.mall:
            how_t = Text.assemble(("积分 ", ACCENT), (f"{c.points * n:,} 兑「{c.mall.name}」", ""))
        else:
            how_t = Text("现金", style=DIM)
        pay = sum(x.pay_fen for x in cs)
        tbl.add_row(c.unit.menu.name, Text(f"x{n}" if n > 1 else "", style=FAINT),
                    Text(yuan(c.unit.menu.price_fen * n), style=DIM), how_t,
                    Text(yuan(pay), style=GREEN if c.saving_fen else ""))
    tbl.add_row(Text("合计", style=DIM), "", Text(yuan(p.original_fen), style=DIM),
                Text(f"{p.points_used:,} 积分" if p.points_used else "", style=ACCENT),
                Text(yuan(p.pay_fen), style=f"bold {GREEN}"))
    console.print(_indent(tbl))


def pay_link(url: str, amount_fen: int | None) -> None:
    """付款：终端里直接画出手机要扫的二维码（jumpToApp，扫了就进 App 收银台），再给电脑上的支付页链接。"""
    from .pay import scan_url, terminal_qr
    scan = scan_url(url) or url
    say(Text.assemble(("订单已创建，待支付 ", ""), (yuan(amount_fen), f"bold {GREEN}"),
                      ("。用手机扫码（微信或相机都行），在麦当劳 App 里付款：", "")))
    qr = terminal_qr(scan) if console.is_terminal and not os.environ.get("NO_COLOR") else None
    if qr:
        console.print()
        for line in qr:
            console.print(Text.assemble(("  ", ""), (line, "black on white")))
        console.print()
    else:
        console.print(Text.assemble(("  手机打开：", DIM), (scan, f"underline {ACCENT}")))
    console.print(Text.assemble(("  电脑上打开支付页：", DIM), (url, f"underline {ACCENT}")))


# ------------------------------------------------------------------ generic pieces
def step(title: str, *lines: str | Text) -> None:
    """A local step (not an MCP call): `⏺ title` + `⎿ lines`."""
    console.print()
    console.print(Text.assemble((BULLET + " ", ACCENT), (title, "bold")))
    if lines:
        result(*lines)


def bullets(rows: Sequence[tuple[str, str | Text]], indent: int = 2) -> None:
    """Icon + text rows, used by the daily brief."""
    for icon, body in rows:
        b = body if isinstance(body, Text) else Text(body)
        console.print(_hang(Text(" " * indent + icon + " "), b))


def cmd(text: str) -> Text:
    return Text(text, style=ACCENT)


def simple_table(columns: Sequence[tuple[str, str]], rows: Sequence[Sequence[str | Text]]) -> None:
    tbl = _table(*columns)
    tbl.show_header = any(name for name, _ in columns)
    for col in tbl.columns[:-1]:
        col.no_wrap = True  # only the last column may wrap
    for r in rows:
        tbl.add_row(*[c if isinstance(c, Text) else Text(str(c)) for c in r])
    console.print(_indent(tbl))


def faint(s: str) -> Text:
    return Text(s, style=FAINT)


def dim(s: str) -> Text:
    return Text(s, style=DIM)


def big_code(label: str, code: str) -> None:
    """A large, easy-to-read code (pickup code) in a rounded box."""
    body = Text.assemble((f"{label}  ", DIM), (" ".join(code), f"bold {ACCENT}"))
    console.print(_indent(Panel(body, box=box.ROUNDED, border_style=ACCENT, padding=(0, 2), expand=False)))


def greeting(hour: int) -> str:
    if 5 <= hour < 10:
        return "早上好 ☀️"
    if 10 <= hour < 14:
        return "中午好 🍔"
    if 14 <= hour < 18:
        return "下午好 ☕"
    if 18 <= hour < 23:
        return "晚上好 🌙"
    return "夜深了，早点休息 🌛"


def meal_hint(hour: int) -> str:
    if 5 <= hour < 10:
        return "早餐别空着肚子"
    if 10 <= hour < 14:
        return "午饭时间到了"
    if 14 <= hour < 18:
        return "来点下午茶？"
    if 18 <= hour < 21:
        return "晚饭想好吃什么了吗"
    return "忙到这么晚辛苦了，饿了就吃点东西"


def gather(client: Any, calls: Sequence[tuple[str, dict[str, Any] | None]], title: str) -> list[Any]:
    """Several read-only MCP calls under one spinner, shown as a single collapsed line."""
    from .client import McdError

    out: list[Any] = []
    with thinking() as spin:
        for n, (name, args) in enumerate(calls, 1):
            spin.detail = f"({n}/{len(calls)}) {name}"
            try:
                out.append(client.call(name, args))
            except McdError as e:
                tool_line(name, ok=False)
                result(str(e), style=RED)
                raise ShownError(str(e)) from e
    console.print()
    console.print(Text.assemble((BULLET + " ", GREEN), (title, "bold"), (f" (MCP x{len(calls)})", DIM)))
    result(" · ".join(name for name, _ in calls), style=FAINT)
    return out


def meal_pick(hour: int) -> str:
    if 5 <= hour < 10:
        return "中杯拿铁"
    if 14 <= hour < 18:
        return "麦旋风 中杯美式"
    if hour >= 21 or hour < 5:
        return "麦辣鸡腿堡 中份薯条"
    return "巨无霸 中杯拿铁"
