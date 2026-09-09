#!/usr/bin/env python3
"""Expose the isolated WanGP runtime through NodeTool's provider adapter API."""

from __future__ import annotations

import contextlib
import json
import os
import sys
import threading
from pathlib import Path
from typing import Any


class _Emitter:
    def __init__(self) -> None:
        try:
            # Preserve a dedicated copy of the protocol pipe before fd 1 is
            # redirected. Native extensions and upstream code can bypass
            # contextlib.redirect_stdout by writing to the descriptor itself.
            self._stream = os.fdopen(
                os.dup(sys.stdout.fileno()),
                "w",
                encoding="utf-8",
                buffering=1,
            )
        except (AttributeError, OSError):  # StringIO and embedded test runners.
            self._stream = sys.stdout
        self._lock = threading.Lock()

    def send(self, event_type: str, data: dict[str, Any]) -> None:
        with self._lock:
            self._stream.write(
                json.dumps(
                    {"type": event_type, "data": data}, separators=(",", ":")
                )
                + "\n"
            )
            self._stream.flush()


def _read_request() -> dict[str, Any]:
    line = sys.stdin.buffer.readline(1024 * 1024 + 1)
    if not line or len(line) > 1024 * 1024:
        raise ValueError("Expected one provider request under 1 MiB")
    value = json.loads(line)
    if not isinstance(value, dict):
        raise ValueError("Provider request must be a JSON object")
    return value


def _reserve_stdout_for_protocol() -> None:
    """Route all ordinary and low-level stdout writes to stderr."""
    try:
        sys.stdout.flush()
        os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    except (AttributeError, OSError):
        # contextlib.redirect_stdout below remains the fallback for streams
        # without real file descriptors.
        pass


def _configure_wangp_root() -> Path:
    root = Path(os.environ.get("WANGP_ROOT", "/opt/Wan2GP")).resolve()
    if not (root / "shared").is_dir():
        raise FileNotFoundError(f"WanGP checkout is missing its shared package: {root}")
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    return root


def _session(root: Path, callbacks: object | None = None) -> Any:
    from shared.api import init

    return init(
        root=str(root),
        config_path=os.environ.get("WANGP_CONFIG_PATH"),
        output_dir=os.environ.get("WANGP_OUTPUT_DIR"),
        callbacks=callbacks,
        console_output=True,
        console_isatty=False,
    )


def _video_models(session: Any) -> list[dict[str, Any]]:
    models: list[dict[str, Any]] = []
    for metadata in session.list_model_metadata():
        outputs = metadata.get("outputs", [])
        if "video" not in outputs:
            continue
        capabilities = metadata.get("capabilities", {})
        supported = [
            task
            for task in ("text_to_video", "image_to_video")
            if capabilities.get(task)
        ]
        if not supported:
            continue
        model_type = str(metadata.get("model_type") or "").strip()
        if not model_type:
            continue
        models.append(
            {
                "id": model_type,
                "name": str(metadata.get("name") or model_type),
                "provider": "wangp",
                "supportedTasks": supported,
            }
        )
    return models


def _settings(request: dict[str, Any]) -> dict[str, Any]:
    params = request.get("params")
    if not isinstance(params, dict):
        raise ValueError("Provider generation requires params")
    model = params.get("model")
    if isinstance(model, dict):
        model = model.get("id")
    model_type = str(model or "").strip()
    if not model_type:
        raise ValueError("Provider generation requires a model id")

    settings: dict[str, Any] = {
        "model_type": model_type,
        "prompt": str(params.get("prompt") or ""),
    }
    mappings = {
        "negativePrompt": "negative_prompt",
        "resolution": "resolution",
        "guidanceScale": "guidance_scale",
        "numInferenceSteps": "num_inference_steps",
        "seed": "seed",
    }
    for source, target in mappings.items():
        value = params.get(source)
        if value is not None:
            settings[target] = value
    if params.get("numFrames") is not None:
        settings["video_length"] = int(params["numFrames"])
    elif params.get("durationSeconds") is not None:
        settings["video_length"] = f"{float(params['durationSeconds']):g}s"

    if request["operation"] == "image_to_video":
        image_path = Path(str(request.get("image_path") or "")).resolve()
        if not image_path.is_file():
            raise ValueError("image_to_video requires a readable image_path")
        settings["image_start"] = str(image_path)
        settings["image_prompt_type"] = "S"
    return settings


class _Callbacks:
    def __init__(self, emitter: _Emitter) -> None:
        self._emitter = emitter

    def on_progress(self, update: Any) -> None:
        self._emitter.send(
            "progress",
            {
                "phase": str(getattr(update, "phase", "") or ""),
                "status": str(getattr(update, "status", "") or ""),
                "progress": int(getattr(update, "progress", 0) or 0),
                "current_step": getattr(update, "current_step", None),
                "total_steps": getattr(update, "total_steps", None),
            },
        )


def _generated_path(result: Any) -> str:
    if not getattr(result, "success", False):
        errors = getattr(result, "errors", ())
        detail = "; ".join(str(error) for error in errors) or "generation failed"
        raise RuntimeError(detail)
    for path in getattr(result, "generated_files", ()):
        candidate = Path(str(path))
        if candidate.is_file():
            return str(candidate.resolve())
    for artifact in getattr(result, "artifacts", ()):
        path = getattr(artifact, "path", None)
        if path and Path(path).is_file():
            return str(Path(path).resolve())
    raise RuntimeError("WanGP completed without a generated media file")


def main() -> int:
    emitter = _Emitter()
    request = _read_request()
    _reserve_stdout_for_protocol()
    operation = str(request.get("operation") or "")
    root = _configure_wangp_root()

    # WanGP writes human-readable diagnostics to stdout. Preserve stdout as the
    # machine-readable adapter channel without modifying upstream code.
    with contextlib.redirect_stdout(sys.stderr):
        if operation == "models":
            model_type = str(request.get("model_type") or "")
            models = _video_models(_session(root)) if model_type == "video" else []
            emitter.send("result", {"models": models})
            return 0
        if operation not in {"text_to_video", "image_to_video"}:
            raise ValueError(f"Unsupported provider operation: {operation}")
        callbacks = _Callbacks(emitter)
        result = _session(root, callbacks).run_task(_settings(request))
        emitter.send("result", {"path": _generated_path(result)})
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"WanGP provider adapter failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
