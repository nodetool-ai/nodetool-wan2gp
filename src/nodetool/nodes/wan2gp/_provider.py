"""Serve your own Wan2GP MCP server as NodeTool's ``wangp`` provider.

A NodeTool Python worker runs this module once per provider request when
``NODETOOL_PROVIDER_ADAPTER_COMMAND_WANGP`` names it. The worker writes one
JSON request line to stdin and reads JSON-lines events from stdout: any number
of ``progress`` events, then one ``result``. Media arrives as files the worker
staged, and the result names an output file the worker reads and deletes.

Unlike ``combined/provider_adapter.py``, which runs WanGP in its own
interpreter, this adapter is an MCP client. It never imports WanGP: every call
goes through ``_client.py`` to the server at ``WAN2GP_MCP_URL``. With it, the
composer, the Create view and ejected workflows list the models of a Wan2GP
server you run yourself, and presets compile for them before the prompt
arrives here.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any, TextIO

from mcp.shared._httpx_utils import McpHttpClientFactory, create_mcp_http_client

from ._base import image_filename, resolve_server_url
from ._client import (
    CANCEL_TIMEOUT_SECONDS,
    MAX_MEDIA_BYTES,
    Wan2GPClient,
    Wan2GPError,
    job_error_message,
)

PROVIDER_ID = "wangp"
#: Overall deadline for one generation, overridable with WAN2GP_PROVIDER_TIMEOUT_SECONDS.
DEFAULT_TIMEOUT_SECONDS = 1800.0
POLL_INTERVAL_SECONDS = 1.0
#: The largest request line the worker sends.
REQUEST_LINE_LIMIT = 1024 * 1024

Emit = Callable[[str, dict[str, Any]], None]

#: Operation -> the media type its result must have.
_OUTPUTS = {
    "text_to_video": "video",
    "image_to_video": "video",
    "reference_to_video": "video",
    "text_to_image": "image",
    "image_to_image": "image",
}

#: Model kind -> (main_output filter, [(task, WanGP capability)]).
_MODEL_KINDS = {
    "video": ("video", [
        ("text_to_video", "text_to_video"),
        ("image_to_video", "image_to_video"),
        ("reference_to_video", "reference_images"),
    ]),
    "image": ("image", [
        ("text_to_image", "text_to_image"),
        ("image_to_image", "image_to_image"),
    ]),
}

_SUFFIXES = {
    "video": (".mp4", ".mov", ".mkv", ".webm", ".avi"),
    "image": (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"),
}


# -- requests -----------------------------------------------------------------


def _param(params: dict[str, Any], *names: str) -> Any:
    """Return the first non-null value among a parameter's spellings."""
    for name in names:
        if params.get(name) is not None:
            return params[name]
    return None


def _model_type(params: dict[str, Any]) -> str:
    model = params.get("model")
    if isinstance(model, dict):
        model = model.get("id")
    model_type = str(model or "").strip()
    if not model_type:
        raise Wan2GPError("The provider request names no model.")
    return model_type


def _resolution(params: dict[str, Any]) -> str | None:
    """Return a ``WxH`` resolution from a tier such as ``720p``, or from a size.

    A tier sets the short side, and the aspect ratio, ``16:9`` by default,
    sets the long one. WanGP aligns the result to its own block size.
    """
    value = _param(params, "resolution")
    if isinstance(value, str) and value.strip():
        tier = re.fullmatch(r"\s*(\d+)\s*[pP]\s*", value)
        if tier is None:
            return value.strip()
        short = int(tier.group(1))
        ratio = str(_param(params, "aspect_ratio", "aspectRatio") or "16:9")
        parts = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)\s*", ratio)
        if parts is None or float(parts.group(1)) <= 0 or float(parts.group(2)) <= 0:
            raise Wan2GPError(f"Invalid aspect ratio: {ratio!r}")
        across, down = float(parts.group(1)), float(parts.group(2))
        if across >= down:
            return f"{round(short * across / down)}x{short}"
        return f"{short}x{round(short * down / across)}"
    width = _param(params, "width", "targetWidth", "target_width")
    height = _param(params, "height", "targetHeight", "target_height")
    if width is not None and height is not None:
        return f"{int(width)}x{int(height)}"
    return None


