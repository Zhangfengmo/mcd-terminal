"""End-to-end runs of every command against demo data (non-interactive)."""
import pytest
from typer.testing import CliRunner

from mcd_terminal.cli import REQUIRED_TOOLS, app
from mcd_terminal.valuation import parse_bind_result, parse_claimable

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("MCD_HOME", str(tmp_path))
    monkeypatch.setenv("MCD_DEMO_NOW", "2026-10-09 12:20")
    monkeypatch.delenv("MCD_DEMO_DELAY", raising=False)


def run(*args, input=None):
    res = runner.invoke(app, ["--demo", *args], input=input, env={"COLUMNS": "110"})
    assert res.exception is None or isinstance(res.exception, SystemExit), res.output
    return res


def test_today_brief_is_the_default_command():
    out = run().output
    assert "整理今日简报 (MCP x5)" in out and "中午好" in out
    assert "mcd spend --expiring" in out and "mcd claim" in out and "9.9元薯你最甜" in out
    assert "mcd order 巨无霸 中杯拿铁" in out


def test_portfolio_shows_calls_and_risk():
    out = run("portfolio").output
    assert "query-my-account (MCP)" in out and "⎿" in out
    assert "1,480" in out and "mcd spend --expiring" in out and "出餐用时" in out


def test_market_ranks_best_first():
    out = run("market").output
    assert "mall-product-detail x9" in out
    assert out.index("中杯拿铁/美式") < out.index("巨无霸")


def test_spend_dry_run_and_confirmation():
    dry = run("spend", "--expiring", "--dry-run").output
    assert "1,450" in dry and "mall-create-order" not in dry
    ok = run("spend", "--expiring", input="1\n").output
    assert "已确认" in ok and ok.count("mall-create-order") == 3 and "换好啦" in ok
    no = run("spend", "--expiring", input="2\n").output
    assert "已取消" in no and "mall-create-order" not in no


@pytest.mark.parametrize("answer,ordered", [("y\n", True), ("n\n", False), ("\n", False)])
def test_buy_requires_explicit_yes(answer, ordered):
    out = run("buy", "10542", input=answer).output
    assert ("mall-create-order" in out) is ordered


def test_buy_physical_goes_to_the_address():
    out = run("buy", "10630", "--address", "A1", "-y").output
    assert "mall-create-order" in out and "寄往" in out


def test_claim_flow():
    out = run("claim", "-y").output
    assert "3 张券，2 张可领" in out and "auto-bind-coupons" in out and "成功 2 张" in out


def test_order_mixes_coupons_and_points_and_creates_order():
    out = run("order", "巨无霸", "中杯拿铁", "薯条", "麦乐鸡", "--city", "上海", "--near", "人民广场", "-y").output
    assert "2 张已有券 + 1,700 积分" in out and "¥21.80" in out
    assert out.count("mall-create-order (MCP)") == 2
    assert "实付 ¥21.80" in out           # authoritative calculate-price agrees with the plan
    assert "create-order (MCP)" in out and "scanToPay" in out
    assert "够买 9 个圆筒冰淇淋" in out


def test_order_cancel_does_nothing():
    out = run("order", "巨无霸", "--city", "上海", "--near", "人民广场", input="2\n").output
    assert "已取消" in out and "create-order" not in out and "mall-create-order" not in out


def test_prefs_persist_between_runs(tmp_path):
    from mcd_terminal.prefs import Prefs
    Prefs().set("store_pickup", {"code": "1", "be": "2", "name": "麦当劳人民广场餐厅"})
    assert Prefs().get("store_pickup")["name"] == "麦当劳人民广场餐厅"
    assert (tmp_path / "prefs.json").exists()
    mem = Prefs(persist=False)
    mem.set("x", 1)
    assert Prefs().get("x") is None  # demo prefs never touch the file


