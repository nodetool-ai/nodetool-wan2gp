#!/usr/bin/env python3
"""Prepare a WanGP model and emit JSON-lines progress for NodeTool."""

from __future__ import annotations

import contextlib
import json
import os
import sys
import threading
from pathlib import Path
from typing import Any

try:
    from .download_telemetry import DownloadTelemetry
except ImportError:  # Executed as a copied standalone image script.
    from download_telemetry import DownloadTelemetry


def _read_request() -> dict[str, Any]:
    line = sys.stdin.buffer.readline(1024 * 1024 + 1)
    if not line or len(line) > 1024 * 1024:
        raise ValueError("Expected one model preparation request under 1 MiB")
    value = json.loads(line)
    if not isinstance(value, dict):
        raise ValueError("Model preparation request must be a JSON object")
    return value


class _Emitter:
    def __init__(self) -> None:
        self._stream = sys.stdout
        self._lock = threading.Lock()

    def send(self, payload: dict[str, object]) -> None:
        with self._lock:
            self._stream.write(json.dumps(payload, separators=(",", ":")) + "\n")
            self._stream.flush()


def _configure_wangp_root() -> Path:
    """Make the pinned WanGP checkout importable from this copied script."""
    root = Path(os.environ.get("WANGP_ROOT", "/opt/Wan2GP")).resolve()
    if not (root / "shared").is_dir():
        raise FileNotFoundError(f"WanGP checkout is missing its shared package: {root}")
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    return root


def _model_files(runtime: Any, model_type: str) -> list[tuple[str, int, int]]:
    """Mirror WanGP's own pre-load selection, stopping before model loading."""
    module = runtime.module
    model_def = module.get_model_def(model_type)
    if model_def is None:
        raise ValueError(f"Unknown WanGP model_type: {model_type}")
    quantization = module.transformer_quantization
    dtype_policy = module.transformer_dtype_policy
    selected: list[tuple[str, int, int]] = []

    primary = module.get_model_filename(
        model_type=model_type,
        quantization=quantization,
        dtype_policy=dtype_policy,
        model_def=model_def,
    )
    if primary:
        selected.append((primary, 0, 1))
    if "URLs2" in model_def:
        secondary = module.get_model_filename(
            model_type=model_type,
            quantization=quantization,
            dtype_policy=dtype_policy,
            submodel_no=2,
            model_def=model_def,
        )
        if secondary:
            selected.append((secondary, 0, 2))

    modules = module.get_model_recursive_prop(
        model_type, "modules", return_list=True, model_def=model_def
    )
    for module_type in modules:
        if isinstance(module_type, dict):
            for submodel_no, key in ((1, "URLs"), (2, "URLs2")):
                urls = module_type.get(key)
                if urls is None:
                    raise ValueError(f"WanGP module is missing {key}: {module_type}")
                filename = module.get_model_filename(
                    model_type,
                    quantization,
                    dtype_policy,
                    URLs=urls,
                )
                if filename:
                    selected.append((filename, 1, submodel_no))
        else:
            filename = module.get_model_filename(
                model_type,
                quantization,
                dtype_policy,
                module_type=module_type,
            )
            if filename:
                selected.append((filename, 1, 0))
    return selected


def _prepare(runtime: Any, model_type: str) -> None:
    module = runtime.module
    model_def = module.get_model_def(model_type)
    selected = _model_files(runtime, model_type)
    if not selected:
        module.download_models("", model_type, 0, -1, model_def=model_def)
    for filename, file_type, submodel_no in selected:
        module.download_models(
            filename,
            model_type,
            file_type,
            submodel_no,
            model_def=model_def,
        )

    text_encoder_urls = module.get_model_recursive_prop(
        model_type, "text_encoder_URLs", return_list=True, model_def=model_def
    )
    if text_encoder_urls:
        text_encoder = module.get_model_filename(
            model_type=model_type,
            quantization=module.text_encoder_quantization,
            dtype_policy=module.transformer_dtype_policy,
            URLs=text_encoder_urls,
        )
        if text_encoder:
            module.download_models(
                text_encoder,
                model_type,
                2,
                -1,
                force_path=model_def.get("text_encoder_folder"),
                model_def=model_def,
            )


def main() -> int:
    emitter = _Emitter()
    request = _read_request()
    wangp_root = _configure_wangp_root()
    model_type = str(request.get("model_type") or "").strip()
    if not model_type:
        raise ValueError("model_type is required")
    token = request.get("token")
    if isinstance(token, str) and token.strip():
        os.environ["HF_TOKEN"] = token.strip()

    roots = [
        Path(os.environ.get("WANGP_MODEL_DIR", "/workspace/wan2gp/models")),
        Path(os.environ.get("HF_HOME", "/workspace/cache/huggingface")),
    ]
    stall_seconds = float(os.environ.get("WANGP_DOWNLOAD_STALL_SECONDS", "90"))
    interval = max(0.25, float(os.environ.get("WANGP_DOWNLOAD_SAMPLE_SECONDS", "2")))
    telemetry = DownloadTelemetry(
        roots,
        pid=os.getpid(),
        stall_seconds=stall_seconds,
    )
    stop = threading.Event()

    def observe() -> None:
        last_stalled = False
        while not stop.wait(interval):
            sample: dict[str, object] = {**telemetry.sample()}
            stalled = bool(sample["stalled"])
            sample["status"] = "progress"
            sample["message"] = (
                f"No model download activity for {sample['seconds_since_activity']} seconds"
                if stalled
                else "Preparing WanGP model"
            )
            emitter.send(sample)
            last_stalled = stalled
        if last_stalled:
            # A final non-stalled completion frame below clears the warning.
            return

    emitter.send(
        {
            "status": "progress",
            **telemetry.sample(),
            "message": "Resolving WanGP model files",
        }
    )
    observer = threading.Thread(target=observe, name="download-telemetry", daemon=True)
    observer.start()
    try:
        # WanGP writes human-readable status to stdout. Keep stdout dedicated to
        # the adapter protocol without changing any upstream code.
        with contextlib.redirect_stdout(sys.stderr):
            from shared.api import init

            session = init(
                root=str(wangp_root),
                config_path=os.environ.get("WANGP_CONFIG_PATH"),
                output_dir=os.environ.get("WANGP_OUTPUT_DIR"),
                console_output=True,
                console_isatty=False,
            )
            session.ensure_ready()
            runtime = session._ensure_runtime()
            with contextlib.chdir(runtime.root):
                _prepare(runtime, model_type)
            availability = session.get_model_availability(model_type)
    finally:
        stop.set()
        observer.join(timeout=interval + 1)
        os.environ.pop("HF_TOKEN", None)

    emitter.send(
        {
            "status": "completed",
            **telemetry.sample(),
            "current_files": [],
            "stalled": False,
            "message": "WanGP model files are ready",
            "availability": availability,
        }
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"WanGP model preparation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