def base_settings(operation: str, params: dict[str, Any]) -> dict[str, Any]:
    """Map NodeTool provider params to WanGP settings, without media."""
    settings: dict[str, Any] = {
        "model_type": _model_type(params),
        "prompt": str(_param(params, "prompt", "text") or ""),
    }
    for key, names in (
        ("negative_prompt", ("negative_prompt", "negativePrompt")),
        ("num_inference_steps", ("num_inference_steps", "numInferenceSteps")),
        ("seed", ("seed",)),
        ("guidance_scale", ("guidance_scale", "guidanceScale")),
        ("denoising_strength", ("strength",)),
    ):
        value = _param(params, *names)
        if value is not None and value != "":
            settings[key] = value
    resolution = _resolution(params)
    if resolution is not None:
        settings["resolution"] = resolution
    if _OUTPUTS[operation] == "video":
        frames = _param(params, "num_frames", "numFrames")
        seconds = _param(params, "duration_seconds", "durationSeconds")
        if frames is not None:
            settings["video_length"] = int(frames)
        elif seconds is not None:
            settings["video_length"] = f"{float(seconds):g}s"
    else:
        # Selects the image output on models that also make video, such as H3.
        settings["image_mode"] = 1
    return settings


def _input_file(path: Any, name: str) -> bytes:
    file = Path(str(path or ""))
    if not file.is_file() or file.stat().st_size == 0:
        raise Wan2GPError(f"The provider request has no readable {name}.")
    return file.read_bytes()


async def _upload_image(client: Wan2GPClient, path: Any, name: str) -> str:
    data = _input_file(path, name)
    return await client.upload_bytes(image_filename(data), data)


async def build_settings(client: Wan2GPClient, request: dict[str, Any]) -> dict[str, Any]:
    """Return the settings for one generation request, uploading its media."""
    operation = str(request.get("operation") or "")
    params = request.get("params")
    if not isinstance(params, dict):
        raise Wan2GPError("The provider request has no params.")
    settings = base_settings(operation, params)
    model_type = settings["model_type"]
    if operation == "image_to_video":
        settings["image_start"] = await _upload_image(client, request.get("image_path"), "image")
    elif operation == "image_to_image":
        roles = (await client.get_model_capabilities(model_type)).get("media_inputs", {}).get("image", [])
        if "start" in roles:
            settings["image_start"] = await _upload_image(client, request.get("image_path"), "image")
        elif "reference" in roles:
            settings["image_refs"] = [await _upload_image(client, request.get("image_path"), "image")]
        else:
            raise Wan2GPError(f"Wan2GP model {model_type} takes no input image.")
    elif operation == "reference_to_video":
        if request.get("reference_video_paths"):
            raise Wan2GPError(
                "This adapter does not send reference videos yet. Use the Generate node with a video input."
            )
        paths = request.get("reference_image_paths") or []
        if not isinstance(paths, list) or not paths:
            raise Wan2GPError("reference_to_video needs at least one reference image.")
        settings["image_refs"] = [
            await _upload_image(client, path, "reference image") for path in paths
        ]
    return settings


# -- models -------------------------------------------------------------------


async def list_provider_models(client: Wan2GPClient, kind: str) -> list[dict[str, Any]]:
    """Return the server's models of one kind as NodeTool provider models."""
    if kind not in _MODEL_KINDS:
        return []
    main_output, tasks = _MODEL_KINDS[kind]
    models: list[dict[str, Any]] = []
    for row in await client.search_all_models(filters={"main_output": main_output}):
        capabilities = set(row.get("capabilities") or [])
        supported = [task for task, capability in tasks if capability in capabilities]
        model_type = str(row.get("model_type") or "").strip()
        if not supported or not model_type:
            continue
        models.append({
            "id": model_type,
            "name": str(row.get("name") or model_type),
            "provider": PROVIDER_ID,
            "supportedTasks": supported,
        })
    return models


# -- generation ---------------------------------------------------------------


def _progress(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "phase": str(payload.get("phase") or ""),
        "status": str(payload.get("status") or ""),
        "progress": int(payload.get("progress") or 0),
        "current_step": payload.get("current_step"),
        "total_steps": payload.get("total_steps"),
    }


