"""The combined image's token proxy, against an in-process stand-in for WanGP."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("auth_proxy", ROOT / "combined/auth_proxy.py")
assert spec and spec.loader
auth_proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auth_proxy)

TOKEN = "s3cret-token"


class Upstream:
    """Records what reached WanGP and answers like its routes do."""

    def __init__(self) -> None:
        self.requests: list[dict] = []

        async def echo(request: Request):
            body = await request.body()
            self.requests.append(
                {
                    "method": request.method,
                    "path": request.url.path,
                    "query": request.url.query,
                    "headers": dict(request.headers),
                    "body": body,
                }
            )
            if request.url.path == "/mcp/stream":
                async def events():
                    yield b"event: message\ndata: {\"id\": 1}\n\n"
                    yield b"event: message\ndata: {\"id\": 2}\n\n"

                return StreamingResponse(events(), media_type="text/event-stream")
            return JSONResponse(
                {"ok": True}, status_code=201, headers={"Mcp-Session-Id": "abc"}
            )

        self.app = Starlette(routes=[Route("/{path:path}", echo, methods=["GET", "POST", "PUT", "DELETE"])])


def run(coro):
    return asyncio.run(coro)


async def call(upstream: Upstream, method: str, path: str, **kwargs) -> httpx.Response:
    upstream_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=upstream.app), base_url="http://127.0.0.1:7867"
    )
    app = auth_proxy.create_app(TOKEN, "http://127.0.0.1:7867", client=upstream_client)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://gpu-box:7866"
    ) as client:
        return await client.request(method, path, **kwargs)


@pytest.mark.parametrize("header", [None, "Bearer wrong", f"Basic {TOKEN}", f"Bearer {TOKEN}x"])
def test_refuses_a_missing_or_wrong_token(header: str | None) -> None:
    upstream = Upstream()
    headers = {"Authorization": header} if header else {}
    response = run(call(upstream, "POST", "/mcp", headers=headers, content=b"{}"))
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert upstream.requests == []


def test_forwards_an_authorized_request_without_the_token() -> None:
    upstream = Upstream()
    response = run(
        call(
            upstream,
            "PUT",
            "/wangp_api/files/upload/tok?x=1",
            headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/octet-stream"},
            content=b"\x93NUMPY",
        )
    )
    assert response.status_code == 201
    assert response.json() == {"ok": True}
    assert response.headers["mcp-session-id"] == "abc"
    [seen] = upstream.requests
    assert seen["method"] == "PUT"
    assert seen["path"] == "/wangp_api/files/upload/tok"
    assert seen["query"] == "x=1"
    assert seen["body"] == b"\x93NUMPY"
    assert "authorization" not in seen["headers"]
    # WanGP's MCP server checks Host against its loopback bind.
    assert seen["headers"]["host"] == "127.0.0.1:7867"


def test_streams_the_mcp_event_stream() -> None:
    upstream = Upstream()
    response = run(call(upstream, "POST", "/mcp/stream", headers={"Authorization": f"Bearer {TOKEN}"}))
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text.count("event: message") == 2


def test_answers_502_while_wangp_is_down() -> None:
    async def down() -> httpx.Response:
        client = httpx.AsyncClient(base_url="http://127.0.0.1:9")
        app = auth_proxy.create_app(TOKEN, "http://127.0.0.1:9", client=client)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://x") as outer:
            return await outer.get("/mcp", headers={"Authorization": f"Bearer {TOKEN}"})

    assert run(down()).status_code == 502


def test_needs_a_token() -> None:
    with pytest.raises(ValueError):
        auth_proxy.create_app("", "http://127.0.0.1:7867")
