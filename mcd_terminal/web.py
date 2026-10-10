"""`mcd web`: the same engine, shown as a page in your browser.

A tiny local server (stdlib only, bound to 127.0.0.1) serves one self-contained page and a
single JSON endpoint that runs the CLI's own commands in --json mode. So the web page uses
exactly the agent interface: same optimiser, same live quote, and the same rule that nothing
irreversible happens without a confirmation (the page adds --yes only after you click).

Safety:
- listens on 127.0.0.1 only, on a random port;
- every API call must carry a per-run secret (it is in the URL that `mcd web` opens), and the
  Host header must be local, so other sites in your browser can't drive it (CSRF / DNS rebinding);
- only a fixed list of commands can be run; the token never reaches the page.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import secrets
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from typing import Any
from urllib.parse import parse_qs, urlparse

# Commands the page may run (first word). Login, logout and skill install stay in the terminal.
ALLOWED = {
    "today", "portfolio", "market", "spend", "buy", "claim", "order", "menu", "nutrition", "stores",
    "address", "config", "track", "orders", "cancel", "history", "calendar", "prizes", "events", "party", "remind",
    "survey", "draw", "stats",
}
# A QR code is only drawn for payment / order links on McDonald's own domains.
QR_HOSTS = (".mcd.cn", ".mcdonalds.com.cn")
# Pictures come from these hosts (menu, mall, coupons, campaigns). The page loads them through
# this server, so they work even where the image CDN checks the Referer, and nothing else can be fetched.
IMG_HOSTS = (".mcd.cn", ".mcdonalds.com.cn")
IMG_COS = ".myqcloud.com"   # McDonald's coupon images live in a Tencent COS bucket named mcd-portal-…
IMG_MAX = 5 * 1024 * 1024
_img_cache: dict[str, tuple[str, bytes]] = {}

_lock = threading.Lock()  # the CLI keeps module-level state; run one command at a time


def run_command(args: list[str], demo: bool) -> dict[str, Any]:
    """Run `mcd --json [--demo] <args>` in-process and return its JSON object."""
    if not args or args[0] not in ALLOWED:
        return {"ok": False, "error": f"不支持的命令：{args[0] if args else '（空）'}"}
    if any(a in ("--help", "-h") for a in args):
        return {"ok": False, "error": "不支持 --help"}
    from .cli import app

    full = ["--json", *(["--demo"] if demo else []), *args]
    out = io.StringIO()
    with _lock:
        saved_argv = sys.argv
        sys.argv = ["mcd", *full]  # used to build follow-up commands (confirm_with, retry_with)
        try:
            with contextlib.redirect_stdout(out):
                try:
                    app(full, standalone_mode=False, prog_name="mcd")
                except SystemExit:
                    pass
                except Exception as e:  # never take the server down
                    return {"ok": False, "error": f"出错了：{e}"}
        finally:
            sys.argv = saved_argv
    for line in reversed(out.getvalue().strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                break
    return {"ok": False, "error": "没有拿到结果"}


def qr_svg(data: str) -> str | None:
    host = urlparse(data).hostname or ""
    if not data.startswith("https://") or not any(host == h[1:] or host.endswith(h) for h in QR_HOSTS):
        return None
    import segno

    buf = io.BytesIO()
    segno.make(data, error="m").save(buf, kind="svg", scale=5, border=2, dark="#2b1d16", light="#ffffff",
                                     xmldecl=False, svgns=True)
    return buf.getvalue().decode("utf-8")


def img_allowed(url: str) -> bool:
    u = urlparse(url)
    host = u.hostname or ""
    if u.scheme != "https":
        return False
    return any(host.endswith(h) for h in IMG_HOSTS) or (host.endswith(IMG_COS) and host.startswith("mcd-"))


def fetch_image(url: str) -> tuple[str, bytes] | None:
    """Download a picture from an allowed McDonald's host (cached in memory)."""
    if not img_allowed(url):
        return None
    if url in _img_cache:
        return _img_cache[url]
    import httpx

    try:
        with httpx.stream("GET", url, timeout=10, follow_redirects=False,
                          headers={"User-Agent": "Mozilla/5.0 mcd-terminal"}) as r:
            ctype = r.headers.get("content-type", "")
            if r.status_code != 200 or not ctype.startswith("image/"):
                return None
            data = b""
            for chunk in r.iter_bytes():
                data += chunk
                if len(data) > IMG_MAX:
                    return None
    except httpx.HTTPError:
        return None
    if len(_img_cache) > 300:
        _img_cache.clear()
    _img_cache[url] = (ctype, data)
    return ctype, data


