"""`mcd web`: the local server, its security rules, and the page it serves."""
import re

from mcd_terminal import web


def test_self_test_passes_in_demo(monkeypatch, tmp_path):
    monkeypatch.setenv("MCD_HOME", str(tmp_path))
    results = web.self_test(demo=True)
    assert [n for n, ok in results if not ok] == []


def test_only_allowed_commands_run(monkeypatch, tmp_path):
    monkeypatch.setenv("MCD_HOME", str(tmp_path))
    for bad in (["login", "--token", "x"], ["logout"], ["skill", "install"], [], ["order", "--help"]):
        assert web.run_command(bad, demo=True)["ok"] is False
    assert web.run_command(["today"], demo=True)["ok"] is True


def test_qr_and_images_only_for_mcdonalds_hosts():
    assert web.qr_svg("https://m.mcd.cn/mcp/scanToPay?orderId=1").startswith("<svg")
    for bad in ("http://m.mcd.cn/x", "https://evil.com/?m.mcd.cn", "https://mcd.cn.evil.com/x", "javascript:alert(1)"):
        assert web.qr_svg(bad) is None
    assert web.img_allowed("https://menu-img.mcd.cn/pcm/prod/menu/a.png")
    assert web.img_allowed("https://img.mcd.cn/ecs/a.png")
    assert web.img_allowed("https://mcd-portal-prod-cos1-1300270282.cos.ap-shanghai.myqcloud.com/a.jpg?sign=1")
    for bad in ("https://evil.myqcloud.com/a.png", "http://img.mcd.cn/a.png", "https://example.com/a.png",
                "https://img.mcd.cn.evil.com/a.png", "file:///etc/passwd"):
        assert not web.img_allowed(bad)


def test_page_escapes_server_text_and_never_embeds_a_token():
    html = web.page_html()
    assert "__MCD_SECRET__" in html and "MCD_MCP_TOKEN" not in html
    # every place that interpolates data into HTML goes through esc() or a number formatter
    js = html.split("<script>")[1]
    raw = re.findall(r"\$\{(?:x|c|l|o|i|p|d)\.(?:name|title|item|coupon|store|status|intro|detail|tags|message)\}", js)
    assert raw == []


def test_style_and_script_stay_separate():
    html = web.page_html()
    css = html.split("<style>")[1].split("</style>")[0]
    js = html.split("<script>")[1].split("</script>")[0]
    assert "function " not in css and "=>" not in css
    import re as _re
    assert not _re.search(r"^\.[a-z][\w-]* \{ [a-z-]+:", js, _re.M)   # no CSS rules pasted into the script
