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


_MODEL_TASKS = {
    "video": ("text_to_video", "image_to_video"),
    "image": ("text_to_image", "image_to_image"),
}


def _is_music(metadata: dict[str, Any]) -> bool:
    return str(metadata.get("family") or "").casefold() == "music"


def _models(session: Any, model_kind: str) -> list[dict[str, Any]]:
    """Translate WanGP model metadata into NodeTool provider models."""
    if model_kind not in {"video", "image", "tts", "music"}:
        return []
    models: list[dict[str, Any]] = []
    for metadata in session.list_model_metadata():
        outputs = metadata.get("main_output", metadata.get("outputs", []))
        expected_output = "audio" if model_kind in {"tts", "music"} else model_kind
        if expected_output not in outputs:
            continue
        if model_kind == "music" and not _is_music(metadata):
            continue
        if model_kind == "tts" and _is_music(metadata):
            continue
        capabilities = metadata.get("capabilities", {})
        if model_kind in _MODEL_TASKS:
            supported = [
                task for task in _MODEL_TASKS[model_kind] if capabilities.get(task)
            ]
        elif model_kind == "music":
            supported = ["text_to_music"] if capabilities.get("text_to_audio") else []
        else:
            supported = ["text_to_speech"] if capabilities.get("text_to_audio") else []
        if not supported:
            continue
        model_type = str(metadata.get("model_type") or "").strip()
        if not model_type:
            continue
        model = {
            "id": model_type,
            "name": str(metadata.get("name") or model_type),
            "provider": "wangp",
        }
        if model_kind == "tts":
            model["capabilities"] = supported
        else:
            model["supportedTasks"] = supported
        models.append(model)
    return models


def _model_id(request: dict[str, Any]) -> str:
    params = request.get("params")
    if not isinstance(params, dict):
        raise ValueError("Provider generation requires params")
    model = params.get("model")
    if isinstance(model, dict):
        model = model.get("id")
    model_type = str(model or "").strip()
    if not model_type:
        raise ValueError("Provider generation requires a model id")
    return model_type


def _input_path(request: dict[str, Any], name: str) -> Path:
    path = Path(str(request.get(name) or "")).resolve()
    if not path.is_file():
        raise ValueError(f"{request.get('operation')} requires a readable {name}")
    return path


def _setting_choice_with_flag(
    metadata: dict[str, Any] | None, setting: str, flag: str
) -> str:
    definitions = (metadata or {}).get("setting_values", {}).get(
        "video_prompt_type", {}
    )
    choice_def = definitions.get(setting)
    if not isinstance(choice_def, dict):
        return ""
    for choice in choice_def.get("choices", []):
        value = choice.get("value", "") if isinstance(choice, dict) else ""
        if flag in str(value):
            return str(value)
    return ""


def _settings(
    request: dict[str, Any], metadata: dict[str, Any] | None = None
) -> dict[str, Any]:
    params = request["params"]
    operation = str(request.get("operation") or "")
    model_type = _model_id(request)

    settings: dict[str, Any] = {
        "model_type": model_type,
        "prompt": str(params.get("text") or params.get("prompt") or ""),
    }
    mappings = {
        "negativePrompt": "negative_prompt",
        "resolution": "resolution",
        "guidanceScale": "guidance_scale",
        "numInferenceSteps": "num_inference_steps",
        "seed": "seed",
        "fps": "force_fps",
        "scheduler": "sample_solver",
        "strength": "denoising_strength",
    }
    for source, target in mappings.items():
        value = params.get(source)
        if value is not None:
            settings[target] = value
    if "resolution" not in settings:
        width = params.get("width", params.get("targetWidth"))
        height = params.get("height", params.get("targetHeight"))
        if width is not None and height is not None:
            settings["resolution"] = f"{int(width)}x{int(height)}"
    if params.get("numFrames") is not None:
        settings["video_length"] = int(params["numFrames"])
    elif params.get("durationSeconds") is not None and operation.endswith("video"):
        settings["video_length"] = f"{float(params['durationSeconds']):g}s"

    if operation in {"image_to_image", "image_to_video"}:
        image_path = str(_input_path(request, "image_path"))
        image_inputs = (metadata or {}).get("media_inputs", {}).get("image", {})
        if image_inputs.get("start") or operation == "image_to_video":
            settings["image_start"] = image_path
            settings["image_prompt_type"] = "S"
        elif image_inputs.get("reference"):
            settings["image_refs"] = [image_path]
        elif image_inputs.get("control"):
            settings["image_guide"] = image_path
            control_mode = _setting_choice_with_flag(
                metadata, "guide_preprocessing", "V"
            ) or _setting_choice_with_flag(metadata, "guide_custom_choices", "V")
            if control_mode:
                settings["video_prompt_type"] = control_mode
        else:
            raise ValueError(f"Model {model_type} does not accept an input image")

    if operation == "text_to_audio":
        style_prompt = str(params.get("prompt") or "")
        lyrics = str(params.get("lyrics") or "").strip()
        settings["prompt"] = lyrics or "[Instrumental]"
        settings["alt_prompt"] = style_prompt
        if params.get("durationSeconds") is not None:
            settings["duration_seconds"] = float(params["durationSeconds"])

    if operation == "tts_encoded":
        if params.get("referenceText") is not None:
            settings["alt_prompt"] = str(params["referenceText"])
        elif params.get("instructions") is not None:
            settings["alt_prompt"] = str(params["instructions"])
        model_mode = params.get("voice") or params.get("language")
        if model_mode:
            settings["model_mode"] = str(model_mode)
        if params.get("speed") is not None:
            settings["speech_speed"] = float(params["speed"])
        if request.get("reference_audio_path"):
            settings["audio_guide"] = str(
                _input_path(request, "reference_audio_path")
            )
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


def _generated_path(result: Any, media_type: str | None = None) -> str:
    if not getattr(result, "success", False):
        errors = getattr(result, "errors", ())
        detail = "; ".join(str(error) for error in errors) or "generation failed"
        raise RuntimeError(detail)
    for artifact in getattr(result, "artifacts", ()):
        if media_type and getattr(artifact, "media_type", None) != media_type:
            continue
        path = getattr(artifact, "path", None)
        if path and Path(path).is_file():
            return str(Path(path).resolve())
    for path in getattr(result, "generated_files", ()):
        candidate = Path(str(path))
        if candidate.is_file():
            return str(candidate.resolve())
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
            models = _models(_session(root), model_type)
            emitter.send("result", {"models": models})
            return 0
        media_type = {
            "text_to_image": "image",
            "image_to_image": "image",
            "text_to_video": "video",
            "image_to_video": "video",
            "text_to_audio": "audio",
            "tts_encoded": "audio",
        }.get(operation)
        if media_type is None:
            raise ValueError(f"Unsupported provider operation: {operation}")
        callbacks = _Callbacks(emitter)
        session = _session(root, callbacks)
        metadata = session.get_model_metadata(_model_id(request))
        result = session.run_task(_settings(request, metadata))
        emitter.send("result", {"path": _generated_path(result, media_type)})
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"WanGP provider adapter failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
