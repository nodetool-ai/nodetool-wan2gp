"""Async client for a Wan2GP MCP server the user runs themselves.

Every call this package makes to Wan2GP goes through this module. Nodes never
build JSON-RPC and never import Wan2GP: the process boundary is the license
boundary (see NOTICE.md).

The transport is MCP streamable HTTP. Wan2GP serves it at ``/mcp`` and serves
one-use media transfer routes under ``/wangp_api/`` on the same origin, so both
share one base URL. See docs/wan2gp-contract.md for the tool shapes.
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared._httpx_utils import McpHttpClientFactory, create_mcp_http_client
from mcp.types import CallToolResult, TextContent

DEFAULT_SERVER_URL = "http://127.0.0.1:7866/mcp"

# Extensions Wan2GP's gallery accepts, from shared/mcp_server.py.
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
_AUDIO_EXTENSIONS = {".wav", ".mp3", ".aac", ".m4a", ".flac", ".ogg", ".opus"}
_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}

ProgressCallback = Callable[[dict[str, Any]], None] | Callable[[dict[str, Any]], Awaitable[None]]


class Wan2GPError(RuntimeError):
    """A Wan2GP server rejected a call, or reported a failed generation."""


def media_type_for(filename: str) -> str:
    """Return ``image``, ``video`` or ``audio`` for a filename Wan2GP accepts."""
    suffix = Path(filename).suffix.lower()
    if suffix in _IMAGE_EXTENSIONS:
        return "image"
    if suffix in _VIDEO_EXTENSIONS:
        return "video"
    if suffix in _AUDIO_EXTENSIONS:
        return "audio"
    raise Wan2GPError(
        f"Wan2GP does not accept the file extension {suffix or '(none)'} for gallery uploads."
    )


def _origin_of(server_url: str) -> str:
    """Return the origin that Wan2GP's relative transfer URLs resolve against."""
    parsed = httpx.URL(server_url)
    return str(parsed.copy_with(raw_path=b"/", query=None, fragment=None))


def _text_payload(result: CallToolResult) -> str | None:
    for block in result.content:
        if isinstance(block, TextContent):
            return block.text
    return None


def _error_message(result: CallToolResult, tool_name: str) -> str:
    text = _text_payload(result)
    if text:
        return text.strip()
    return f"Wan2GP tool {tool_name} failed without a message."


def parse_tool_result(result: CallToolResult, tool_name: str) -> Any:
    """Turn a CallToolResult into the value the Wan2GP tool returned.

    FastMCP puts a dict return value in ``structuredContent`` verbatim and any
    other return value under a ``result`` key there. Both also arrive as JSON
    text, which is the fallback when a server omits structured content.
    """
    if result.isError:
        raise Wan2GPError(_error_message(result, tool_name))

    structured = result.structuredContent
    if structured is not None:
        if set(structured.keys()) == {"result"}:
            return structured["result"]
        return structured

    text = _text_payload(result)
    if text is None:
        raise Wan2GPError(f"Wan2GP tool {tool_name} returned no content.")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise Wan2GPError(
            f"Wan2GP tool {tool_name} returned content that is not JSON: {text[:200]}"
        ) from exc


def progress_from_job(job: dict[str, Any]) -> dict[str, Any] | None:
    """Return the most recent progress event payload in a job snapshot."""
    for event in reversed(job.get("events") or []):
        if event.get("kind") == "progress" and isinstance(event.get("data"), dict):
            return event["data"]
    return None


def job_error_message(job: dict[str, Any]) -> str:
    """Join the errors of a finished job into one message."""
    result = job.get("result") or {}
    parts = []
    for error in result.get("errors") or []:
        message = str(error.get("message") or "").strip()
        stage = str(error.get("stage") or "").strip()
        parts.append(f"{message} (stage: {stage})" if stage else message)
    if not parts:
        return "Wan2GP reported a failed generation without an error message."
    return "; ".join(parts)


