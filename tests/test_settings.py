"""Tests for the node field to Wan2GP settings mapping."""

from __future__ import annotations

import pytest

from nodetool.nodes.wan2gp._settings import (
    lora_settings,
    merged_settings,
    resolution_string,
    strip_api,
    video_settings,
)
from nodetool.nodes.wan2gp.generate import Generate
from nodetool.nodes.wan2gp.image_to_video import ImageToVideo
from nodetool.nodes.wan2gp.text_to_video import TextToVideo

from conftest import fixture

TEXT_TO_VIDEO_DEFAULTS = {
    "model_type": "t2v_2_2",
    "prompt": "A large orange octopus is seen resting on the bottom of the ocean floor.",
    "negative_prompt": "",
    "resolution": "832x480",
    "video_length": 81,
    "force_fps": 16,
    "num_inference_steps": 30,
    "seed": -1,
}

IMAGE_TO_VIDEO_DEFAULTS = {
    "model_type": "i2v_2_2",
    "prompt": "The camera slowly pushes in as the scene comes to life.",
    "negative_prompt": "",
    "resolution": "832x480",
    "video_length": 81,
    "force_fps": 16,
    "num_inference_steps": 30,
    "seed": -1,
    "image_start": "visual:0a1b2c3d4e5f",
    "image_prompt_type": "S",
}


def test_resolution_string_joins_the_sides():
    assert resolution_string(832, 480) == "832x480"


@pytest.mark.parametrize("width,height", [(830, 480), (832, 481), (100, 100)])
def test_resolution_rejects_sides_off_the_grid(width, height):
    with pytest.raises(ValueError, match="multiple of 16"):
        resolution_string(width, height)


def test_resolution_names_the_nearest_valid_sizes():
    with pytest.raises(ValueError, match=r"Got 830\. Use 816 or 832\."):
        resolution_string(830, 480)


@pytest.mark.parametrize("width,height", [(0, 480), (832, -16)])
def test_resolution_rejects_non_positive_sides(width, height):
    with pytest.raises(ValueError, match="positive"):
        resolution_string(width, height)


def test_lora_settings_are_absent_without_loras():
    assert lora_settings([], []) == {}


def test_lora_settings_default_every_weight_to_one():
    assert lora_settings(["a.safetensors", "b.safetensors"], []) == {
        "activated_loras": ["a.safetensors", "b.safetensors"],
        "loras_multipliers": "1 1",
    }


def test_lora_settings_join_the_weights_with_spaces():
    assert lora_settings(["a.safetensors", "b.safetensors"], [0.5, 1.25]) == {
        "activated_loras": ["a.safetensors", "b.safetensors"],
        "loras_multipliers": "0.5 1.25",
    }


def test_lora_settings_reject_a_length_mismatch():
    with pytest.raises(ValueError, match="one multiplier per LoRA"):
        lora_settings(["a.safetensors", "b.safetensors"], [0.5])


def test_strip_api_removes_only_the_reserved_key():
    assert strip_api({"_api": {"return_media": True}, "prompt": "hi"}) == {"prompt": "hi"}


def test_text_to_video_defaults_map_to_settings():
    assert TextToVideo().build_settings() == TEXT_TO_VIDEO_DEFAULTS


def test_text_to_video_carries_every_field_through():
    node = TextToVideo(
        prompt="a kite",
        negative_prompt="blurry",
        model_type="t2v",
        width=512,
        height=288,
        num_frames=17,
        fps=24,
        num_inference_steps=4,
        seed=7,
        loras=["speed.safetensors"],
        lora_multipliers=[0.8],
    )
    assert node.build_settings() == {
        "model_type": "t2v",
        "prompt": "a kite",
        "negative_prompt": "blurry",
        "resolution": "512x288",
        "video_length": 17,
        "force_fps": 24,
        "num_inference_steps": 4,
        "seed": 7,
        "activated_loras": ["speed.safetensors"],
        "loras_multipliers": "0.8",
    }


