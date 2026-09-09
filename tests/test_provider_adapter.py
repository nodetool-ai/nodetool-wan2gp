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
    _settings,
    _video_models,
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

    assert _video_models(session) == [
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


def test_generated_path_requires_successful_existing_file(tmp_path: Path) -> None:
    video = tmp_path / "output.mp4"
    video.write_bytes(b"video")
    result = SimpleNamespace(success=True, generated_files=[str(video)], artifacts=[])
    assert _generated_path(result) == str(video.resolve())

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