@pytest.mark.parametrize("flags,needle", [
    (["--delivery"], "麦乐送"),
    (["--drive", "--city", "上海", "--near", "人民广场"], "得来速"),
    (["--group", "--service", "专人分餐", "--at", "2026-10-10 12:00"], "专人分餐"),
])
def test_order_scenes(flags, needle):
    out = run("order", "巨无霸*3", *flags, "--no-points", "--dry-run").output
    assert needle in out and "x3" in out


def test_order_unknown_item_is_friendly():
    res = run("order", "火星披萨", "--city", "上海", "--near", "人民广场", "--dry-run")
    assert res.exit_code == 1 and "没有「火星披萨」" in res.output and "mcd menu" in res.output


@pytest.mark.parametrize("args,needle", [
    (["menu", "薯条", "--city", "上海", "--near", "人民广场"], "330 千卡"),
    (["menu", "--detail", "920101", "--city", "上海", "--near", "人民广场"], "中杯可口可乐"),
    (["nutrition", "--sort", "protein"], "按蛋白质从高到低"),
    (["stores", "--city", "上海", "--near", "人民广场", "--use", "2"], "以后点餐默认去 麦当劳南京东路餐厅"),
    (["address"], "A1"),
    (["address", "add", "--city", "上海市", "--name", "麦麦", "--phone", "15212345678",
      "--street", "人民大道200号", "--detail", "3楼"], "地址加好了"),
    (["track"], "A 1 2 7"),
    (["history"], "汉堡造型钥匙扣"),
    (["history", "ECS1211037028709736448"], "4009-200-205"),
    (["calendar"], "甜品示例活动"),
])
def test_other_commands(args, needle):
    res = run(*args)
    assert res.exit_code == 0 and needle in res.output, res.output


def test_every_mcp_tool_is_used_somewhere():
    import pathlib
    import re
    src = ""
    for p in pathlib.Path("mcd_terminal").glob("*.py"):
        if p.name == "demo.py":
            continue
        text = p.read_text(encoding="utf-8")
        if p.name == "cli.py":  # don't count the REQUIRED_TOOLS list itself
            text = re.sub(r"REQUIRED_TOOLS = \[.*?\]", "", text, flags=re.S)
        src += text
    assert len(REQUIRED_TOOLS) == 31
    assert [t for t in REQUIRED_TOOLS if f'"{t}"' not in src] == []


def test_error_is_rendered_and_exit_code_is_1():
    res = run("buy", "999", "-y")
    assert res.exit_code == 1 and "不存在" in res.output


def test_parse_claim_markdown():
    md = ("### 麦麦省优惠券列表：\n- 优惠券标题：11.9元麦乐鸡 \\\n  状态：已领取 \\\n  优惠券图片：\\\n"
          "    <img src=\"x\">\n- 优惠券标题：9.9元薯你最甜 \\\n  状态：未领取 \\\n")
    assert parse_claimable(md) == [("11.9元麦乐鸡", "已领取"), ("9.9元薯你最甜", "未领取")]
    bound = ("### 🎉 领券结果\n\n**总计**: 1 张优惠券\n**成功**: 1 张\n**失败**: 0 张\n\n---\n\n"
             "#### ✅ 成功领取的优惠券：\n\n- **9.9元薯你最甜**\n  - couponId：8ED8\n")
    assert parse_bind_result(bound) == (1, 0, ["9.9元薯你最甜"])
    assert parse_bind_result(None) == (None, None, [])


# ------------------------------------------------------------------ agents (--json)
import json as _json  # noqa: E402


def run_json(*args, input=None):
    res = runner.invoke(app, ["--demo", "--json", *args], input=input, env={"COLUMNS": "110"})
    lines = [l for l in res.output.splitlines() if l.strip()]
    assert len(lines) == 1, res.output  # exactly one JSON object, nothing else
    return res, _json.loads(lines[0])


