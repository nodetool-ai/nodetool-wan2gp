"""Bearer-token gate in front of WanGP's MCP server.

WanGP's MCP server has no authentication, so the combined image binds it to
the container's loopback and publishes this proxy instead. Every request,
the MCP endpoint and the /wangp_api transfer routes alike, must carry
``Authorization: Bearer <WAN2GP_MCP_TOKEN>``. Bodies stream in both
directions, so uploads and the MCP event stream are not buffered.

It runs in the WanGP interpreter, which has uvicorn, starlette and httpx as
dependencies of the pinned ``mcp`` package. It does not import WanGP.
"""

from __future__ import annotations

import hmac
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response, StreamingResponse
from starlette.routing import Route

# Headers that describe one hop, not the message (RFC 9110 section 7.6.1).
HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
METHODS = ["GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS", "PATCH"]


def create_app(token: str, upstream: str, client: httpx.AsyncClient | None = None) -> Starlette:
    """Return the proxy app. ``upstream`` is WanGP's own origin, such as http://127.0.0.1:7867."""
    if not token:
        raise ValueError("The proxy needs a non-empty token.")
    expected = f"Bearer {token}".encode()
    upstream_host = httpx.URL(upstream).netloc.decode()
    http = client or httpx.AsyncClient(
        base_url=upstream,
        timeout=httpx.Timeout(connect=10.0, read=None, write=None, pool=None),
        follow_redirects=False,
    )

    async def proxy(request: Request) -> Response:
        supplied = request.headers.get("authorization", "").encode()
        if not hmac.compare_digest(supplied, expected):
            return PlainTextResponse(
                "Unauthorized", status_code=401, headers={"WWW-Authenticate": "Bearer"}
            )
        headers = [
            (name, value)
            for name, value in request.headers.items()
            if name.lower() not in HOP_BY_HOP | {"authorization", "host", "content-length"}
        ]
        # WanGP's MCP server checks the Host header against its loopback bind.
        headers.append(("host", upstream_host))
        length = request.headers.get("content-length")
        if length is not None:
            headers.append(("content-length", length))
        body = request.stream() if request.method not in {"GET", "HEAD"} else None
        upstream_request = http.build_request(
            request.method,
            request.url.path + (f"?{request.url.query}" if request.url.query else ""),
            headers=headers,
            content=body,
        )
        try:
            upstream_response = await http.send(upstream_request, stream=True)
        except httpx.HTTPError:
            return PlainTextResponse("WanGP is not answering.", status_code=502)
        response_headers = {
            name: value
            for name, value in upstream_response.headers.items()
            if name.lower() not in HOP_BY_HOP
        }
        return StreamingResponse(
            upstream_response.aiter_raw(),
            status_code=upstream_response.status_code,
            headers=response_headers,
            background=BackgroundTask(upstream_response.aclose),
        )

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        yield
        await http.aclose()

    return Starlette(routes=[Route("/{path:path}", proxy, methods=METHODS)], lifespan=lifespan)


def main() -> int:
    token = os.environ.get("WAN2GP_MCP_TOKEN", "")
    if not token:
        print("WAN2GP_MCP_TOKEN must be non-empty.", file=sys.stderr)
        return 64
    host = os.environ.get("WAN2GP_MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("WAN2GP_MCP_PORT", "7866"))
    upstream_port = int(os.environ.get("WANGP_UPSTREAM_PORT", "7867"))
    app = create_app(token, f"http://127.0.0.1:{upstream_port}")
    uvicorn.run(app, host=host, port=port, log_level="warning", proxy_headers=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
