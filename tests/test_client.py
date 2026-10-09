import json
import socket
import threading
import time

import httpx
import pytest

from mcd_terminal.client import PROTOCOL_VERSION, McdClient, McdError, parse_payload


def envelope(data):
    return json.dumps({"success": True, "code": 200, "message": "请求成功", "data": data}, ensure_ascii=False)


class FakeServer:
    """Records requests and answers like a Streamable HTTP MCP server."""

    def __init__(self, tool_text=envelope({"availablePoint": "100"}), sse=False, status=200, is_error=False):
        self.requests = []
        self.tool_text, self.sse, self.status, self.is_error = tool_text, sse, status, is_error

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, text="nope")
        if request.method == "DELETE":
            return httpx.Response(200)
        body = json.loads(request.content)
        if "id" not in body:  # notification
            return httpx.Response(202)
        if body["method"] == "initialize":
            result = {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "serverInfo": {"name": "fake", "version": "1"}}
        elif body["method"] == "tools/list":
            result = {"tools": [{"name": "query-my-account", "inputSchema": {"type": "object"}}]}
        else:
            result = {"content": [{"type": "text", "text": self.tool_text}], "isError": self.is_error}
        msg = {"jsonrpc": "2.0", "id": body["id"], "result": result}
        headers = {"mcp-session-id": "sess-1"}
        if self.sse:
            text = "event: message\ndata: " + json.dumps(msg, ensure_ascii=False) + "\n\n"
            return httpx.Response(200, text=text, headers={**headers, "content-type": "text/event-stream"})
        return httpx.Response(200, json=msg, headers=headers)


def make(server):
    return McdClient(token="t0k", url="https://mcp.test", transport=httpx.MockTransport(server))


@pytest.mark.parametrize("sse", [False, True])
def test_handshake_headers_and_payload(sse):
    server = FakeServer(sse=sse)
    c = make(server)
    assert c.call("query-my-account") == {"availablePoint": "100"}
    init, notif, call = server.requests
    assert init.headers["authorization"] == "Bearer t0k"
    assert "text/event-stream" in init.headers["accept"]
    assert json.loads(init.content)["params"]["protocolVersion"] == PROTOCOL_VERSION
    assert json.loads(notif.content)["method"] == "notifications/initialized"
    assert call.headers["mcp-session-id"] == "sess-1"
    assert call.headers["mcp-protocol-version"] == PROTOCOL_VERSION
    c.close()
    assert server.requests[-1].method == "DELETE"


def test_markdown_tools_return_text():
    md = "# 您的优惠券列表\n\n共 0 张可用优惠券"
    assert make(FakeServer(tool_text=md)).call("query-my-coupons") == md


@pytest.mark.parametrize("status,needle", [(401, "401"), (429, "429"), (500, "500")])
def test_http_errors_are_readable(status, needle):
    with pytest.raises(McdError, match=needle):
        make(FakeServer(status=status)).call("query-my-account")


def test_tool_error_and_business_failure():
    with pytest.raises(McdError, match="调用失败"):
        make(FakeServer(is_error=True, tool_text="boom")).call("x")
    with pytest.raises(McdError, match="积分不足"):
        parse_payload(json.dumps({"success": False, "message": "积分不足"}), "mall-create-order")


def test_missing_token(monkeypatch, tmp_path):
    monkeypatch.delenv("MCD_MCP_TOKEN", raising=False)
    monkeypatch.setenv("MCD_HOME", str(tmp_path))
    with pytest.raises(McdError, match="mcd login"):
        McdClient()


def test_token_file_is_private_and_env_wins(monkeypatch, tmp_path):
    import os
    import stat
    from mcd_terminal.prefs import clear_token, save_token
    monkeypatch.delenv("MCD_MCP_TOKEN", raising=False)
    monkeypatch.setenv("MCD_HOME", str(tmp_path))
    p = save_token(" from-file \n")
    if os.name != "nt":
        assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert McdClient().token == "from-file"
    monkeypatch.setenv("MCD_MCP_TOKEN", "from-env")
    assert McdClient().token == "from-env"
    assert clear_token() and not p.exists()


# ---------------------------------------------------------------- interop
def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_interop_with_official_mcp_sdk_server():
    """Our hand-rolled client must work against the reference SDK implementation."""
    mcpserver = pytest.importorskip("mcp.server.mcpserver")
    uvicorn = pytest.importorskip("uvicorn")

    server = mcpserver.MCPServer("fake-mcd")

    def account() -> str:
        return envelope({"availablePoint": "3260", "nextMouthExpirePoint": "1480"})

    def detail(spuId: int) -> str:
        return envelope({"skuList": [{"skuId": spuId + 1, "points": "500", "extTradePrice": "17"}]})

    server.add_tool(account, name="query-my-account")
    server.add_tool(detail, name="mall-product-detail")

    port = _free_port()
    cfg = uvicorn.Config(server.streamable_http_app(), host="127.0.0.1", port=port, log_level="error")
    uv = uvicorn.Server(cfg)
    t = threading.Thread(target=uv.run, daemon=True)
    t.start()
    for _ in range(100):
        if uv.started:
            break
        time.sleep(0.05)

    try:
        c = McdClient(token="t", url=f"http://127.0.0.1:{port}/mcp")
        assert set(c.list_tools()) >= {"query-my-account", "mall-product-detail"}
        assert c.call("query-my-account")["nextMouthExpirePoint"] == "1480"
        assert c.call("mall-product-detail", {"spuId": 542})["skuList"][0]["skuId"] == 543
        c.close()
    finally:
        uv.should_exit = True
        t.join(timeout=5)
