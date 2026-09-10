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
                json.dumps({"type": event_type, "data": data}, separators=(",", ":"))
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


def _choice_values(definition: Any) -> list[str]:
    if not isinstance(definition, dict):
        return []
    values: list[str] = []
    for choice in definition.get("choices", []):
        value = (
            choice.get("value")
            if isinstance(choice, dict)
            else choice[1]
            if isinstance(choice, (list, tuple)) and len(choice) > 1
            else choice
        )
        if value is not None and str(value):
            values.append(str(value))
    for value in definition.get("selection", []):
        if value is not None and str(value):
            values.append(str(value))
    return values


def _setting_definition(metadata: dict[str, Any] | None, name: str) -> Any:
    values = (metadata or {}).get("setting_values", {})
    if not isinstance(values, dict):
        return None
    direct = values.get(name)
    if direct is not None:
        return direct
    video = values.get("video_prompt_type")
    return video.get(name) if isinstance(video, dict) else None


def _media_roles(metadata: dict[str, Any] | None, kind: str) -> dict[str, Any]:
    media = (metadata or {}).get("media_inputs", {})
    roles = media.get(kind, {}) if isinstance(media, dict) else {}
    return roles if isinstance(roles, dict) else {}


def _reference_modes(metadata: dict[str, Any] | None) -> list[str]:
    image_modes = _choice_values(_setting_definition(metadata, "image_ref_choices"))
    image_modes += _choice_values(_setting_definition(metadata, "guide_custom_choices"))
    return [value for value in image_modes if "I" in value]


def _video_reference_modes(metadata: dict[str, Any] | None) -> list[str]:
    # WanGP's guide choices are authoritative. H3 declares V-U and V+-U for
    # one and two reference videos. GV is generic control video and excluded.
    values = _choice_values(_setting_definition(metadata, "guide_custom_choices"))
    return [value for value in values if value in {"V-U", "V+-U"}]


def _audio_video_modes(metadata: dict[str, Any] | None) -> list[str]:
    audio = (metadata or {}).get("setting_values", {}).get("audio_prompt_type", {})
    definition = audio.get("sources") if isinstance(audio, dict) else None
    values = _choice_values(definition)
    return [value for value in values if "K" in value]


def _combine_prompt_modes(*modes: str) -> str:
    result = ""
    for mode in modes:
        for flag in mode:
            if flag not in result:
                result += flag
    return result


def _supports_reference_video(metadata: dict[str, Any] | None) -> bool:
    if not metadata:
        return False
    image_roles = _media_roles(metadata, "image")
    video_roles = _media_roles(metadata, "video")
    image_support = bool(
        (
            image_roles.get("reference")
            or image_roles.get("multiple_references")
            or image_roles.get("single_reference")
        )
        and _reference_modes(metadata)
    )
    video_support = bool(
        video_roles.get("control") and _video_reference_modes(metadata)
    )
    return bool(image_support or video_support)


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
            if model_kind == "video" and _supports_reference_video(metadata):
                supported.append("reference_to_video")
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
            base_model_type = str(metadata.get("base_model_type") or model_type)
            tts_capabilities = list(supported)
            media_inputs = metadata.get("media_inputs")
            audio_inputs = (
                media_inputs.get("audio", {}) if isinstance(media_inputs, dict) else {}
            )
            if audio_inputs.get("prompt"):
                tts_capabilities.append("voice_cloning")
            if base_model_type in {"qwen3_tts_base", "omnivoice"}:
                tts_capabilities.append("reference_transcript")
            if base_model_type in {
                "qwen3_tts_customvoice",
                "index_tts2",
                "index_tts25",
            }:
                tts_capabilities.append("instruction_control")
            if base_model_type in {"qwen3_tts_voicedesign", "omnivoice"}:
                tts_capabilities.append("voice_design")

            setting_values = metadata.get("setting_values")
            model_mode = (
                setting_values.get("model_mode")
                if isinstance(setting_values, dict)
                else None
            )
            mode_label = str(
                model_mode.get("label", "") if isinstance(model_mode, dict) else ""
            ).casefold()
            mode_values = _choice_values(model_mode)
            if mode_label == "speaker":
                tts_capabilities.append("preset_voice")
                model["voices"] = mode_values
            elif mode_label == "language":
                tts_capabilities.append("language_selection")
                model["languages"] = mode_values
            model["capabilities"] = list(dict.fromkeys(tts_capabilities))
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
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"{request.get('operation')} requires a readable {name}")
    return path


