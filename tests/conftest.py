"""A fake Wan2GP MCP server, served in-process over httpx.ASGITransport.

No sockets and no Wan2GP. The app answers the MCP streamable-HTTP handshake and
the ``/wangp_api`` media transfer routes, and records every request so a test can
assert which tools the client actually called.

The response shapes come from reading Wan2GP at commit
057f9ecab9ad57dfbec9768b2daf7a4426ce986c, not from a live server. See
docs/wan2gp-contract.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

FIXTURES = Path(__file__).parent / "fixtures"

PROTOCOL_VERSION = "2025-06-18"

# The tools the fake exposes, with the argument names Wan2GP declares.
TOOL_NAMES = [
    "wangp_models",
    "wangp_model",
    "wangp_list_loras",
    "wangp_generate",
    "wangp_get_job",
    "wangp_cancel_job",
    "wangp_list_gallery",
    "wangp_create_gallery_upload",
    "wangp_create_gallery_download",
]


def fixture(name: str) -> Any:
    """Load one recorded Wan2GP response."""
    return json.loads((FIXTURES / f"{name}.json").read_text())


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class FakeWan2GP:
    """An ASGI app that behaves enough like Wan2GP's MCP server."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.tool_calls: list[dict[str, Any]] = []
        self.uploads: dict[str, bytes] = {}
        self.upload_filenames: dict[str, str] = {}
        self.cancelled_jobs: list[str] = []
        # Snapshots wangp_get_job returns, in order. The last one repeats.
        self.job_snapshots: list[dict[str, Any]] = [fixture("job_done")]
        self.download_payload: bytes = fixture_bytes("tiny.mp4")
        # Tool name -> message. A listed tool answers with isError instead.
        self.tool_errors: dict[str, str] = {}
        self._get_job_index = 0

    # -- tool implementations -------------------------------------------

    def tool_result(self, name: str, args: dict[str, Any]) -> Any:
        if name == "wangp_models":
            return fixture("models")
        if name == "wangp_model":
            if args.get("view") == "defaults":
                return fixture(f"model_defaults_{args['model_type']}")
            return {"model_type": args["model_type"], "view": args.get("view", "schema")}
        if name == "wangp_generate":
            return fixture("job_submitted")
        if name == "wangp_get_job":
            index = min(self._get_job_index, len(self.job_snapshots) - 1)
            self._get_job_index += 1
            return self.job_snapshots[index]
        if name == "wangp_cancel_job":
            self.cancelled_jobs.append(args["job_id"])
            return fixture("job_cancelled")
        if name == "wangp_list_gallery":
            return []
        if name == "wangp_create_gallery_upload":
            ticket = dict(fixture("gallery_upload_ticket"))
            ticket["filename"] = args["filename"]
            token = ticket["upload_url"].rsplit("/", 1)[-1]
            self.upload_filenames[token] = args["filename"]
            return ticket
        if name == "wangp_create_gallery_download":
            ticket = dict(fixture("gallery_download_ticket"))
            ticket["media_id"] = args["media_id"]
            return ticket
        if name == "wangp_list_loras":
            return {"loras": []}
        raise KeyError(name)

    # -- MCP JSON-RPC ----------------------------------------------------

    def handle_rpc(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        if method == "initialize":
            return self._ok(
                message,
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "WanGP", "version": "fake"},
                },
            )
        if method == "notifications/initialized":
            return None
        if method == "tools/list":
            return self._ok(
                message,
                {
                    "tools": [
                        {
                            "name": name,
                            "description": f"Fake {name}",
                            "inputSchema": {"type": "object", "properties": {}},
                        }
                        for name in TOOL_NAMES
                    ]
                },
            )
        if method == "tools/call":
            params = message.get("params") or {}
            name = params.get("name", "")
            args = params.get("arguments") or {}
            self.tool_calls.append({"name": name, "arguments": args})
            if name in self.tool_errors:
                return self._ok(
                    message,
                    {
                        "content": [{"type": "text", "text": self.tool_errors[name]}],
                        "isError": True,
                    },
                )
            try:
                value = self.tool_result(name, args)
            except KeyError:
                return self._ok(
                    message,
                    {
                        "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
                        "isError": True,
                    },
                )
            # FastMCP puts a dict return value in structuredContent verbatim and
            # every other return value under a "result" key.
            structured = value if isinstance(value, dict) else {"result": value}
            return self._ok(
                message,
                {
                    "content": [{"type": "text", "text": json.dumps(value)}],
                    "structuredContent": structured,
                    "isError": False,
                },
            )
        return {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

    @staticmethod
    def _ok(message: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": message.get("id"), "result": result}

    # -- ASGI ------------------------------------------------------------

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        assert scope["type"] == "http"
        body = await _read_body(receive)
        path = scope["path"]
        method = scope["method"]
        record: dict[str, Any] = {"method": method, "path": path}

        if path == "/mcp" and method == "POST":
            message = json.loads(body)
            record["rpc_method"] = message.get("method")
            if message.get("method") == "tools/call":
                record["tool"] = (message.get("params") or {}).get("name")
            self.requests.append(record)
            response = self.handle_rpc(message)
            if response is None:
                await _send(send, 202, b"", "text/plain")
                return
            await _send(send, 200, json.dumps(response).encode(), "application/json")
            return

        self.requests.append(record)

        if path.startswith("/wangp_api/gallery/upload/") and method == "PUT":
            token = path.rsplit("/", 1)[-1]
            self.uploads[token] = body
            result = dict(fixture("gallery_upload_result"))
            result["size"] = len(body)
            result["filename"] = self.upload_filenames.get(token, result["filename"])
            await _send(send, 200, json.dumps(result).encode(), "application/json")
            return

        if path.startswith("/wangp_api/gallery/download/") and method == "GET":
            await _send(send, 200, self.download_payload, "video/mp4")
            return

        await _send(send, 404, b'{"error":"not found"}', "application/json")

    # -- helpers for tests ------------------------------------------------

    def tool_names_called(self) -> set[str]:
        return {call["name"] for call in self.tool_calls}

    def args_for(self, name: str) -> list[dict[str, Any]]:
        return [call["arguments"] for call in self.tool_calls if call["name"] == name]


async def _read_body(receive: Any) -> bytes:
    body = b""
    while True:
        event = await receive()
        if event["type"] != "http.request":
            break
        body += event.get("body", b"")
        if not event.get("more_body"):
            break
    return body


async def _send(send: Any, status: int, body: bytes, content_type: str) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", content_type.encode()),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


@pytest.fixture
def fake_server() -> FakeWan2GP:
    return FakeWan2GP()


@pytest.fixture
def client_factory(fake_server: FakeWan2GP):
    """An httpx client factory the mcp client accepts, wired to the fake app."""

    def factory(
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=fake_server),
            headers=headers,
            timeout=timeout if timeout is not None else httpx.Timeout(30.0),
            auth=auth,
            follow_redirects=True,
        )

    return factory


@pytest.fixture
def server_url() -> str:
    return "http://wan2gp.test/mcp"


@pytest.fixture
def wan2gp_nodes(monkeypatch, client_factory):
    """Point every node at the fake server instead of a real socket.

    Nodes build their own client, so the test replaces the class the base node
    reaches for. It also drops the poll interval, so a test never waits.
    """
    from nodetool.nodes.wan2gp import _base
    from nodetool.nodes.wan2gp._client import Wan2GPClient

    def make_client(url: str, timeout: float = 1800.0) -> Wan2GPClient:
        return Wan2GPClient(url, timeout=timeout, httpx_client_factory=client_factory)

    monkeypatch.setattr(_base, "Wan2GPClient", make_client)
    monkeypatch.setattr(_base, "POLL_INTERVAL_SECONDS", 0.0)
    return _base


@pytest.fixture
def context(tmp_path):
    """A real ProcessingContext with a workspace, as the node tests use it."""
    from nodetool.workflows.processing_context import ProcessingContext

    return ProcessingContext(workspace_dir=str(tmp_path))


def progress_messages(context) -> list:
    """Drain the context's message queue and return the NodeProgress messages."""
    from nodetool.workflows.types import NodeProgress

    messages = []
    while not context.message_queue.empty():
        messages.append(context.message_queue.get_nowait())
    return [m for m in messages if isinstance(m, NodeProgress)]
