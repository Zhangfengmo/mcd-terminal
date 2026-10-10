"""付款链接怎么给人用。

create-order 返回的 payH5Url（m.mcd.cn/mcp/scanToPay?orderId=…）是给电脑看的“扫码页”：页面上又是一个二维码。
那个二维码里装的是 m.mcd.cn/mcp/jumpToApp?orderId=…——手机扫它（相机或微信），会打开麦当劳 App
的订单详情并直接弹出收银台。所以我们自己画二维码时直接画 jumpToApp，省掉“扫码再扫码”。

jumpToApp 页面里拉起 App 用的是 mcdapp://page?…&parameters={"orderId":…,"openCashierDesk":"1"}，
在手机上可以直接点这个链接打开 App 付款。
"""
from __future__ import annotations

import json
from urllib.parse import quote, urlsplit, urlunsplit

SCAN_PATH = "/mcp/scanToPay"
JUMP_PATH = "/mcp/jumpToApp"


def _is_mcd(host: str) -> bool:
    return host == "mcd.cn" or host.endswith(".mcd.cn")


def scan_url(pay_url: str | None) -> str | None:
    """手机该扫的链接：scanToPay → jumpToApp（同一个订单号）；认不出来就原样返回。"""
    if not pay_url:
        return None
    u = urlsplit(pay_url)
    if _is_mcd(u.hostname or "") and u.path.rstrip("/") == SCAN_PATH:
        return urlunsplit((u.scheme or "https", u.netloc, JUMP_PATH, u.query, ""))
    return pay_url


def order_id_of(pay_url: str | None) -> str | None:
    if not pay_url:
        return None
    for part in urlsplit(pay_url).query.split("&"):
        k, _, v = part.partition("=")
        if k == "orderId" and v:
            return v
    return None


def app_url(pay_url: str | None) -> str | None:
    """手机上直接打开麦当劳 App 收银台的链接（只对点餐订单的 scanToPay 链接生成）。"""
    if not pay_url or scan_url(pay_url) == pay_url:
        return None
    oid = order_id_of(pay_url)
    if not oid:
        return None
    params = quote(json.dumps({"orderId": oid, "openCashierDesk": "1"}, separators=(",", ":")), safe="")
    return ("mcdapp://page?iosPageName=MCDOrderDetailViewController&androidPageName=ComponentOrder"
            f"&androidPageAction=order_detail&harmonyPageName=OrderDetailPage&parameters={params}")


def terminal_qr(data: str) -> list[str] | None:
    """二维码画成终端里的半格字符（两行像素合成一行字），黑码白底由调用方上色。没有 segno 就返回 None。"""
    try:
        import segno
    except ImportError:
        return None
    rows = [list(r) for r in segno.make(data, error="m").matrix_iter(scale=1, border=2)]
    if len(rows) % 2:
        rows.append([0] * len(rows[0]))
    out = []
    for top, bottom in zip(rows[0::2], rows[1::2]):
        out.append("".join(" " if not a and not b else "▀" if a and not b else "▄" if b and not a else "█"
                           for a, b in zip(top, bottom)))
    return out