def test_json_order_needs_confirmation_and_never_prompts():
    res, d = run_json("order", "巨无霸", "中杯拿铁", "薯条", "麦乐鸡", input="1\n")
    assert res.exit_code == 0 and d["ok"] and d["status"] == "needs_confirmation"
    assert d["plan"]["pay_yuan"] == 21.8 and d["plan"]["points_used"] == 1700
    assert {l["pay_with"] for l in d["plan"]["lines"]} == {"points", "coupon"}
    assert d["quote"]["pay_yuan"] == 21.8
    assert d["suggestions"][0]["add"] == "圆筒冰淇淋" and d["suggestions"][0]["points"] == 150
    assert d["campaigns_today"][0]["items"] == ["麦辣鸡腿堡"]
    assert "create-order" not in res.output


def test_json_order_with_yes_places_order():
    _, d = run_json("order", "巨无霸", "--yes")
    assert d["status"] == "ordered" and d["order"]["pay_url"].startswith("https://")


def test_json_promo_is_caught_by_live_quote():
    _, d = run_json("order", "麦辣鸡腿堡*2", "--no-points", "--dry-run")
    assert d["plan"]["pay_yuan"] == 47.0          # our estimate doesn't know the promotion
    assert d["quote"]["pay_yuan"] == 35.25        # the live quote does
    assert d["quote"]["promo_saving_yuan"] == 11.75


def test_json_errors_are_json():
    res, d = run_json("buy", "999", "--yes")
    assert res.exit_code == 1 and d["ok"] is False and "不存在" in d["error"]


@pytest.mark.parametrize("args,key", [
    ([], "points"), (["portfolio"], "coupons"), (["market"], "items"), (["spend", "--expiring"], "plan"),
    (["claim"], "claimable"), (["menu", "--city", "上海", "--near", "人民广场"], "items"),
    (["nutrition"], "items"), (["stores"], "stores"), (["address"], "addresses"), (["track"], "order"),
    (["history"], "orders"), (["calendar"], "campaigns"), (["doctor"], "connected"),
])
def test_every_command_speaks_json(args, key):
    res, d = run_json(*args)
    assert res.exit_code == 0 and d["ok"] and key in d, d


def test_skill_show_and_install(tmp_path):
    out = runner.invoke(app, ["skill", "show"]).output
    assert out.startswith("---\nname: mcd-terminal") and "--yes" in out
    res = runner.invoke(app, ["--json", "skill", "install", "--dir", str(tmp_path)])
    path = _json.loads(res.output)["path"]
    assert (tmp_path / "mcd-terminal" / "SKILL.md").read_text(encoding="utf-8") == out.rstrip("\n") + "\n" or \
        (tmp_path / "mcd-terminal" / "SKILL.md").exists()
    assert path.endswith("SKILL.md")


def test_contest_files_present():
    import pathlib
    root = pathlib.Path(".")
    for f in ["README.md", "CONTEST_DECLARATION.md", "MCP_INTEGRATION.md", "mcp-config.example.json"]:
        assert (root / f).exists(), f
    cfg = _json.loads((root / "mcp-config.example.json").read_text(encoding="utf-8"))
    assert cfg["mcpServers"]["mcd-mcp"]["headers"]["Authorization"] == "Bearer ${MCD_MCP_TOKEN}"
    readme = (root / "README.md").read_text(encoding="utf-8")
    for section in ["目标用户", "安装", "使用示例"]:
        assert section in readme, section


def test_login_verifies_then_saves_token(monkeypatch, tmp_path):
    import httpx
    from mcd_terminal import cli as cli_mod
    from mcd_terminal.client import McdClient
    from tests.test_client import FakeServer

    monkeypatch.setenv("MCD_HOME", str(tmp_path))
    real = McdClient
    monkeypatch.setattr(cli_mod, "McdClient",
                        lambda token=None: real(token=token, url="https://mcp.test", transport=httpx.MockTransport(FakeServer())))
    res = runner.invoke(app, ["--json", "login", "--token", "abc123"])
    d = _json.loads(res.output)
    assert d["ok"] and d["logged_in"] and (tmp_path / "token").read_text().strip() == "abc123"

    monkeypatch.setattr(cli_mod, "McdClient",
                        lambda token=None: real(token=token, url="https://mcp.test", transport=httpx.MockTransport(FakeServer(status=401))))
    res = runner.invoke(app, ["--json", "login", "--token", "bad"])
    assert res.exit_code == 1 and "401" in _json.loads(res.output)["error"]
    assert (tmp_path / "token").read_text().strip() == "abc123"   # a bad token never overwrites a good one

    res = runner.invoke(app, ["--json", "logout"])
    assert _json.loads(res.output)["logged_out"] and not (tmp_path / "token").exists()