def _output_suffix(item: dict[str, Any], media_type: str) -> str:
    suffix = PurePosixPath(str(item.get("filename") or "")).suffix.lower()
    return suffix if suffix in _SUFFIXES[media_type] else _SUFFIXES[media_type][0]


async def generate(
    client: Wan2GPClient,
    request: dict[str, Any],
    emit: Emit,
    output_dir: Path,
    timeout: float,
) -> str:
    """Run one generation and return the path of the file it produced."""
    operation = str(request.get("operation") or "")
    expected = _OUTPUTS[operation]
    settings = await build_settings(client, request)
    job_id = await client.submit(settings)
    try:
        job = await client.poll_until_done(
            job_id,
            on_progress=lambda payload: emit("progress", _progress(payload)),
            interval=POLL_INTERVAL_SECONDS,
            timeout=timeout,
        )
    except BaseException:
        # A worker cancel or timeout must not leave the remote job running.
        try:
            async with asyncio.timeout(CANCEL_TIMEOUT_SECONDS):
                await client.cancel(job_id)
        except BaseException:
            pass
        raise
    result = job.get("result") or {}
    if not result.get("success"):
        raise Wan2GPError(job_error_message(job))
    items = [item for item in result.get("gallery_items") or [] if isinstance(item, dict)]
    if not items:
        raise Wan2GPError("Wan2GP finished the generation but put no media in its gallery.")
    item = items[0]
    media_type = str(item.get("media_type") or "").lower()
    if media_type != expected:
        raise Wan2GPError(f"Wan2GP returned {media_type or 'unknown'} output for {operation}, which needs {expected}.")
    data = await client.download_media(str(item.get("media_id") or ""))
    output_dir.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix="wan2gp-", suffix=_output_suffix(item, expected), dir=output_dir)
    with os.fdopen(handle, "wb") as file:
        file.write(data)
    return name


async def run_request(
    request: dict[str, Any],
    emit: Emit,
    *,
    server_url: str | None = None,
    output_dir: Path | None = None,
    httpx_client_factory: McpHttpClientFactory = create_mcp_http_client,
) -> None:
    """Answer one provider request, emitting progress and one result."""
    operation = str(request.get("operation") or "")
    if operation != "models" and operation not in _OUTPUTS:
        raise Wan2GPError(f"The Wan2GP MCP adapter does not support {operation or 'an empty operation'}.")
    timeout = float(os.environ.get("WAN2GP_PROVIDER_TIMEOUT_SECONDS") or DEFAULT_TIMEOUT_SECONDS)
    async with Wan2GPClient(
        resolve_server_url(server_url),
        timeout=timeout,
        httpx_client_factory=httpx_client_factory,
        max_transfer_bytes=MAX_MEDIA_BYTES,
    ) as client:
        if operation == "models":
            models = await list_provider_models(client, str(request.get("model_type") or ""))
            emit("result", {"models": models})
            return
        directory = output_dir or Path(tempfile.gettempdir()) / "nodetool-wan2gp-provider"
        emit("result", {"path": await generate(client, request, emit, directory, timeout)})


# -- command ------------------------------------------------------------------


def _protocol_stream() -> TextIO:
    """Keep a private copy of stdout for events and send everything else to stderr.

    Libraries may write to stdout, which would corrupt the event stream.
    """
    try:
        stream = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8", buffering=1)
        sys.stdout.flush()
        os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
        return stream
    except (AttributeError, OSError, ValueError):
        return sys.stdout


def main() -> int:
    stream = _protocol_stream()

    def emit(kind: str, data: dict[str, Any]) -> None:
        stream.write(json.dumps({"type": kind, "data": data}, separators=(",", ":")) + "\n")
        stream.flush()

    async def serve() -> None:
        line = sys.stdin.buffer.readline(REQUEST_LINE_LIMIT + 1)
        if not line or len(line) > REQUEST_LINE_LIMIT:
            raise Wan2GPError("Expected one provider request line under 1 MiB.")
        request = json.loads(line)
        if not isinstance(request, dict):
            raise Wan2GPError("The provider request must be a JSON object.")
        task = asyncio.current_task()
        if task is not None:
            # The worker stops a cancelled request with SIGTERM.
            asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, task.cancel)
        await run_request(request, emit)

    try:
        asyncio.run(serve())
    except BaseException as error:
        print(f"Wan2GP MCP adapter failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
