"""Build the settings dict that Wan2GP's ``wangp_generate`` accepts.

This module holds no I/O and no node classes, so the mapping from node fields
to Wan2GP settings keys can be tested on its own. The keys and their value
shapes come from docs/wan2gp-contract.md.
"""

from __future__ import annotations

from typing import Any

# Wan2GP's latent grid needs a resolution that is a multiple of this.
RESOLUTION_MULTIPLE = 16

# The image_prompt_type flag that means "start from image_start".
IMAGE_PROMPT_TYPE_START = "S"

# Reserved API metadata, not a generation setting. Stripped from user input.
API_KEY = "_api"


def resolution_string(width: int, height: int) -> str:
    """Return the ``"<width>x<height>"`` string Wan2GP wants.

    Raise ``ValueError`` when a side is not a positive multiple of 16.
    """
    for name, value in (("width", width), ("height", height)):
        if value <= 0:
            raise ValueError(f"Wan2GP needs a positive {name}. Got {value}.")
        if value % RESOLUTION_MULTIPLE:
            lower = value - value % RESOLUTION_MULTIPLE
            upper = lower + RESOLUTION_MULTIPLE
            raise ValueError(
                f"Wan2GP needs a {name} that is a multiple of {RESOLUTION_MULTIPLE}. "
                f"Got {value}. Use {lower or RESOLUTION_MULTIPLE} or {upper}."
            )
    return f"{width}x{height}"


def lora_settings(loras: list[str], multipliers: list[float]) -> dict[str, Any]:
    """Return the ``activated_loras`` and ``loras_multipliers`` settings.

    Wan2GP takes the multipliers as one space separated string. An empty LoRA
    list produces no settings at all, so the model keeps its own defaults.
    """
    if multipliers and len(multipliers) != len(loras):
        raise ValueError(
            f"Wan2GP needs one multiplier per LoRA. Got {len(loras)} LoRAs and "
            f"{len(multipliers)} multipliers."
        )
    if not loras:
        return {}
    weights = multipliers or [1.0] * len(loras)
    return {
        "activated_loras": list(loras),
        "loras_multipliers": " ".join(_format_multiplier(weight) for weight in weights),
    }


def _format_multiplier(weight: float) -> str:
    """Format one LoRA weight the way Wan2GP parses it."""
    text = f"{float(weight):g}"
    return text


def video_settings(
    *,
    model_type: str,
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    num_frames: int,
    fps: int,
    num_inference_steps: int,
    seed: int,
    loras: list[str],
    lora_multipliers: list[float],
    image_start: str | None = None,
) -> dict[str, Any]:
    """Map the text-to-video and image-to-video node fields to settings.

    ``image_start`` is a gallery ``media_id``, never a path. When it is given
    the result also carries ``image_prompt_type`` so Wan2GP starts from that
    image.
    """
    settings: dict[str, Any] = {
        "model_type": model_type,
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "resolution": resolution_string(width, height),
        "video_length": num_frames,
        "force_fps": fps,
        "num_inference_steps": num_inference_steps,
        "seed": seed,
    }
    if image_start is not None:
        settings["image_start"] = image_start
        settings["image_prompt_type"] = IMAGE_PROMPT_TYPE_START
    settings.update(lora_settings(loras, lora_multipliers))
    return settings


def strip_api(settings: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of user settings without the reserved ``_api`` key."""
    return {key: value for key, value in settings.items() if key != API_KEY}


def merged_settings(
    *,
    defaults: dict[str, Any],
    model_type: str,
    seed: int,
    user_settings: dict[str, Any],
    media: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge the passthrough settings of ``Generate`` over the model defaults.

    Precedence, lowest first: the model's own defaults, then ``seed`` from the
    node, then the user's settings dict, then any media ids this node uploaded.
    ``model_type`` is a node field, so it always wins. ``_api`` is removed from
    the user's dict only.
    """
    settings: dict[str, Any] = dict(defaults)
    settings["seed"] = seed
    settings.update(strip_api(user_settings))
    if media:
        settings.update(media)
    settings["model_type"] = model_type
    return settings