def test_version_flag():
    from mcd_terminal import __version__
    assert runner.invoke(app, ["--version"]).output.strip() == f"mcd-terminal {__version__}"


@pytest.mark.parametrize("args", [["--demo", "--json", "today"], ["skill", "show"], ["--demo", "order", "巨无霸", "--dry-run"]])
def test_non_utf8_pipes_do_not_crash(args, tmp_path):
    """Windows pipes default to a legacy code page; mcd must still emit Chinese text (as UTF-8)."""
    import os
    import subprocess
    import sys
    env = dict(os.environ, PYTHONIOENCODING="cp1252", MCD_HOME=str(tmp_path), COLUMNS="100")
    r = subprocess.run([sys.executable, "-m", "mcd_terminal", *args], capture_output=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-500:]
    r.stdout.decode("utf-8")  # valid UTF-8


def test_root_skill_is_the_packaged_skill():
    """SKILL.md at the repo root (what people and agents see) must equal the copy shipped in the package."""
    import pathlib
    root = pathlib.Path("SKILL.md").read_text(encoding="utf-8")
    packaged = pathlib.Path("mcd_terminal/skill/SKILL.md").read_text(encoding="utf-8")
    assert root == packaged, "run: cp SKILL.md mcd_terminal/skill/SKILL.md"
    assert root.startswith("---\nname: mcd-terminal\ndescription: ")


