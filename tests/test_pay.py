"""The QR code we draw must be the one McDonald's own pay page shows (jumpToApp), not the pay page itself."""
from mcd_terminal.pay import app_url, order_id_of, scan_url, terminal_qr

# captured from the live m.mcd.cn/mcp/scanToPay page (its QR value and the app link on /mcp/jumpToApp)
PAY = "https://m.mcd.cn/mcp/scanToPay?orderId=1030991670000661753499842867"
JUMP = "https://m.mcd.cn/mcp/jumpToApp?orderId=1030991670000661753499842867"
APP = ("mcdapp://page?iosPageName=MCDOrderDetailViewController&androidPageName=ComponentOrder&androidPageAction=order_detail"
       "&harmonyPageName=OrderDetailPage&parameters=%7B%22orderId%22%3A%221030991670000661753499842867%22%2C"
       "%22openCashierDesk%22%3A%221%22%7D")


def test_scan_url_is_the_inner_qr_of_the_pay_page():
    assert scan_url(PAY) == JUMP
    assert scan_url(PAY.replace("?", "/?")) == JUMP
    assert order_id_of(PAY) == "1030991670000661753499842867"


def test_app_link_matches_the_live_jump_page():
    assert app_url(PAY) == APP


def test_unknown_links_pass_through():
    assert scan_url("https://example.com/scanToPay?orderId=1") == "https://example.com/scanToPay?orderId=1"
    assert app_url("https://example.com/pay") is None and scan_url(None) is None


def test_terminal_qr_is_half_block_rows():
    rows = terminal_qr(JUMP)
    assert rows and len({len(r) for r in rows}) == 1 and set("".join(rows)) <= set(" ▀▄█")
