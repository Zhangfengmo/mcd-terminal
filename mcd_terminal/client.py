"""Minimal MCP Streamable HTTP client for the McDonald's China MCP Server.

We talk JSON-RPC over HTTP directly instead of depending on a specific MCP SDK
major version: the server only speaks protocol 2025-06-18 and earlier, and
pinning that here keeps the client stable no matter which SDK users have.
"""
from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx

from . import __version__

DEFAULT_URL = "https://mcp.mcd.cn"
PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "mcd-terminal", "version": __version__}


class McdError(Exception):
    """A user-facing error with a readable (Chinese) message."""


class McdClient:
    """Calls tools on the McDonald's MCP server.

    `call(tool, args)` returns the tool's payload: the parsed JSON body when the
    tool answers with JSON (its `data` field if present), otherwise the raw text
    (several tools answer with Markdown).
    """

    def __init__(
        self,
        token: str | None = None,
        url: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        from .prefs import load_token

        self.token = token or os.environ.get("MCD_MCP_TOKEN") or load_token()
        if not self.token:
            raise McdError(
                "还没有登录。运行 mcd login 粘贴你的 MCP Token 就好（在 https://open.mcd.cn/mcp 申请），"
                "或者先加 --demo 用演示数据逛逛。"
            )
        self.url = url or os.environ.get("MCD_MCP_URL", DEFAULT_URL)
        self._http = httpx.Client(timeout=timeout, transport=transport)
        self._session_id: str | None = None
        self._next_id = 1
        self._initialized = False
        self._init_mu = threading.Lock()
        self._mu = threading.Lock()   # calls may run in parallel (see call_many); ids and the handshake are shared

    # ---- low level -------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        h = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._initialized:
            h["MCP-Protocol-Version"] = PROTOCOL_VERSION
        if self._session_id:
            h["Mcp-Session-Id"] = self._session_id
        return h

    def _post(self, payload: dict[str, Any]) -> httpx.Response:
        try:
            resp = self._http.post(self.url, json=payload, headers=self._headers())
        except httpx.HTTPError as e:
            raise McdError(f"连不上麦当劳 MCP 服务（{e}），请检查网络或代理后再试") from e
        if resp.status_code == 401:
            raise McdError("MCP Token 无效、已过期或未提供（401）。请检查 MCD_MCP_TOKEN。")
        if resp.status_code == 429:
            raise McdError("请求太频繁被限流了（429，每分钟最多 600 次），稍后再试。")
        if resp.status_code >= 400:
            raise McdError(f"MCP 服务返回 HTTP {resp.status_code}：{resp.text[:200]}")
        sid = resp.headers.get("mcp-session-id")
        if sid:
            self._session_id = sid
        return resp

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        with self._mu:
            req_id = self._next_id
            self._next_id += 1
        resp = self._post({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        msg = _extract_response(resp, req_id)
        if "error" in msg:
            err = msg["error"]
            raise McdError(f"MCP 错误 {err.get('code')}：{err.get('message')}")
        return msg.get("result", {})

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        with self._init_mu:
            if self._initialized:
                return
            self._request(
                "initialize",
                {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": CLIENT_INFO},
            )
            self._initialized = True
            self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    # ---- public ----------------------------------------------------------
    def list_tools(self) -> list[str]:
        self._ensure_initialized()
        return [t["name"] for t in self._request("tools/list", {}).get("tools", [])]

    def call(self, tool: str, args: dict[str, Any] | None = None) -> Any:
        self._ensure_initialized()
        result = self._request("tools/call", {"name": tool, "arguments": args or {}})
        text = "\n".join(
            c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"
        )
        if result.get("isError"):
            raise McdError(f"工具 {tool} 调用失败：{text[:300]}")
        return parse_payload(text, tool)

    def close(self) -> None:
        if self._session_id:
            try:
                self._http.delete(self.url, headers=self._headers())
            except httpx.HTTPError:
                pass
        self._http.close()


def parse_payload(text: str, tool: str = "") -> Any:
    """Turn a tool's text result into data.

    The live server wraps JSON results in guidance text written for LLMs ("Response
    Structure", display rules…) and puts the JSON envelope {success, code, message, data}
    somewhere inside it, sometimes glued to the end of a table row. So we look for the
    envelope anywhere in the text. Tools that answer in pure Markdown come back as text.
    """
    if not isinstance(text, str):
        return text
    body = _find_envelope(text)
    if body is None:
        stripped = text.strip()
        if stripped[:1] in "[{":
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                pass
        return text
    if body.get("success") is False:
        msg = body.get("message") or f"错误码 {body.get('code')}"
        raise McdError(str(msg))
    return body.get("data")


def _find_envelope(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    start = 0
    while True:
        i = text.find('{"success"', start)
        if i < 0:
            i = text.find('{ "success"', start)
        if i < 0:
            return None
        try:
            obj, _ = decoder.raw_decode(text, i)
        except json.JSONDecodeError:
            start = i + 1
            continue
        if isinstance(obj, dict) and "success" in obj:
            return obj
        start = i + 1


def _extract_response(resp: httpx.Response, req_id: int) -> dict[str, Any]:
    """The server may answer with plain JSON or a one-shot SSE stream."""
    ctype = resp.headers.get("content-type", "")
    if "text/event-stream" in ctype:
        for line in resp.text.splitlines():
            if not line.startswith("data:"):
                continue
            try:
                msg = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
            if isinstance(msg, dict) and msg.get("id") == req_id:
                return msg
        raise McdError("MCP 服务的 SSE 响应里没有找到对应的结果。")
    try:
        msg = resp.json()
    except json.JSONDecodeError as e:
        raise McdError(f"无法解析 MCP 响应：{resp.text[:200]}") from e
    if isinstance(msg, list):  # batched
        msg = next((m for m in msg if m.get("id") == req_id), {})
    return msg


def call_many(client: Any, tool: str, args_list: list[dict[str, Any]], workers: int = 6) -> list[Any]:
    """Call one tool for many arguments in parallel (e.g. product details for a whole listing).

    Returns results in the same order; a failed call gives its McdError instead of raising, so one bad
    item never sinks the batch. Stays well under the server's 600 calls/minute limit.
    """
    def one(a: dict[str, Any]) -> Any:
        try:
            return client.call(tool, a)
        except McdError as e:
            return e
    if len(args_list) <= 1:
        return [one(a) for a in args_list]
    with ThreadPoolExecutor(max_workers=min(workers, len(args_list))) as pool:
        return list(pool.map(one, args_list))