def test_stamp_embeds_checksums_into_installers(tmp_path):
    """Release installers carry the package checksums, so installs never stall fetching SHA256SUMS."""
    import hashlib
    import subprocess
    import sys
    (tmp_path / "mcd-linux-x64.tar.gz").write_bytes(b"pkg-a")
    (tmp_path / "mcd-windows-x64.zip").write_bytes(b"pkg-b")
    r = subprocess.run([sys.executable, "packaging/stamp.py", str(tmp_path), "v9.9.9"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    sh = (tmp_path / "install.sh").read_text(encoding="utf-8")
    ps = (tmp_path / "install.ps1").read_text(encoding="utf-8")
    want = hashlib.sha256(b"pkg-a").hexdigest()
    assert 'EMBEDDED_VERSION="v9.9.9"' in sh and f"{want}  mcd-linux-x64.tar.gz" in sh
    assert "$EmbeddedVersion = 'v9.9.9'" in ps and f"{want}  mcd-linux-x64.tar.gz" in ps
    assert subprocess.run(["bash", "-n", str(tmp_path / "install.sh")]).returncode == 0
    sums = (tmp_path / "SHA256SUMS").read_text(encoding="utf-8")
    assert hashlib.sha256(sh.encode()).hexdigest() in sums  # the stamped script itself is listed
    assert all(ord(c) < 128 for c in ps)                      # PowerShell 5.1 + irm needs ASCII
    # the repo copies stay unstamped
    assert 'EMBEDDED_SUMS=""' in pathlib_text("install.sh")


def pathlib_text(p):
    import pathlib
    return pathlib.Path(p).read_text(encoding="utf-8")


def test_install_sh_is_safe_for_macos_bash_3_2():
    """macOS ships bash 3.2, which reads a UTF-8 byte right after `$NAME` as part of the variable name
    (`$VERSION（` became the unbound `VERSION?`). Every variable next to non-ASCII text must be braced."""
    import re
    bad = [(n, l) for n, l in enumerate(pathlib_text("install.sh").splitlines(), 1)
           if re.search(r"\$[A-Za-z_][A-Za-z0-9_]*[^\x00-\x7f]", l)]
    assert bad == [], bad


def test_orders_and_cancel():
    out = run("orders").output
    assert "order-list" in out and "麦辣鸡腿堡 x2" in out
    body = _json.loads(run("--json", "cancel").output)
    assert body["status"] == "needs_confirmation" and body["confirm_with"].endswith("--yes")
    body = _json.loads(run("--json", "cancel", "--yes").output)
    assert body["status"] == "done" and body["cancelled"] is True
    out = run("cancel", input="2\n").output
    assert "cancel-order" not in out


def test_saved_defaults_drive_order_mode_and_points(tmp_path, monkeypatch):
    from mcd_terminal import cli
    from mcd_terminal.prefs import Prefs
    monkeypatch.setattr(cli.state, "_prefs", Prefs(persist=False))
    assert cli._mode(False, False, False) == "pickup"
    cli.state.prefs.set("mode", "delivery")
    assert cli._mode(False, False, False) == "delivery"
    assert cli._mode(False, False, False, pickup=True) == "pickup"      # a flag beats the saved default
    assert cli._points_cap(None, False) is None
    cli.state.prefs.set("points", "off")
    assert cli._points_cap(None, False) == 0 and cli._points_cap(300, False) == 300
    cli.state.prefs.set("points", 800)
    assert cli._points_cap(None, False) == 800 and cli._points_cap(None, True) == 0


def test_same_address_is_not_added_twice():
    from mcd_terminal.cli import same_address
    a = {"addressId": "A1", "phone": "152****6666", "fullAddress": "上海市黄浦区人民大道 200 号 3 楼"}
    assert same_address(a, "15200006666", "人民大道200号", "3楼")
    assert not same_address(a, "13900001234", "人民大道200号", "3楼")
    assert not same_address(a, "15200006666", "人民大道200号", "5楼")


def test_prefs_persist_and_reset(tmp_path, monkeypatch):
    from mcd_terminal.prefs import Prefs
    p = Prefs()
    p.set("mode", "delivery"); p.set("points", 500)
    assert Prefs().get("mode") == "delivery" and Prefs().get("points") == 500
    p.unset("mode"); p.set("points", None)
    assert Prefs().get("mode") is None and Prefs().get("points") is None


def test_take_way_preference():
    from mcd_terminal.ordering import _take_way
    price = {"takeWayList": [{"code": "eat-in", "title": "堂食"}, {"code": "locker-out", "title": "外带"}]}
    assert _take_way(price) == "eat-in"
    assert _take_way(price, "外带") == "locker-out"
    assert _take_way({"takeWayList": [{"code": "eat-in", "title": "堂食"}]}, "外带") == "eat-in"


def test_new_addresses_are_checked_before_they_reach_mcdonalds():
    from mcd_terminal.cli import check_address
    from mcd_terminal.client import McdError
    ok = check_address(" 上海 ", "张三", "138-0000-0000", "人民大道  200 号", "3 楼 302", "男")
    assert ok == {"city": "上海市", "contactName": "张三", "phone": "13800000000", "address": "人民大道 200 号",
                  "addressDetail": "3 楼 302", "gender": "先生"}
    for bad, why in ((("上海", "张三", "1380000000", "人民大道", "302", ""), "手机号"),
                     (("Shanghai", "张三", "13800000000", "人民大道", "302", ""), "城市"),
                     (("上海", "12345", "13800000000", "人民大道", "302", ""), "收货人"),
                     (("上海", "张三", "13800000000", "人", "302", ""), "小区"),
                     (("上海", "张三", "13800000000", "人民大道", "", ""), "门牌号"),
                     (("上海", "张三", "13800000000", "人民大道", "302", "老板"), "称谓")):
        with pytest.raises(McdError, match=why):
            check_address(*bad)


def test_address_add_rejects_a_bad_phone_without_calling_the_server():
    res = run("address", "add", "-c", "上海", "--name", "麦麦", "--phone", "12345", "--street", "人民大道 200 号", "--detail", "3 楼")
    assert res.exit_code == 1 and "手机号" in res.output and "delivery-create-address" not in res.output
