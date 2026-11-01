"""The node that lists the models a Wan2GP server offers."""

from __future__ import annotations

from enum import Enum
from typing import Any

from nodetool.workflows.base_node import BaseNode
from nodetool.workflows.processing_context import ProcessingContext
from pydantic import Field

from ._base import SERVER_URL_DEFAULT, open_client

#: The largest page API v2 search returns, and the most rows API v1 returns.
_V2_PAGE_LIMIT = 100
_V1_PAGE_LIMIT = 50

#: The fields each returned row carries.
_ROW_KEYS = ("model_type", "name", "family", "main_output", "outputs", "inputs", "media_inputs", "capabilities")


class OutputKind(str, Enum):
    ANY = ""
    VIDEO = "video"
    IMAGE = "image"
    AUDIO = "audio"
    MODEL_3D = "3d"


class ListModels(BaseNode):
    """
    Lists the models your own Wan2GP server offers, with the media each one accepts.
    models, list, search, Wan, Wan2GP, local

    Each row carries the model_type to put in the Generate, TextToVideo or
    ImageToVideo node, the model's name and family, its outputs, and
    media_inputs: the image, video and audio roles it accepts and any custom
    file it needs. The list comes from the running server, so it includes
    finetunes and models added after this package was released.

    Use cases:
    - Find the model_type for a model you know by name
    - List the video models that take a start or reference image
    - Check which models need a custom file before you build a graph
    - Pick a model for a 3D, image or audio generation
    """

    server_url: str | None = Field(
        default=SERVER_URL_DEFAULT,
        description="URL of the MCP endpoint of your own Wan2GP server. Leave blank to use WAN2GP_MCP_URL, then http://127.0.0.1:7866/mcp.",
    )
    query: str = Field(
        default="",
        description="Text to look for in the model's name, id, family or description. Leave blank to list every model.",
    )
    main_output: OutputKind = Field(
        default=OutputKind.ANY,
        description="Keep only models whose main output is this kind.",
    )
    media_input: str = Field(
        default="",
        description="Keep only models that accept this input kind: image, video, audio, 3d or world.",
    )
    capability: str = Field(
        default="",
        description="Keep only models with this Wan2GP capability, for example image_to_video, reference_images or control_video.",
    )
    limit: int = Field(
        default=50,
        ge=1,
        le=500,
        description="Most models to return.",
    )

    @classmethod
    def get_basic_fields(cls) -> list[str]:
        return ["query", "main_output", "media_input"]

    @classmethod
    def is_cacheable(cls) -> bool:
        return False

    def _filters(self) -> dict[str, Any]:
        filters: dict[str, Any] = {}
        if self.main_output.value:
            filters["main_output"] = self.main_output.value
        if self.media_input.strip():
            filters["inputs"] = self.media_input.strip()
        if self.capability.strip():
            filters["capabilities"] = [self.capability.strip()]
        return filters

    async def process(self, context: ProcessingContext) -> list[dict[str, Any]]:
        async with open_client(self.server_url) as client:
            if client.legacy_api:
                filters = self._filters()
                filters.pop("capabilities", None)
                page = await client.list_models(
                    self.query, filters, limit=min(self.limit, _V1_PAGE_LIMIT)
                )
                return [_row(model) for model in page.get("models") or []][: self.limit]

            rows: list[dict[str, Any]] = []
            cursor: str | None = None
            while len(rows) < self.limit:
                page = await client.list_models(
                    self.query,
                    self._filters(),
                    limit=min(self.limit - len(rows), _V2_PAGE_LIMIT),
                    cursor=cursor,
                )
                for model in page.get("models") or []:
                    if "media_inputs" not in model:
                        # Without a query WanGP returns compact rows.
                        model = await client.get_model_capabilities(str(model["model_type"]))
                    rows.append(_row(model))
                cursor = page.get("next_cursor")
                if not page.get("has_more") or not cursor:
                    break
            return rows[: self.limit]


def _row(model: dict[str, Any]) -> dict[str, Any]:
    return {key: model[key] for key in _ROW_KEYS if key in model}
