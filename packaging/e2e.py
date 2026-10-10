#!/usr/bin/env python3
"""End-to-end loop test of the whole CLI, run against a real executable.

    python packaging/e2e.py python -m mcd_terminal     # the source tree
    python packaging/e2e.py ./build/.../mcd            # a packaged binary

Every command and subcommand is run in demo mode (help text, the human UI, the --json
agent mode, confirmations accepted and declined), in the order a real user would go:
look around, plan, redeem, order, track, cancel. Any non-zero exit, Python traceback,
or malformed / unexpected JSON fails the run. Stdlib only, so it runs anywhere.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# Every command the CLI registers; tests/test_e2e.py checks this list is complete.
COMMANDS = [
    "today", "portfolio", "market", "spend", "buy", "claim", "order", "menu", "nutrition", "stores",
    "address", "address add", "prizes", "events", "party", "remind", "web", "config", "config mode", "config store", "config address", "config city",
    "config points", "config take-way", "config reset", "track", "history", "orders", "cancel", "calendar", "doctor", "login",
    "logout", "skill", "skill show", "skill install",
]

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
YES = "y\n" * 12   # answer "yes" to every prompt
NO = "n\n" * 12    # decline every prompt


def scenarios(skill_dir: str) -> list[tuple[str, list[str], str | None, dict]]:
    """(name, args, stdin, expectations): json=True, status=..., contains=[...], lacks=[...]."""
    s: list[tuple[str, list[str], str | None, dict]] = []
    add = lambda name, args, stdin=None, **exp: s.append((name, args, stdin, exp))  # noqa: E731

    add("version", ["--version"], contains=["mcd-terminal"])
    add("help", ["--help"], contains=["order"])
    for c in COMMANDS:
        add(f"help: {c}", [*c.split(), "--help"], contains=["Usage"])

    # look around
    add("today (default command)", ["--demo"], contains=["积分"])
    add("today --json", ["--demo", "--json", "today"], json=True)
    add("portfolio", ["--demo", "portfolio"])
    add("portfolio --json", ["--demo", "--json", "portfolio"], json=True)
    add("market", ["--demo", "market"], contains=["分/积分"])
    add("market --no-physical --json", ["--demo", "--json", "market", "--no-physical"], json=True)
    add("menu", ["--demo", "menu"])
    add("menu search", ["--demo", "menu", "薯条"], contains=["薯条"])
    add("menu combo detail", ["--demo", "menu", "--detail", "920101"])
    add("menu --json", ["--demo", "--json", "menu", "巨无霸"], json=True)
    add("nutrition", ["--demo", "nutrition"])
    add("nutrition by protein", ["--demo", "nutrition", "--sort", "protein"])
    add("calendar", ["--demo", "calendar"])
    add("calendar --date", ["--demo", "calendar", "--date", "2026-10-10"])
    add("stores near", ["--demo", "stores", "--city", "上海", "--near", "人民广场"])
    add("stores --use", ["--demo", "stores", "--city", "上海", "--near", "人民广场", "--use", "2"])
    add("stores drive", ["--demo", "stores", "--drive", "--city", "上海", "--near", "人民广场"])
    add("address list", ["--demo", "address"])
    add("address add", ["--demo", "address", "add", "--city", "上海市", "--name", "麦麦", "--phone", "13800000000",
                        "--street", "人民大道 200 号", "--detail", "3 楼"])
    add("history", ["--demo", "history"])
    add("prizes", ["--demo", "prizes"], contains=["积分抽奖"])
    add("prizes --json", ["--demo", "--json", "prizes"], json=True)
    add("events", ["--demo", "events"], contains=["生日派对"])
    add("events --json", ["--demo", "--json", "events"], json=True)
    add("party sessions", ["--demo", "party", "生日派对", "-c", "上海"], contains=["余 1"])
    add("party --json", ["--demo", "--json", "party", "生日派对", "-c", "上海"], json=True, status="listed")
    add("party needs a city", ["--demo", "--json", "party", "生日派对", "-c", "火星"], exit_code=1, contains=["choose_city"])
    add("remind coupons --json needs confirmation", ["--demo", "--json", "remind", "coupons"], json=True,
        status="needs_confirmation")
    add("remind coupons (demo writes a calendar file)", ["--demo", "remind", "coupons", "-y"], contains=[".ics"])
    add("remind points", ["--demo", "--json", "remind", "points", "-y"], json=True, status="done")
    add("remind campaign", ["--demo", "--json", "remind", "campaign", "-t", "甜品", "-y"], json=True, status="done")
    add("remind party", ["--demo", "--json", "remind", "party", "-t", "生日派对", "--date", "2026-10-12", "--at", "10:30", "-y"],
        json=True, status="done")
    add("web (self-test: page, API, QR, image proxy, security)", ["--demo", "web", "--self-test"],
        contains=["web self-test passed"])
    add("history detail", ["--demo", "history", "ECS1211037028709736448"])
    add("orders", ["--demo", "orders"])
    add("doctor", ["--demo", "doctor"], contains=["31"])

    # saved defaults
    add("config show", ["--demo", "config"], contains=["点餐方式"])
    add("config --json", ["--demo", "--json", "config"], json=True)
    add("config mode", ["--demo", "config", "mode", "delivery"], contains=["麦乐送"])
    add("config mode (中文)", ["--demo", "config", "mode", "外卖"], contains=["麦乐送"])
    add("config store", ["--demo", "config", "store", "--city", "上海", "--near", "人民广场", "--pick", "2"],
        contains=["记住了"])
    add("config store asks where", ["--demo", "config", "store"], "上海 人民广场\n", contains=["记住了"])
    add("config drive store", ["--demo", "config", "store", "--drive", "--city", "上海", "--near", "人民广场"])
    add("config address (only one)", ["--demo", "config", "address"], contains=["记住了"])
    add("config address by id", ["--demo", "--json", "config", "address", "A1"], json=True)
    add("config city", ["--demo", "config", "city", "上海"])
    add("config points", ["--demo", "config", "points", "500"], contains=["500"])
    add("config points off", ["--demo", "config", "points", "off"])
    add("config take-way", ["--demo", "config", "take-way", "外带"])
    add("config reset one", ["--demo", "config", "reset", "points"])
    add("config reset all", ["--demo", "config", "reset"])
    add("address add an existing one", ["--demo", "address", "add", "--city", "上海市", "--name", "麦麦",
                                        "--phone", "15200006666", "--street", "人民大道 200 号", "--detail", "3 楼"],
        contains=["不重复添加"], lacks=["delivery-create-address"])
    add("order --pickup flag", ["--demo", "order", "巨无霸", "--pickup", "--dry-run"])

    # plan, then decline and accept
    add("spend --dry-run", ["--demo", "spend", "--dry-run"])
    add("spend declined", ["--demo", "spend"], NO, lacks=["mall-create-order"])
    add("spend --json needs confirmation", ["--demo", "--json", "spend"], json=True, status="needs_confirmation")
    add("spend --expiring --yes", ["--demo", "spend", "--expiring", "--yes"], contains=["换好啦"])
    add("spend --json --yes", ["--demo", "--json", "spend", "--budget", "500", "--yes"], json=True, status="done")
    add("buy declined", ["--demo", "buy", "10588"], NO, lacks=["mall-create-order"])
    add("buy --json needs confirmation", ["--demo", "--json", "buy", "10588"], json=True, status="needs_confirmation")
    add("buy coupon", ["--demo", "buy", "10588", "--yes"], contains=["mall-create-order"])
    add("buy physical to address", ["--demo", "buy", "10630", "--address", "A1", "--yes"], contains=["寄往"])
    add("claim --json", ["--demo", "--json", "claim"], json=True, status="needs_confirmation")
    add("claim accepted", ["--demo", "claim"], YES, contains=["领好了"])

    # order in every mode
    add("order --dry-run", ["--demo", "order", "巨无霸", "中杯拿铁", "薯条", "麦乐鸡", "--dry-run"], contains=["实付"])
    add("order --json plan", ["--demo", "--json", "order", "巨无霸", "中杯拿铁", "--dry-run"], json=True, status="planned")
    add("order --json needs confirmation", ["--demo", "--json", "order", "巨无霸", "中杯拿铁"], json=True,
        status="needs_confirmation")
    add("order declined", ["--demo", "order", "巨无霸"], NO, lacks=["create-order"])
    add("order interactive accepted", ["--demo", "order", "巨无霸", "薯条*2"], YES, contains=["支付"])
    add("order --yes", ["--demo", "order", "巨无霸", "中杯拿铁", "--yes"], contains=["支付"])
    add("order --json --yes", ["--demo", "--json", "order", "麦辣鸡腿堡", "--yes"], json=True, status="ordered")
    add("order no points", ["--demo", "order", "巨无霸", "--no-points", "--dry-run"])
    add("order points cap", ["--demo", "order", "巨无霸", "中杯拿铁", "--points", "500", "--dry-run"])
    add("order other store", ["--demo", "order", "巨无霸", "--city", "上海", "--near", "南京东路", "--pick", "2",
                              "--dry-run"])
    add("order delivery", ["--demo", "order", "巨无霸", "--delivery", "--yes"], contains=["支付"])
    add("order quantity forms", ["--demo", "--json", "order", "巨无霸", "2份薯条", "麦乐鸡x2", "--dry-run"], json=True,
        status="planned")
    add("order item not on menu", ["--demo", "--json", "order", "巨无霸", "火星披萨", "--dry-run"], json=False,
        exit_code=1, contains=["not_on_menu"])
    add("order drive-thru", ["--demo", "order", "巨无霸", "--drive", "--dry-run"])
    add("order group meal", ["--demo", "order", "巨无霸x10", "--group", "--service", "专人分餐", "--dry-run"])
    add("order reservation", ["--demo", "order", "巨无霸", "--at", "2026-10-10 12:00", "--dry-run"])

    # after ordering
    add("track latest", ["--demo", "track"])
    add("track --json", ["--demo", "--json", "track"], json=True)
    add("cancel --json needs confirmation", ["--demo", "--json", "cancel"], json=True, status="needs_confirmation")
    add("cancel declined", ["--demo", "cancel"], NO, lacks=["cancel-order"])
    add("cancel --yes", ["--demo", "cancel", "--reason", "2", "--yes"], contains=["取消"])

    # short names: mcd -h, mcd o … -n, …
    add("-h", ["-h"], contains=["简写"])
    add("o -h", ["o", "-h"], contains=["--dry-run"])
    add("c -h", ["c", "-h"], contains=["Usage"])
    add("o … -n (short flags)", ["--demo", "o", "巨无霸", "麦乐鸡x2", "-n"], contains=["实付"])
    add("-j o … -d -n", ["--demo", "-j", "o", "巨无霸", "-d", "-n"], json=True, status="planned")
    add("-j o … needs confirmation, short flags", ["--demo", "-j", "o", "巨无霸", "-n"], json=True, status="planned")
    add("o … -y", ["--demo", "o", "巨无霸", "-y"], contains=["支付"])
    add("m", ["--demo", "m", "薯条"], contains=["薯条"])
    add("t", ["--demo", "t"])
    add("p", ["--demo", "p"])
    add("s -n", ["--demo", "s", "-n"])
    add("st -c -l", ["--demo", "st", "-c", "上海", "-l", "人民广场"])
    add("n", ["--demo", "n"])
    add("cal", ["--demo", "cal"])
    add("c", ["--demo", "c"], contains=["点餐方式"])
    add("w --self-test", ["--demo", "w", "--self-test"], contains=["web self-test passed"])
    add("c mode", ["--demo", "c", "mode", "外卖"], contains=["麦乐送"])

    # agent setup
    add("skill show", ["skill", "show"], contains=["mcd"])
    add("skill install", ["skill", "install", "--dir", skill_dir])
    add("login (demo: validates, saves nothing)", ["--demo", "login", "--token", "demo-token"], contains=["演示模式"])
    add("login --json (demo)", ["--demo", "--json", "login", "--token", "demo-token"], json=True)
    add("logout", ["logout"])
    return s


def run(cmd: list[str]) -> int:
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as skills:
        # CI runners (GITHUB_ACTIONS) make rich force colours; ANSI codes would split "--dry-run".
        env = dict(os.environ, NO_COLOR="1", MCD_HOME=home, MCD_DEMO_NOW="2026-10-09 12:20", MCD_DEMO_DELAY="0",
                   PYTHONIOENCODING="utf-8", COLUMNS="110")
        env.pop("MCD_MCP_TOKEN", None)
        cases = scenarios(skills)
        for name, args, stdin, exp in cases:
            r = subprocess.run([*cmd, *args], input=stdin, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", env=env, timeout=120)
            out = ANSI.sub("", r.stdout + r.stderr)
            problem = None
            if r.returncode != exp.get("exit_code", 0):
                problem = f"exit code {r.returncode}"
            elif "Traceback" in out or "Error:" in r.stderr:
                problem = "traceback / error in output"
            elif exp.get("json"):
                try:
                    body = json.loads(r.stdout)
                except json.JSONDecodeError:
                    problem = "stdout is not a single JSON object"
                else:
                    if body.get("ok") is not True:
                        problem = f"ok is not true: {body.get('error')}"
                    elif exp.get("status") and body.get("status") != exp["status"]:
                        problem = f"status {body.get('status')!r}, expected {exp['status']!r}"
            for needle in exp.get("lacks", []):
                if problem is None and needle in out:
                    problem = f"declined, but output has {needle!r}"
            for needle in exp.get("contains", []):
                if problem is None and needle not in out:
                    problem = f"output lacks {needle!r}"
            mark = "✓" if problem is None else "✗"
            print(f"  {mark} {name}" + (f"  —  {problem}" if problem else ""))
            if problem:
                failures.append(f"{name}: mcd {' '.join(args)}\n{problem}\n{out[-2000:]}")
        if not (Path(skills) / "mcd-terminal" / "SKILL.md").exists():
            failures.append("skill install did not write SKILL.md")
    print(f"\n{len(cases) - len(failures)}/{len(cases)} passed")
    for f in failures:
        print("\n----- FAILED: " + f)
    return 1 if failures else 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sys.exit(run(sys.argv[1:]))
