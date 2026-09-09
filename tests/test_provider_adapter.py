import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from combined.provider_adapter import (  # noqa: E402
    _Callbacks,
    _generated_path,
    _models,
    _settings,
)


def test_video_models_exposes_supported_tasks() -> None:
    session = SimpleNamespace(
        list_model_metadata=lambda: [
            {
                "model_type": "t2v",
                "name": "Text model",
                "outputs": ["video"],
                "capabilities": {"text_to_video": True},
            },
            {
                "model_type": "i2v",
                "outputs": ["video"],
                "capabilities": {"image_to_video": True},
            },
            {
                "model_type": "image",
                "outputs": ["image"],
                "capabilities": {"text_to_image": True},
            },
        ]
    )

    assert _models(session, "video") == [
        {
            "id": "t2v",
            "name": "Text model",
            "provider": "wangp",
            "supportedTasks": ["text_to_video"],
        },
        {
            "id": "i2v",
            "name": "i2v",
            "provider": "wangp",
            "supportedTasks": ["image_to_video"],
        },
    ]


def test_models_exposes_image_tts_and_music_separately() -> None:
    session = SimpleNamespace(
        list_model_metadata=lambda: [
            {
                "model_type": "flux2",
                "name": "Flux 2",
                "main_output": ["image"],
                "capabilities": {
                    "text_to_image": True,
                    "image_to_image": True,
                },
            },
            {
                "model_type": "qwen3_tts",
                "name": "Qwen3 TTS",
                "family": "tts",
                "main_output": ["audio"],
                "capabilities": {"text_to_audio": True},
            },
            {
                "model_type": "ace_step",
                "name": "ACE-Step",
                "family": "music",
                "main_output": ["audio"],
                "capabilities": {"text_to_audio": True},
            },
        ]
    )

    assert _models(session, "image") == [
        {
            "id": "flux2",
            "name": "Flux 2",
            "provider": "wangp",
            "supportedTasks": ["text_to_image", "image_to_image"],
        }
    ]
    assert _models(session, "tts") == [
        {
            "id": "qwen3_tts",
            "name": "Qwen3 TTS",
            "provider": "wangp",
            "capabilities": ["text_to_speech"],
        }
    ]
    assert _models(session, "music") == [
        {
            "id": "ace_step",
            "name": "ACE-Step",
            "provider": "wangp",
            "supportedTasks": ["text_to_music"],
        }
    ]


def test_text_to_video_settings_map_provider_fields() -> None:
    assert _settings(
        {
            "operation": "text_to_video",
            "params": {
                "model": "t2v_2_2",
                "prompt": "ocean",
                "negativePrompt": "text",
                "resolution": "832x480",
                "numFrames": 81,
                "numInferenceSteps": 20,
                "guidanceScale": 4.5,
                "seed": 7,
            },
        }
    ) == {
        "model_type": "t2v_2_2",
        "prompt": "ocean",
        "negative_prompt": "text",
        "resolution": "832x480",
        "video_length": 81,
        "num_inference_steps": 20,
        "guidance_scale": 4.5,
        "seed": 7,
    }


def test_image_to_video_settings_use_input_path(tmp_path: Path) -> None:
    image = tmp_path / "input.png"
    image.write_bytes(b"png")
    settings = _settings(
        {
            "operation": "image_to_video",
            "image_path": str(image),
            "params": {
                "model": {"id": "i2v_2_2"},
                "prompt": "move",
                "durationSeconds": 5,
            },
        }
    )
    assert settings["image_start"] == str(image.resolve())
    assert settings["image_prompt_type"] == "S"
    assert settings["video_length"] == "5s"


def test_image_to_image_uses_reference_input_when_required(tmp_path: Path) -> None:
    image = tmp_path / "input.png"
    image.write_bytes(b"png")
    settings = _settings(
        {
            "operation": "image_to_image",
            "image_path": str(image),
            "params": {
                "model": "qwen_image_edit",
                "prompt": "make it blue",
                "targetWidth": 1024,
                "targetHeight": 768,
                "strength": 0.65,
            },
        },
        {"media_inputs": {"image": {"reference": True}}},
    )
    assert settings["image_refs"] == [str(image.resolve())]
    assert settings["resolution"] == "1024x768"
    assert settings["denoising_strength"] == 0.65