def _setting_choice_with_flag(
    metadata: dict[str, Any] | None, setting: str, flag: str
) -> str:
    choice_def = _setting_definition(metadata, setting)
    for choice in choice_def.get("choices", []) if isinstance(choice_def, dict) else []:
        value = (
            choice.get("value", "")
            if isinstance(choice, dict)
            else choice[1]
            if isinstance(choice, (list, tuple)) and len(choice) > 1
            else choice
        )
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

    if operation in {"text_to_image", "image_to_image"}:
        settings["image_mode"] = 1

    if operation in {"image_to_image", "image_to_video"}:
        if operation == "image_to_video" and metadata is not None:
            capabilities = metadata.get("capabilities", {})
            image_roles = _media_roles(metadata, "image")
            if not capabilities.get("image_to_video") or not image_roles.get("start"):
                raise ValueError(f"Model {model_type} does not support image_to_video")
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

    if operation == "reference_to_video":
        if (
            metadata is None
            or str(metadata.get("model_type") or model_type) != model_type
        ):
            raise ValueError(f"Unknown WanGP model: {model_type}")
        if not _supports_reference_video(metadata):
            raise ValueError(f"Model {model_type} does not support reference_to_video")
        raw_image_paths = request.get("reference_image_paths", [])
        raw_video_paths = request.get("reference_video_paths", [])
        if not isinstance(raw_image_paths, list) or not isinstance(
            raw_video_paths, list
        ):
            raise ValueError("reference media paths must be arrays")
        image_paths = [Path(str(path)).resolve() for path in raw_image_paths]
        video_paths = [Path(str(path)).resolve() for path in raw_video_paths]
        if any(
            not path.is_file() or path.stat().st_size == 0
            for path in image_paths + video_paths
        ):
            raise ValueError(
                "reference_to_video requires readable reference media paths"
            )
        if not image_paths and not video_paths:
            raise ValueError(
                "reference_to_video requires at least one reference image or video"
            )
        if len(video_paths) > 2:
            raise ValueError("reference_to_video supports at most two reference videos")
        image_roles = _media_roles(metadata, "image")
        if image_roles.get("single_reference") and len(image_paths) > 1:
            raise ValueError(
                "reference_to_video model accepts only one reference image"
            )
        if image_paths and not _reference_modes(metadata):
            raise ValueError(
                "reference_to_video model does not accept reference images"
            )
        if video_paths and not _media_roles(metadata, "video").get("control"):
            raise ValueError(
                "reference_to_video model does not accept reference videos"
            )
        if image_paths:
            settings["image_refs"] = [str(path) for path in image_paths]
            image_mode = _reference_modes(metadata)[0]
            settings["video_prompt_type"] = image_mode
        if video_paths:
            video_modes = _video_reference_modes(metadata)
            mode = next(
                (
                    value
                    for value in video_modes
                    if value == ("V+-U" if len(video_paths) == 2 else "V-U")
                ),
                None,
            )
            if mode is None:
                raise ValueError(
                    "reference_to_video video count has no advertised WanGP mode"
                )
            image_mode = settings.get("video_prompt_type")
            settings["video_prompt_type"] = _combine_prompt_modes(
                str(image_mode or ""), mode
            )
            settings["video_guide"] = str(video_paths[0])
            if len(video_paths) == 2:
                settings["video_guide2"] = str(video_paths[1])
        if params.get("useReferenceVideoAudio"):
            if not video_paths:
                raise ValueError(
                    "reference video audio requires at least one reference video"
                )
            audio_modes = _audio_video_modes(metadata)
            if not audio_modes:
                raise ValueError("reference video audio is not supported by this model")
            settings["audio_prompt_type"] = audio_modes[0]

    if operation == "text_to_audio":
        style_prompt = str(params.get("prompt") or "")
        lyrics = str(params.get("lyrics") or "").strip()
        base_model_type = str((metadata or {}).get("base_model_type") or model_type)
        if base_model_type.startswith("stable_audio3"):
            settings["prompt"] = style_prompt
        else:
            settings["prompt"] = lyrics or "[Instrumental]"
            settings["alt_prompt"] = style_prompt
        if params.get("durationSeconds") is not None:
            settings["duration_seconds"] = float(params["durationSeconds"])

    if operation == "tts_encoded":
        if params.get("referenceText") is not None:
            settings["alt_prompt"] = str(params["referenceText"])
        elif params.get("instructions") is not None:
            settings["alt_prompt"] = str(params["instructions"])
        base_model_type = str((metadata or {}).get("base_model_type") or model_type)
        model_mode = (
            params.get("voice")
            if base_model_type == "qwen3_tts_customvoice"
            else params.get("language")
        )
        if model_mode:
            settings["model_mode"] = str(model_mode)
        if params.get("speed") is not None and base_model_type == "index_tts25":
            settings["custom_settings"] = {"speech_speed": float(params["speed"])}
        if request.get("reference_audio_path"):
            settings["audio_guide"] = str(_input_path(request, "reference_audio_path"))
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
    media_suffixes = {
        "image": {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"},
        "video": {".avi", ".mkv", ".mov", ".mp4", ".webm"},
        "audio": {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav"},
    }
    expected_suffixes = media_suffixes.get(media_type or "")
    for path in getattr(result, "generated_files", ()):
        candidate = Path(str(path))
        if candidate.is_file() and (
            expected_suffixes is None
            or candidate.suffix.casefold() in expected_suffixes
        ):
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
            "reference_to_video": "video",
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
