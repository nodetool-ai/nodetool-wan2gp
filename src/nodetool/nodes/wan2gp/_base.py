"""The shared base class for every Wan2GP node.

It owns the connection fields, the submit-poll-download run loop, and the
cancellation handshake. The nodes themselves only decide which settings to
send. Nothing here imports Wan2GP: the process boundary is the license
boundary (see NOTICE.md).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from typing import Any

from nodetool.metadata.types import AssetRef, ImageRef, VideoRef
from nodetool.workflows.base_node import BaseNode
from nodetool.workflows.processing_context import ProcessingContext
from nodetool.workflows.types import NodeProgress
from pydantic import Field

from ._client import (
    CANCEL_TIMEOUT_SECONDS,
    DEFAULT_MAX_MEDIA_BYTES,
    DEFAULT_SERVER_URL,
    MAX_MEDIA_BYTES,
    Wan2GPClient,
    job_error_message,
)

#: How long to wait between two ``wangp_get_job`` polls.
POLL_INTERVAL_SECONDS = 1.0

#: Empty metadata-safe sentinel; the environment is resolved at execution time.
SERVER_URL_DEFAULT: str | None = None


def resolve_server_url(server_url: str | None) -> str:
    """Resolve an explicit node URL, then the runtime environment, then localhost."""
    explicit = (server_url or "").strip()
    if explicit:
        return explicit
    return os.environ.get("WAN2GP_MCP_URL", "").strip() or DEFAULT_SERVER_URL

SettingsBuilder = Callable[[Wan2GPClient], Awaitable[dict[str, Any]]]

# Leading bytes that identify the image and video containers Wan2GP's gallery
# accepts. The server picks a media type from the filename extension alone, so
# the extension has to match the bytes.
_IMAGE_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
    (b"BM", ".bmp"),
)


def image_filename(data: bytes) -> str:
    """Return an upload filename whose extension matches the image bytes."""
    for signature, suffix in _IMAGE_SIGNATURES:
        if data.startswith(signature):
            return f"image{suffix}"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image.webp"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "image.tif"
    return "image.png"


def video_filename(data: bytes) -> str:
    """Return an upload filename whose extension matches the video bytes."""
    if data[4:8] == b"ftyp":
        return "video.mov" if data[8:12] == b"qt  " else "video.mp4"
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return "video.webm"
    if data[:4] == b"RIFF" and data[8:12] == b"AVI ":
        return "video.avi"
    return "video.mp4"


class _Wan2GPNode(BaseNode):
    """Shared connection fields and run loop. Not a node in its own right."""

    server_url: str | None = Field(
        default=SERVER_URL_DEFAULT,
        description="URL of the MCP endpoint of your own Wan2GP server, for example http://127.0.0.1:7866/mcp. Leave blank to use WAN2GP_MCP_URL at execution time, then localhost.",
    )
    timeout_seconds: int = Field(
        default=1800,
        ge=1,
        description="How long to wait for one generation before giving up, in seconds.",
    )
    max_media_bytes: int = Field(
        default=DEFAULT_MAX_MEDIA_BYTES,
        ge=1,
        le=MAX_MEDIA_BYTES,
        description="Maximum media upload/download size in bytes. Defaults to 512 MiB; values up to the 8 GiB safety ceiling are allowed.",
    )
    seed: int = Field(
        default=-1,
        description="Random seed. Use -1 to let Wan2GP pick a new seed for every run.",
    )

    @classmethod
    def is_visible(cls) -> bool:
        return cls is not _Wan2GPNode

    @classmethod
    def is_cacheable(cls) -> bool:
        return False

    def requires_gpu(self) -> bool:
        return False

    # -- media in ---------------------------------------------------------

    async def upload_image(
        self, context: ProcessingContext, client: Wan2GPClient, image: ImageRef
    ) -> str:
        """Put an image in Wan2GP's gallery and return its ``media_id``."""
        data = await context.asset_to_bytes(image)
        return await client.upload_bytes(image_filename(data), data)

    async def upload_video(
        self, context: ProcessingContext, client: Wan2GPClient, video: VideoRef
    ) -> str:
        """Put a video in Wan2GP's gallery and return its ``media_id``."""
        data = await context.asset_to_bytes(video)
        return await client.upload_bytes(video_filename(data), data)

    # -- run loop ---------------------------------------------------------

    def post_progress(self, context: ProcessingContext, payload: dict[str, Any]) -> None:
        """Forward one Wan2GP progress event to the NodeTool UI.

        Wan2GP reports both a percentage and, in phases that step, a step
        counter. The step counter is the more useful of the two, so it wins
        when it is there.
        """
        current = payload.get("current_step")
        total = payload.get("total_steps")
        if not isinstance(current, int) or not isinstance(total, int) or total <= 0:
            current = int(payload.get("progress") or 0)
            total = 100
        context.post_message(
            NodeProgress(node_id=self.id, progress=int(current), total=int(total))
        )

    async def run_generation(
        self,
        context: ProcessingContext,
        build_settings: SettingsBuilder,
        expected_media_type: str | None = None,
    ) -> AssetRef:
        """Submit one generation, follow it, and return its first output.

        ``build_settings`` gets a connected client so a node can upload its
        input media before it decides on the settings dict.
        """
        async with Wan2GPClient(
            resolve_server_url(self.server_url),
            timeout=float(self.timeout_seconds),
            max_transfer_bytes=self.max_media_bytes,
        ) as client:
            settings = await build_settings(client)
            context.raise_if_cancelled()
            job_id = await client.submit(settings)
            job = await self._follow_job(context, client, job_id)
            return await self._output_of(context, client, job, expected_media_type)

    async def _follow_job(
        self, context: ProcessingContext, client: Wan2GPClient, job_id: str
    ) -> dict[str, Any]:
        """Poll one job to the end, cancelling it if this node is cancelled."""

        async def sleep(seconds: float) -> None:
            context.raise_if_cancelled()
            await asyncio.sleep(seconds)

        def on_progress(payload: dict[str, Any]) -> None:
            self.post_progress(context, payload)

        try:
            return await client.poll_until_done(
                job_id,
                on_progress=on_progress,
                interval=POLL_INTERVAL_SECONDS,
                timeout=float(self.timeout_seconds),
                sleep=sleep,
            )
        except BaseException:
            # Timeout, a failed poll, and local cancellation all leave a queued
            # remote job behind unless we ask the server to stop it. Keep this
            # bounded: cancellation is cooperative and best effort.
            try:
                async with asyncio.timeout(CANCEL_TIMEOUT_SECONDS):
                    await client.cancel(job_id)
            except BaseException:
                pass
            raise

    async def _output_of(
        self,
        context: ProcessingContext,
        client: Wan2GPClient,
        job: dict[str, Any],
        expected_media_type: str | None = None,
    ) -> AssetRef:
        """Convert the first gallery item to its declared media reference."""
        result = job.get("result") or {}
        if not result.get("success"):
            raise ValueError(job_error_message(job))
        items = result.get("gallery_items") or []
        if not items:
            raise ValueError(
                "Wan2GP finished the generation but put no media in its gallery."
            )
        item = items[0]
        if not isinstance(item, dict):
            raise ValueError("Wan2GP returned an invalid gallery item.")
        media_id = str(item.get("media_id") or "").strip()
        media_type = str(item.get("media_type") or "").strip().lower()
        if not media_id:
            raise ValueError("Wan2GP returned a gallery item without a media_id.")
        if media_type not in {"image", "video", "audio"}:
            raise ValueError(f"Wan2GP returned an unsupported gallery media_type: {media_type or '(missing)'}.")
        if expected_media_type is not None and media_type != expected_media_type:
            raise ValueError(
                f"Wan2GP returned {media_type} output, but this node requires {expected_media_type}."
            )
        data = await client.download_media(media_id)
        if media_type == "image":
            return await context.image_from_bytes(data)
        if media_type == "audio":
            return await context.audio_from_bytes(data)
        return await context.video_from_bytes(data)
