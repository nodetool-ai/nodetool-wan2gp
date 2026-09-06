"""The passthrough node for any Wan2GP model and any setting."""

from __future__ import annotations

from typing import Any

from nodetool.metadata.types import ImageRef, VideoRef
from nodetool.workflows.processing_context import ProcessingContext
from pydantic import Field

from ._base import _Wan2GPNode
from ._client import Wan2GPClient
from ._settings import merged_settings


class Generate(_Wan2GPNode):
    """
    Runs any model on your own Wan2GP server with the settings you supply.
    video, generation, diffusion, Wan, Wan2GP, advanced, local

    This node starts from the model's own generation defaults, applies your
    settings on top, and returns the first output. Use it for models and
    settings that the TextToVideo and ImageToVideo nodes do not cover. The
    wangp_models and wangp_model tools on your server list the model ids and
    their settings.

    Use cases:
    - Drive a model that this package has no dedicated node for
    - Set guidance scale, flow shift, sliding windows or other expert settings
    - Reproduce a settings file exported from the Wan2GP web UI
    - Run a video-to-video or control-guided generation
    - Try a new Wan2GP release before this package catches up
    """

    model_type: str = Field(
        default="t2v_2_2",
        description="Wan2GP model id to run. Call the wangp_models tool on your server for the ids it offers.",
    )
    settings: dict[str, Any] = Field(
        default={},
        description="Wan2GP generation settings, applied on top of the model defaults. Keys such as prompt, resolution, video_length, num_inference_steps and guidance_scale. The reserved _api key is removed.",
    )
    image: ImageRef | None = Field(
        default=None,
        description="Optional starting image. It is uploaded to the Wan2GP gallery and passed as image_start.",
    )
    video: VideoRef | None = Field(
        default=None,
        description="Optional guide video. It is uploaded to the Wan2GP gallery and passed as video_guide.",
    )

    @classmethod
    def get_basic_fields(cls) -> list[str]:
        return ["model_type", "settings"]

    async def build_settings(
        self, context: ProcessingContext, client: Wan2GPClient
    ) -> dict[str, Any]:
        """Merge the model defaults, the node fields and the user settings."""
        defaults = await client.get_model_defaults(self.model_type)
        media: dict[str, Any] = {}
        if self.image is not None and not self.image.is_empty():
            media["image_start"] = await self.upload_image(context, client, self.image)
        if self.video is not None and not self.video.is_empty():
            media["video_guide"] = await self.upload_video(context, client, self.video)
        return merged_settings(
            defaults=defaults,
            model_type=self.model_type,
            seed=self.seed,
            user_settings=self.settings,
            media=media,
        )

    async def process(self, context: ProcessingContext) -> VideoRef:
        async def build(client: Wan2GPClient) -> dict[str, Any]:
            return await self.build_settings(context, client)

        return await self.run_generation(context, build)