def test_text_to_video_rejects_a_width_off_the_grid():
    with pytest.raises(ValueError, match="multiple of 16"):
        TextToVideo(width=500).build_settings()


def test_text_to_video_rejects_a_lora_length_mismatch():
    with pytest.raises(ValueError, match="one multiplier per LoRA"):
        TextToVideo(loras=["a.safetensors"], lora_multipliers=[1.0, 2.0]).build_settings()


def test_text_to_video_settings_carry_no_image_keys():
    settings = TextToVideo().build_settings()
    assert "image_start" not in settings
    assert "image_prompt_type" not in settings


def test_image_to_video_defaults_map_to_settings():
    assert ImageToVideo().build_settings("visual:0a1b2c3d4e5f") == IMAGE_TO_VIDEO_DEFAULTS


def test_image_to_video_sets_the_start_image_flag():
    settings = ImageToVideo(model_type="i2v", width=512, height=288).build_settings(
        "visual:deadbeef"
    )
    assert settings["image_start"] == "visual:deadbeef"
    assert settings["image_prompt_type"] == "S"
    assert settings["resolution"] == "512x288"


def test_video_settings_place_the_loras_after_the_image_keys():
    settings = video_settings(
        model_type="i2v_2_2",
        prompt="p",
        negative_prompt="",
        width=832,
        height=480,
        num_frames=81,
        fps=16,
        num_inference_steps=30,
        seed=-1,
        loras=["a.safetensors"],
        lora_multipliers=[2.0],
        image_start="visual:1",
    )
    assert settings["activated_loras"] == ["a.safetensors"]
    assert settings["loras_multipliers"] == "2"
    assert settings["image_prompt_type"] == "S"


def test_generate_merges_user_settings_over_the_model_defaults():
    defaults = fixture("model_defaults_t2v_2_2")
    merged = merged_settings(
        defaults=defaults,
        model_type="t2v_2_2",
        seed=99,
        user_settings={"prompt": "a kite", "num_inference_steps": 4},
    )
    assert merged["prompt"] == "a kite"
    assert merged["num_inference_steps"] == 4
    assert merged["seed"] == 99
    assert merged["model_type"] == "t2v_2_2"
    # A default the user did not touch survives.
    assert merged["flow_shift"] == defaults["flow_shift"]
    assert merged["resolution"] == "832x480"


def test_generate_lets_user_settings_override_the_seed():
    merged = merged_settings(
        defaults={},
        model_type="t2v_2_2",
        seed=99,
        user_settings={"seed": 123},
    )
    assert merged["seed"] == 123


def test_generate_strips_the_api_key_from_user_settings():
    merged = merged_settings(
        defaults={"prompt": "d"},
        model_type="t2v_2_2",
        seed=-1,
        user_settings={"_api": {"return_media": True}, "prompt": "u"},
    )
    assert "_api" not in merged
    assert merged["prompt"] == "u"


def test_generate_media_ids_win_over_user_settings():
    merged = merged_settings(
        defaults={},
        model_type="i2v_2_2",
        seed=-1,
        user_settings={"image_start": "/etc/passwd"},
        media={"image_start": "visual:abc"},
    )
    assert merged["image_start"] == "visual:abc"


def test_generate_model_type_field_wins_over_user_settings():
    merged = merged_settings(
        defaults={"model_type": "t2v"},
        model_type="i2v_2_2",
        seed=-1,
        user_settings={"model_type": "something_else"},
    )
    assert merged["model_type"] == "i2v_2_2"


def test_generate_node_defaults():
    node = Generate()
    assert node.model_type == "t2v_2_2"
    assert node.settings == {}
    assert node.image is None
    assert node.video is None
    assert node.get_basic_fields() == ["model_type", "settings"]


def test_basic_fields_of_the_video_nodes():
    assert TextToVideo.get_basic_fields() == [
        "prompt",
        "model_type",
        "width",
        "height",
        "num_frames",
    ]
    assert ImageToVideo.get_basic_fields() == [
        "image",
        "prompt",
        "model_type",
        "width",
        "height",
        "num_frames",
    ]