class Wan2GPClient:
    """One MCP session against one Wan2GP server.

    Use it as an async context manager::

        async with Wan2GPClient("http://127.0.0.1:7866/mcp") as client:
            job_id = await client.submit(settings)
            job = await client.poll_until_done(job_id)
    """

    def __init__(
        self,
        server_url: str = DEFAULT_SERVER_URL,
        timeout: float = 1800.0,
        httpx_client_factory: McpHttpClientFactory = create_mcp_http_client,
    ) -> None:
        self.server_url = server_url
        self.origin = _origin_of(server_url)
        self.timeout = timeout
        self._httpx_client_factory = httpx_client_factory
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._media_client: httpx.AsyncClient | None = None

    # -- connection ------------------------------------------------------

    async def connect(self) -> "Wan2GPClient":
        """Open the transport and complete the MCP handshake."""
        if self._session is not None:
            return self
        stack = AsyncExitStack()
        try:
            read_stream, write_stream, _get_session_id = await stack.enter_async_context(
                streamablehttp_client(
                    self.server_url,
                    timeout=self.timeout,
                    sse_read_timeout=self.timeout,
                    httpx_client_factory=self._httpx_client_factory,
                )
            )
            session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
            await session.initialize()
            self._media_client = await stack.enter_async_context(
                self._httpx_client_factory(timeout=httpx.Timeout(self.timeout))
            )
        except BaseException:
            await stack.aclose()
            raise
        self._stack = stack
        self._session = session
        return self

    async def close(self) -> None:
        """Close the transport."""
        stack, self._stack = self._stack, None
        self._session = None
        self._media_client = None
        if stack is not None:
            await stack.aclose()

    async def __aenter__(self) -> "Wan2GPClient":
        return await self.connect()

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.close()

    @property
    def session(self) -> ClientSession:
        if self._session is None:
            raise Wan2GPError("The Wan2GP client is not connected. Call connect() first.")
        return self._session

    @property
    def media_client(self) -> httpx.AsyncClient:
        if self._media_client is None:
            raise Wan2GPError("The Wan2GP client is not connected. Call connect() first.")
        return self._media_client

    # -- tools -----------------------------------------------------------

    async def call_tool(self, name: str, args: dict[str, Any] | None = None) -> Any:
        """Call one MCP tool and return its parsed return value."""
        result = await self.session.call_tool(name, args or {})
        return parse_tool_result(result, name)

    async def list_tools(self) -> list[str]:
        """Return the names of the tools this server exposes."""
        listing = await self.session.list_tools()
        return [tool.name for tool in listing.tools]

    async def list_models(
        self,
        query: str = "",
        filters: dict[str, Any] | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Search Wan2GP's model registry. See ``wangp_models``."""
        args: dict[str, Any] = {"query": query, "limit": limit, "offset": offset}
        if filters:
            args["filters"] = filters
        return await self.call_tool("wangp_models", args)

    async def get_model_defaults(self, model_type: str) -> dict[str, Any]:
        """Return one model's pristine generation defaults."""
        return await self.call_tool(
            "wangp_model", {"model_type": model_type, "view": "defaults"}
        )

    # -- media -----------------------------------------------------------

    async def upload_bytes(self, filename: str, data: bytes) -> str:
        """Upload media to Wan2GP's gallery and return its ``media_id``.

        The returned id is what ``image_start``, ``video_guide`` and the other
        media settings accept. Local paths are rejected by the server unless it
        was started with ``--mcp-allow-read-file-system``, so this package never
        sends one.
        """
        media_type_for(filename)  # reject unsupported extensions before the round trip
        ticket = await self.call_tool("wangp_create_gallery_upload", {"filename": filename})
        url = httpx.URL(self.origin).join(ticket["upload_url"])
        response = await self.media_client.request(
            ticket.get("method", "PUT"),
            url,
            content=data,
            headers={"content-type": "application/octet-stream"},
        )
        if response.status_code >= 400:
            raise Wan2GPError(
                f"Wan2GP rejected the upload of {filename}: {response.status_code} {response.text}"
            )
        record = response.json()
        media_id = str(record.get("media_id") or "").strip()
        if not media_id:
            raise Wan2GPError(f"Wan2GP accepted the upload of {filename} but returned no media_id.")
        return media_id

    async def download_media(self, media_id: str) -> bytes:
        """Download one gallery item by ``media_id`` and return its bytes."""
        ticket = await self.call_tool("wangp_create_gallery_download", {"media_id": media_id})
        url = httpx.URL(self.origin).join(ticket["download_url"])
        response = await self.media_client.get(url)
        if response.status_code >= 400:
            raise Wan2GPError(
                f"Wan2GP rejected the download of {media_id}: {response.status_code} {response.text}"
            )
        return response.content

    # -- jobs ------------------------------------------------------------

    async def submit(self, settings: dict[str, Any]) -> str:
        """Start a generation from a settings dict and return its ``job_id``."""
        job = await self.call_tool("wangp_generate", {"source": settings, "wait": False})
        job_id = str(job.get("job_id") or "").strip()
        if not job_id:
            raise Wan2GPError("Wan2GP accepted the generation but returned no job_id.")
        return job_id

    async def get_job(self, job_id: str, event_limit: int | None = None) -> dict[str, Any]:
        """Poll one job once and return its snapshot."""
        args: dict[str, Any] = {"job_id": job_id}
        if event_limit is not None:
            args["event_limit"] = event_limit
        return await self.call_tool("wangp_get_job", args)

    async def cancel(self, job_id: str) -> dict[str, Any]:
        """Ask Wan2GP to cancel a job. Cancellation is cooperative."""
        return await self.call_tool("wangp_cancel_job", {"job_id": job_id})

    async def poll_until_done(
        self,
        job_id: str,
        on_progress: ProgressCallback | None = None,
        interval: float = 1.0,
        timeout: float | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        """Poll a job until it finishes and return its final snapshot.

        ``on_progress`` receives each new progress payload, which carries
        ``phase``, ``status``, ``progress`` (0-100), ``current_step`` and
        ``total_steps``. It may be sync or async.
        """
        if sleep is None:
            import anyio

            sleep = anyio.sleep
        deadline = None if timeout is None else time.monotonic() + timeout
        last_progress: dict[str, Any] | None = None
        while True:
            job = await self.get_job(job_id)
            progress = progress_from_job(job)
            if progress is not None and progress != last_progress:
                last_progress = progress
                if on_progress is not None:
                    outcome = on_progress(progress)
                    if isinstance(outcome, Awaitable):
                        await outcome
            if job.get("done"):
                return job
            if deadline is not None and time.monotonic() >= deadline:
                raise Wan2GPError(
                    f"Wan2GP job {job_id} did not finish within {timeout:g} seconds."
                )
            await sleep(interval)