def page_html() -> str:
    return resources.files("mcd_terminal").joinpath("web/index.html").read_text(encoding="utf-8")


def make_handler(secret: str, demo: bool) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "mcd-web"

        def log_message(self, *_: Any) -> None:  # keep the terminal quiet
            pass

        # ---------------------------------------------------------- helpers
        def _local_host(self) -> bool:
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
            return host in ("127.0.0.1", "localhost", "::1")

        def _send(self, status: int, body: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, obj: Any) -> None:
            self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def _authorized(self) -> bool:
            if not self._local_host():
                return False
            given = self.headers.get("X-Mcd-Secret") or ""
            return secrets.compare_digest(given, secret)

        # ---------------------------------------------------------- routes
        def do_GET(self) -> None:  # noqa: N802
            if not self._local_host():
                self._send(HTTPStatus.FORBIDDEN, b"forbidden", "text/plain")
                return
            url = urlparse(self.path)
            if url.path in ("/", "/index.html"):
                q = parse_qs(url.query)
                if not secrets.compare_digest((q.get("s") or [""])[0], secret):
                    self._send(HTTPStatus.FORBIDDEN, "请用 mcd web 打开的链接访问".encode("utf-8"),
                               "text/plain; charset=utf-8")
                    return
                html = page_html().replace("__MCD_SECRET__", secret).replace("__MCD_DEMO__", "true" if demo else "false")
                self._send(HTTPStatus.OK, html.encode("utf-8"), "text/html; charset=utf-8")
            elif url.path == "/api/qr":
                if not self._authorized():
                    self._send(HTTPStatus.FORBIDDEN, b"forbidden", "text/plain")
                    return
                svg = qr_svg((parse_qs(url.query).get("data") or [""])[0])
                if svg is None:
                    self._send(HTTPStatus.BAD_REQUEST, b"unsupported link", "text/plain")
                else:
                    self._send(HTTPStatus.OK, svg.encode("utf-8"), "image/svg+xml")
            elif url.path == "/api/img":
                q = parse_qs(url.query)
                if not secrets.compare_digest((q.get("s") or [""])[0], secret):
                    self._send(HTTPStatus.FORBIDDEN, b"forbidden", "text/plain")
                    return
                got = fetch_image((q.get("u") or [""])[0])
                if got is None:
                    self._send(HTTPStatus.NOT_FOUND, b"no image", "text/plain")
                else:
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", got[0])
                    self.send_header("Content-Length", str(len(got[1])))
                    self.send_header("Cache-Control", "private, max-age=86400")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.end_headers()
                    self.wfile.write(got[1])
            elif url.path == "/api/ics":
                # calendar files that `mcd remind` wrote; only that folder, only .ics names
                q = parse_qs(url.query)
                if not secrets.compare_digest((q.get("s") or [""])[0], secret):
                    self._send(HTTPStatus.FORBIDDEN, b"forbidden", "text/plain")
                    return
                from .prefs import home
                name = os.path.basename((q.get("f") or [""])[0])
                path = home() / "reminders" / name
                if not name.endswith(".ics") or not path.is_file():
                    self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
                    return
                body = path.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/calendar; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="{name}"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif url.path == "/favicon.ico":
                self._send(HTTPStatus.NO_CONTENT, b"", "image/x-icon")
            else:
                self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")

        def do_POST(self) -> None:  # noqa: N802
            if urlparse(self.path).path != "/api/run":
                self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
                return
            if not self._authorized():
                self._json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "forbidden"})
                return
            if "application/json" not in (self.headers.get("Content-Type") or ""):
                self._json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"ok": False, "error": "需要 JSON"})
                return
            try:
                length = min(int(self.headers.get("Content-Length") or 0), 64 * 1024)
                body = json.loads(self.rfile.read(length) or b"{}")
                args = [str(a) for a in body.get("args") or []]
            except (ValueError, AttributeError):
                self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "请求格式不对"})
                return
            self._json(HTTPStatus.OK, run_command(args, demo))

    return Handler


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request: Any, client_address: Any) -> None:
        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            return  # the browser stopped waiting (e.g. switched page while an image loaded)
        super().handle_error(request, client_address)


