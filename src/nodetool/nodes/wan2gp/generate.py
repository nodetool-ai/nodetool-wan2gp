"""The passthrough node for any Wan2GP model and any setting."""

from __future__ import annotations

from typing import Any

from nodetool.metadata.types import AssetRef, AudioRef, ImageRef, Model3DRef, VideoRef
from nodetool.workflows.processing_context import ProcessingContext
from pydantic import Field

from ._base import _Wan2GPNode, custom_filename
from ._client import Wan2GPClient
from ._settings import merged_settings


class Generate(_Wan2GPNode):
    """
    Runs any model on your own Wan2GP server with the settings you supply.
    video, generation, diffusion, Wan, Wan2GP, advanced, local

    This node starts from the model's own generation defaults, applies your
    settings on top, and returns the first output: an image, video, audio or
    3D model. Use it for models and settings that the TextToVideo and
    ImageToVideo nodes do not cover. The ListModels node lists the model ids
    your server offers and the media each one accepts.

    Every connected media input is uploaded to the server's gallery and sent
    under the Wan2GP setting named in its description. Wan2GP turns on the
    matching start, end, reference and audio modes itself. Control and mask
    videos also need a video_prompt_type in settings, such as "VA", unless the
    model's defaults already enable them.

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
        description="Optional starting image, sent as image_start.",
    )
    image_end: ImageRef | None = Field(
        default=None,
        description="Optional last frame, sent as image_end. For models whose capabilities list an end image.",
    )
    reference_images: list[ImageRef] = Field(
        default=[],
        description="Optional reference images, sent in order as image_refs. For models that take a subject, style or background reference; some accept only one.",
    )
    video: VideoRef | None = Field(
        default=None,
        description="Optional control or guide video, sent as video_guide.",
    )
    video_mask: VideoRef | None = Field(
        default=None,
        description="Optional mask video for inpainting, sent as video_mask. Needs a control video and a video_prompt_type with A.",
    )
    source_video: VideoRef | None = Field(
        default=None,
        description="Optional video to continue from, sent as video_source.",
    )
    audio: AudioRef | None = Field(
        default=None,
        description="Optional audio that drives the generation, such as speech for lip sync, sent as audio_guide.",
    )
    custom_file: AssetRef | None = Field(
        default=None,
        description="Optional extra input file some models require, sent as custom_guide: a trajectory (.npy) for wanmove, a score (.abc) for yue2, a camera path (.npz) or a mesh for the 3D texturing models.",
    )
    custom_file_name: str = Field(
        default="",
        description="File name of custom_file with its extension, for example trajectory.npy. Leave blank to take it from the file's URI.",
    )

    @classmethod
    def get_basic_fields(cls) -> list[str]:
        return ["model_type", "settings"]

    async def build_settings(
        self, context: ProcessingContext, client: Wan2GPClient
    ) -> dict[str, Any]:
        """Merge the model defaults, the node fields and the user settings."""
        custom_name = (
            custom_filename(self.custom_file, self.custom_file_name)
            if _connected(self.custom_file)
            else None
        )
        defaults = await client.get_model_defaults(self.model_type)
        media: dict[str, Any] = {}
        for key, image in (("image_start", self.image), ("image_end", self.image_end)):
            if _connected(image):
                media[key] = await self.upload_image(context, client, image)
        references = [image for image in self.reference_images if _connected(image)]
        if references:
            media["image_refs"] = [
                await self.upload_image(context, client, image) for image in references
            ]
        for key, video in (
            ("video_guide", self.video),
            ("video_mask", self.video_mask),
            ("video_source", self.source_video),
        ):
            if _connected(video):
                media[key] = await self.upload_video(context, client, video)
        if _connected(self.audio):
            media["audio_guide"] = await self.upload_audio(context, client, self.audio)
        if custom_name is not None:
            media["custom_guide"] = await self.upload_custom_file(
                context, client, self.custom_file, custom_name
            )
            media.update(await self._custom_file_modes(client))
        return merged_settings(
            defaults=defaults,
            model_type=self.model_type,
            seed=self.seed,
            user_settings=self.settings,
            media=media,
        )

    async def _custom_file_modes(self, client: Wan2GPClient) -> dict[str, Any]:
        """Return the modes the model declares for reading its custom file.

        A model's defaults can leave the custom file unused: yue2 starts in
        audio_prompt_type "0" and reads its score only in "1". A mode the user
        set in settings is kept.
        """
        metadata = await client.get_model_capabilities(self.model_type)
        declared = (metadata.get("media_inputs") or {}).get("custom_file") or {}
        return {
            key: declared[key]
            for key in _CUSTOM_FILE_MODES
            if key in declared and key not in self.settings
        }

    async def process(
        self, context: ProcessingContext
    ) -> ImageRef | VideoRef | AudioRef | Model3DRef:
        async def build(client: Wan2GPClient) -> dict[str, Any]:
            return await self.build_settings(context, client)

        return await self.run_generation(context, build)


#: Settings a model's custom_file declaration may name to make the file count.
_CUSTOM_FILE_MODES = ("model_mode", "video_prompt_type", "audio_prompt_type")


def _connected(asset: AssetRef | None) -> bool:
    return asset is not None and not asset.is_empty()
