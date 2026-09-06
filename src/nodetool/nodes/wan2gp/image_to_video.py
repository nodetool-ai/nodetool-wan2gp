"""The image-to-video node."""

from __future__ import annotations

from typing import Any

from nodetool.metadata.types import ImageRef, VideoRef
from nodetool.workflows.processing_context import ProcessingContext
from pydantic import Field

from ._base import _Wan2GPNode
from ._client import Wan2GPClient
from ._settings import video_settings


class ImageToVideo(_Wan2GPNode):
    """
    Animates a still image with a Wan image-to-video model on your own Wan2GP server.
    video, generation, image-to-video, diffusion, Wan, Wan2GP, animation, local

    Wan2GP runs Wan 2.1 and Wan 2.2 image-to-video models on consumer GPUs. This
    node uploads the image to the server's gallery, uses it as the first frame,
    and returns the finished clip. The prompt describes the motion.

    Use cases:
    - Animate a photograph or a piece of artwork
    - Add camera movement to a product shot
    - Continue a rendered still into a moving shot
    - Make a short social clip from a single frame
    - Test motion prompts against one fixed starting image
    """

    image: ImageRef = Field(
        default=ImageRef(),
        description="The image to use as the first frame of the video.",
    )
    prompt: str = Field(
        default="The camera slowly pushes in as the scene comes to life.",
        description="Text description of how the image should move.",
    )
    negative_prompt: str = Field(
        default="",
        description="Text description of what to keep out of the video. Leave empty to use the model default.",
    )
    model_type: str = Field(
        default="i2v_2_2",
        description="Wan2GP model id, for example i2v_2_2 for Wan2.2 Image2video 14B. Call the wangp_models tool on your server for the ids it offers.",
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
        return ["image", "prompt", "model_type", "width", "height", "num_frames"]

    def build_settings(self, image_start: str) -> dict[str, Any]:
        """Return the settings dict this node sends to ``wangp_generate``.

        ``image_start`` is the gallery media id of the uploaded image. Wan2GP
        rejects filesystem paths, so the image always goes through the gallery.
        """
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
            image_start=image_start,
        )

    async def process(self, context: ProcessingContext) -> VideoRef:
        if self.image.is_empty():
            raise ValueError("ImageToVideo needs a starting image.")

        async def build(client: Wan2GPClient) -> dict[str, Any]:
            media_id = await self.upload_image(context, client, self.image)
            return self.build_settings(media_id)

        return await self.run_generation(context, build)