def serve(demo: bool = False, port: int = 0, open_browser: bool = True) -> tuple[ThreadingHTTPServer, str]:
    """Start the server; returns it and the URL to open (contains the per-run secret)."""
    secret = secrets.token_urlsafe(18)
    if demo:
        os.environ["MCD_WEB_DEMO"] = "1"
    httpd = _Server(("127.0.0.1", port), make_handler(secret, demo))
    url = f"http://127.0.0.1:{httpd.server_address[1]}/?s={secret}"
    if open_browser:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    return httpd, url


def self_test(demo: bool) -> list[tuple[str, bool]]:
    """Start the server, hit every route once, stop it. Used by `mcd web --self-test` and the e2e test."""
    import urllib.error
    import urllib.request

    had_flag = "MCD_WEB_DEMO" in os.environ
    httpd, url = serve(demo=demo, open_browser=False)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = url.split("/?")[0]
    secret = url.split("s=", 1)[1]
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never via a proxy

    def get(path: str, headers: dict | None = None) -> tuple[int, bytes]:
        try:
            with opener.open(urllib.request.Request(base + path, headers=headers or {}), timeout=30) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, b""

    def post(args: list[str], key: str = secret) -> dict:
        req = urllib.request.Request(base + "/api/run", data=json.dumps({"args": args}).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "X-Mcd-Secret": key})
        try:
            with opener.open(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            return {"ok": False, "status": e.code}

    results: list[tuple[str, bool]] = []
    try:
        st, body = get("/?s=" + secret)
        results.append(("页面", st == 200 and b"__MCD_SECRET__" not in body and secret.encode() in body))
        results.append(("没有密钥打不开页面", get("/")[0] == 403))
        results.append(("没有密钥调不了接口", post(["today"], key="wrong").get("status") == 403))
        results.append(("不允许的命令被拒绝", post(["login", "--token", "x"]).get("ok") is False))
        for args in (["today"], ["calendar"], ["prizes"], ["portfolio"], ["menu", "--limit", "500"], ["orders"]):
            results.append((" ".join(args[:1]), post(args).get("ok") is True))
        plan = post(["order", "code:920100", "code:920300x2", "-n"])
        results.append(("按编码算最省付法", plan.get("status") == "planned"))
        results.append(("需要确认才下单", post(["order", "code:920100"]).get("status") == "needs_confirmation"))
        st, svg = get("/api/qr?data=" + "https%3A%2F%2Fm.mcd.cn%2Fmcp%2FscanToPay%3ForderId%3D1",
                      {"X-Mcd-Secret": secret})
        results.append(("付款二维码", st == 200 and svg.lstrip().startswith(b"<svg")))
        results.append(("只给麦当劳链接生成二维码", get("/api/qr?data=https%3A%2F%2Fexample.com", {"X-Mcd-Secret": secret})[0] == 400))
        results.append(("只代理麦当劳的图片", get(f"/api/img?s={secret}&u=https%3A%2F%2Fexample.com%2Fa.png")[0] == 404))
    finally:
        httpd.shutdown()
        httpd.server_close()
        if not had_flag:
            os.environ.pop("MCD_WEB_DEMO", None)
    return results