def test_image_to_image_uses_model_control_mode(tmp_path: Path) -> None:
    image = tmp_path / "control.png"
    image.write_bytes(b"png")
    settings = _settings(
        {
            "operation": "image_to_image",
            "image_path": str(image),
            "params": {"model": "control-model", "prompt": "restyle"},
        },
        {
            "media_inputs": {"image": {"control": True}},
            "setting_values": {
                "video_prompt_type": {
                    "guide_preprocessing": {
                        "choices": [
                            {"label": "None", "value": ""},
                            {"label": "Control image", "value": "V"},
                        ]
                    }
                }
            },
        },
    )
    assert settings["image_guide"] == str(image.resolve())
    assert settings["video_prompt_type"] == "V"


def test_music_settings_map_lyrics_style_and_duration() -> None:
    assert _settings(
        {
            "operation": "text_to_audio",
            "params": {
                "model": "ace_step_v1_5",
                "prompt": "dreamy synth pop",
                "lyrics": "[Verse]\nHello",
                "durationSeconds": 30,
                "seed": 5,
            },
        }
    ) == {
        "model_type": "ace_step_v1_5",
        "prompt": "[Verse]\nHello",
        "alt_prompt": "dreamy synth pop",
        "duration_seconds": 30.0,
        "seed": 5,
    }


def test_tts_settings_map_voice_clone_fields(tmp_path: Path) -> None:
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"wav")
    assert _settings(
        {
            "operation": "tts_encoded",
            "reference_audio_path": str(audio),
            "params": {
                "model": "qwen3_tts_base",
                "text": "Hello",
                "referenceText": "Reference words",
                "language": "English",
                "speed": 1.1,
            },
        }
    ) == {
        "model_type": "qwen3_tts_base",
        "prompt": "Hello",
        "alt_prompt": "Reference words",
        "model_mode": "English",
        "speech_speed": 1.1,
        "audio_guide": str(audio.resolve()),
    }


def test_generated_path_requires_successful_existing_file(tmp_path: Path) -> None:
    video = tmp_path / "output.mp4"
    video.write_bytes(b"video")
    result = SimpleNamespace(success=True, generated_files=[str(video)], artifacts=[])
    assert _generated_path(result, "video") == str(video.resolve())

    with pytest.raises(RuntimeError, match="denied"):
        _generated_path(
            SimpleNamespace(
                success=False,
                generated_files=[],
                artifacts=[],
                errors=["denied"],
            )
        )


def test_callbacks_emit_serializable_progress() -> None:
    events = []
    callbacks = _Callbacks(SimpleNamespace(send=lambda kind, data: events.append((kind, data))))
    callbacks.on_progress(
        SimpleNamespace(
            phase="denoising",
            status="step 1",
            progress=25,
            current_step=1,
            total_steps=4,
        )
    )
    assert events == [
        (
            "progress",
            {
                "phase": "denoising",
                "status": "step 1",
                "progress": 25,
                "current_step": 1,
                "total_steps": 4,
            },
        )
    ]


def test_adapter_reserves_stdout_for_json_protocol(tmp_path: Path) -> None:
    root = tmp_path / "upstream"
    package = root / "shared"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "api.py").write_text(
        """
import os
os.write(1, b"upstream noise\\n")

class Session:
    def list_model_metadata(self):
        return [{
            "model_type": "t2v",
            "outputs": ["video"],
            "capabilities": {"text_to_video": True},
        }]

def init(**kwargs):
    return Session()
""".strip()
        + "\n"
    )
    adapter = Path(__file__).resolve().parents[1] / "combined" / "provider_adapter.py"
    result = subprocess.run(
        [sys.executable, str(adapter)],
        input=json.dumps(
            {"operation": "models", "provider": "wangp", "model_type": "video"}
        )
        + "\n",
        text=True,
        capture_output=True,
        env={**os.environ, "WANGP_ROOT": str(root)},
        check=True,
    )
    event = json.loads(result.stdout)
    assert event["type"] == "result"
    assert event["data"]["models"][0]["id"] == "t2v"
    assert "upstream noise" in result.stderr
