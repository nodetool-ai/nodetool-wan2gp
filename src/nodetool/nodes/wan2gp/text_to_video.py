"""The text-to-video node."""

from __future__ import annotations

from typing import Any

from nodetool.metadata.types import VideoRef
from nodetool.workflows.processing_context import ProcessingContext
from pydantic import Field

from ._base import _Wan2GPNode
from ._client import Wan2GPClient
from ._settings import video_settings


class TextToVideo(_Wan2GPNode):
    """
    Generates a video from a text prompt with a Wan video model on your own Wan2GP server.
    video, generation, text-to-video, diffusion, Wan, Wan2GP, local

    Wan2GP runs Wan 2.1 and Wan 2.2 text-to-video models on consumer GPUs. This
    node sends the prompt and the generation settings to a Wan2GP server you
    start yourself, follows the job, and returns the finished clip.

    Use cases:
    - Turn a written scene description into a short clip
    - Produce b-roll and background footage for an edit
    - Draft storyboard shots before a live shoot
    - Generate looping motion graphics from a style prompt
    - Run repeated prompt variations on local hardware without an API bill
    """

    prompt: str = Field(
        default="A large orange octopus is seen resting on the bottom of the ocean floor.",
        description="Text description of the video to generate.",
    )
    negative_prompt: str = Field(
        default="",
        description="Text description of what to keep out of the video. Leave empty to use the model default.",
    )
    model_type: str = Field(
        default="t2v_2_2",
        description="Wan2GP model id, for example t2v_2_2 for Wan2.2 Text2video 14B. Call the wangp_models tool on your server for the ids it offers.",
    )
    width: int = Field(
        default=832,
        description="Output width in pixels. Must be a multiple of 16.",
    )
    height: int = Field(
        default=480,
        description="Output height in pixels. Must be a multiple of 16.",
    )
    num_frames: int = Field(
        default=81,
        description="Number of frames to generate. Wan2GP rounds this to the nearest count the model allows.",
    )
    fps: int = Field(
        default=16,
        description="Frames per second of the output video.",
    )
    num_inference_steps: int = Field(
        default=30,
        description="Number of denoising steps. More steps give more detail and take longer.",
    )
    loras: list[str] = Field(
        default=[],
        description="LoRA identifiers to activate, as returned by the wangp_list_loras tool.",
    )
    lora_multipliers: list[float] = Field(
        default=[],
        description="Weight for each LoRA, in the same order. Leave empty to use a weight of 1 for each.",
    )

    @classmethod
    def get_basic_fields(cls) -> list[str]:
        return ["prompt", "model_type", "width", "height", "num_frames"]

    def build_settings(self) -> dict[str, Any]:
        """Return the settings dict this node sends to ``wangp_generate``."""
        return video_settings(
            model_type=self.model_type,
            prompt=self.prompt,
            negative_prompt=self.negative_prompt,
            width=self.width,
            height=self.height,
            num_frames=self.num_frames,
            fps=self.fps,
            num_inference_steps=self.num_inference_steps,
            seed=self.seed,
            loras=self.loras,
            lora_multipliers=self.lora_multipliers,
        )

    async def process(self, context: ProcessingContext) -> VideoRef:
        async def build(_client: Wan2GPClient) -> dict[str, Any]:
            return self.build_settings()

        return await self.run_generation(context, build)
