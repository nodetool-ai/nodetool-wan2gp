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


REFERENCE_METADATA = json.loads(
    (
        Path(__file__).parent / "fixtures" / "wangp_h3_reference_metadata.json"
    ).read_text()
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
                "base_model_type": "qwen3_tts_base",
                "media_inputs": {"audio": {"prompt": True}},
                "setting_values": {
                    "model_mode": {
                        "label": "Language",
                        "choices": [
                            {"label": "English", "value": "English"},
                            {"label": "Auto", "value": "auto"},
                        ],
                    }
                },
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
            "languages": ["English", "auto"],
            "capabilities": [
                "text_to_speech",
                "voice_cloning",
                "reference_transcript",
                "language_selection",
            ],
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


def test_reference_models_are_discovered_from_pinned_metadata() -> None:
    session = SimpleNamespace(list_model_metadata=lambda: [REFERENCE_METADATA])
    assert _models(session, "video")[0]["supportedTasks"] == [
        "text_to_video",
        "image_to_video",
        "reference_to_video",
    ]

    video_only = dict(REFERENCE_METADATA)
    video_only["model_type"] = "wan2gp_video_ref"
    video_only["media_inputs"] = {"image": {}, "video": {"control": True}}
    video_only["setting_values"] = {
        "video_prompt_type": {
            "guide_custom_choices": {
                "choices": [
                    {"label": "Use One Reference Video", "value": "V-U"},
                    {"label": "Use Two Reference Videos", "value": "V+-U"},
                ]
            }
        }
    }
    assert (
        "reference_to_video"
        in _models(SimpleNamespace(list_model_metadata=lambda: [video_only]), "video")[
            0
        ]["supportedTasks"]
    )


@pytest.mark.parametrize(
    ("images", "videos", "expected"),
    [
        (1, 0, {"image_refs": 1, "video_prompt_type": "I"}),
        (0, 1, {"video_guide": 1, "video_prompt_type": "V-U"}),
        (0, 2, {"video_guide": 1, "video_guide2": 1, "video_prompt_type": "V+-U"}),
        (1, 1, {"image_refs": 1, "video_guide": 1, "video_prompt_type": "IV-U"}),
    ],
)
def test_reference_to_video_maps_each_declared_media_slot(
    tmp_path: Path, images: int, videos: int, expected: dict[str, int | str]
) -> None:
    image_paths = []
    video_paths = []
    for index in range(images):
        path = tmp_path / f"ref{index}.png"
        path.write_bytes(b"image")
        image_paths.append(str(path))
    for index in range(videos):
        path = tmp_path / f"guide{index}.mp4"
        path.write_bytes(b"video")
        video_paths.append(str(path))
    settings = _settings(
        {
            "operation": "reference_to_video",
            "reference_image_paths": image_paths,
            "reference_video_paths": video_paths,
            "params": {
                "model": REFERENCE_METADATA["model_type"],
                "prompt": "keep identity",
            },
        },
        REFERENCE_METADATA,
    )
    for key, value in expected.items():
        if isinstance(value, str):
            assert settings[key] == value
        elif key == "image_refs":
            assert len(settings[key]) == value
        else:
            assert key in settings


def test_reference_audio_requires_video_and_declared_audio_mode(tmp_path: Path) -> None:
    image = tmp_path / "ref.png"
    image.write_bytes(b"image")
    with pytest.raises(ValueError, match="at least one reference video"):
        _settings(
            {
                "operation": "reference_to_video",
                "reference_image_paths": [str(image)],
                "params": {
                    "model": REFERENCE_METADATA["model_type"],
                    "useReferenceVideoAudio": True,
                },
            },
            REFERENCE_METADATA,
        )

    video = tmp_path / "guide.mp4"
    video.write_bytes(b"video")
    enabled = _settings(
        {
            "operation": "reference_to_video",
            "reference_video_paths": [str(video)],
            "params": {
                "model": REFERENCE_METADATA["model_type"],
                "useReferenceVideoAudio": True,
            },
        },
        REFERENCE_METADATA,
    )
    assert enabled["audio_prompt_type"] == "K"
    disabled = _settings(
        {
            "operation": "reference_to_video",
            "reference_video_paths": [str(video)],
            "params": {
                "model": REFERENCE_METADATA["model_type"],
                "useReferenceVideoAudio": False,
            },
        },
        REFERENCE_METADATA,
    )
    assert "audio_prompt_type" not in disabled


def test_reference_to_video_rejects_unsupported_model_and_count_before_submission(
    tmp_path: Path,
) -> None:
    image = tmp_path / "ref.png"
    image.write_bytes(b"image")
    request = {
        "operation": "reference_to_video",
        "reference_image_paths": [str(image)],
        "params": {"model": "missing-model"},
    }
    with pytest.raises(ValueError, match="Unknown WanGP model"):
        _settings(request, None)
    guides = []
    for index in range(3):
        path = tmp_path / f"guide{index}.mp4"
        path.write_bytes(b"video")
        guides.append(str(path))
    with pytest.raises(ValueError, match="at most two"):
        _settings(
            {
                "operation": "reference_to_video",
                "reference_video_paths": guides,
                "params": {"model": REFERENCE_METADATA["model_type"]},
            },
            REFERENCE_METADATA,
        )

    single = dict(REFERENCE_METADATA)
    single["media_inputs"] = {
        "image": {"single_reference": True},
        "video": {"control": True},
    }
    second = tmp_path / "ref2.png"
    second.write_bytes(b"image")
    with pytest.raises(ValueError, match="only one"):
        _settings(
            {
                "operation": "reference_to_video",
                "reference_image_paths": [str(image), str(second)],
                "params": {"model": REFERENCE_METADATA["model_type"]},
            },
            single,
        )


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
    assert settings["image_mode"] == 1


def test_text_to_image_selects_image_output_for_dual_output_models() -> None:
    settings = _settings(
        {
            "operation": "text_to_image",
            "params": {"model": "t2v_2_2", "prompt": "sunrise"},
        }
    )
    assert settings["image_mode"] == 1


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


def test_stable_audio_uses_description_as_its_main_prompt() -> None:
    assert _settings(
        {
            "operation": "text_to_audio",
            "params": {
                "model": "stable_audio3_small",
                "prompt": "soft rain and distant thunder",
                "lyrics": "ignored lyrics",
            },
        },
        {"base_model_type": "stable_audio3_small"},
    ) == {
        "model_type": "stable_audio3_small",
        "prompt": "soft rain and distant thunder",
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
        "audio_guide": str(audio.resolve()),
    }


def test_tts_uses_voice_only_for_custom_voice_and_speed_only_for_index25() -> None:
    custom_voice = _settings(
        {
            "operation": "tts_encoded",
            "params": {
                "model": "qwen3_tts_customvoice",
                "text": "Hello",
                "voice": "Ryan",
                "language": "English",
            },
        },
        {"base_model_type": "qwen3_tts_customvoice"},
    )
    assert custom_voice["model_mode"] == "Ryan"

    index = _settings(
        {
            "operation": "tts_encoded",
            "params": {
                "model": "index_tts25",
                "text": "Hello",
                "voice": "unused",
                "language": "EN",
                "speed": 1.25,
            },
        },
        {"base_model_type": "index_tts25"},
    )
    assert index["model_mode"] == "EN"
    assert index["custom_settings"] == {"speech_speed": 1.25}


def test_generated_path_requires_successful_existing_file(tmp_path: Path) -> None:
    video = tmp_path / "output.mp4"
    video.write_bytes(b"video")
    result = SimpleNamespace(success=True, generated_files=[str(video)], artifacts=[])
    assert _generated_path(result, "video") == str(video.resolve())

    image = tmp_path / "wrong.png"
    image.write_bytes(b"image")
    with pytest.raises(RuntimeError, match="without a generated media file"):
        _generated_path(
            SimpleNamespace(success=True, generated_files=[str(image)], artifacts=[]),
            "video",
        )

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
    callbacks = _Callbacks(
        SimpleNamespace(send=lambda kind, data: events.append((kind, data)))
    )
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


def test_reference_discovery_excludes_control_and_start_only_models() -> None:
    import copy

    control = copy.deepcopy(REFERENCE_METADATA)
    control["media_inputs"]["image"] = {"start": True}
    choices = control["setting_values"]["video_prompt_type"]
    choices["image_ref_choices"] = None
    choices["guide_custom_choices"]["choices"] = [
        {"label": "Generic control", "value": "GV"}
    ]
    assert (
        "reference_to_video"
        not in _models(SimpleNamespace(list_model_metadata=lambda: [control]), "video")[
            0
        ]["supportedTasks"]
    )

    image_only = copy.deepcopy(control)
    image_only["media_inputs"]["image"] = {"reference": True}
    image_only["media_inputs"]["video"] = {}
    image_only["setting_values"]["video_prompt_type"]["guide_custom_choices"][
        "choices"
    ] = [{"label": "Reference", "value": "I"}]
    assert (
        "reference_to_video"
        in _models(SimpleNamespace(list_model_metadata=lambda: [image_only]), "video")[
            0
        ]["supportedTasks"]
    )


@pytest.mark.parametrize("field", ["reference_image_paths", "reference_video_paths"])
@pytest.mark.parametrize("value", [None, "not-an-array", 1])
def test_reference_paths_require_arrays(field: str, value: object) -> None:
    with pytest.raises(ValueError, match="must be arrays"):
        _settings(
            {
                "operation": "reference_to_video",
                field: value,
                "params": {"model": REFERENCE_METADATA["model_type"]},
            },
            REFERENCE_METADATA,
        )


def test_reference_rejects_unadvertised_video_and_audio_modes(tmp_path: Path) -> None:
    import copy

    video = tmp_path / "guide.mp4"
    video.write_bytes(b"video")
    request = {
        "operation": "reference_to_video",
        "reference_video_paths": [str(video)],
        "params": {"model": REFERENCE_METADATA["model_type"]},
    }
    metadata = copy.deepcopy(REFERENCE_METADATA)
    metadata["setting_values"]["video_prompt_type"]["guide_custom_choices"][
        "choices"
    ] = [{"value": "V+-U"}]
    with pytest.raises(ValueError, match="video count"):
        _settings(request, metadata)
    metadata = copy.deepcopy(REFERENCE_METADATA)
    metadata["setting_values"]["audio_prompt_type"]["sources"] = None
    request["params"]["useReferenceVideoAudio"] = True
    with pytest.raises(ValueError, match="audio is not supported"):
        _settings(request, metadata)
