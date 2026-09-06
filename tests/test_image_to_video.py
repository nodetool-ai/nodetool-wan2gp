"""Tests for the ImageToVideo node, run against the in-process fake server."""

from __future__ import annotations

import pytest
from nodetool.metadata.types import ImageRef, VideoRef

from nodetool.nodes.wan2gp.image_to_video import ImageToVideo

from conftest import FakeWan2GP, fixture_bytes, progress_messages


def a_node(server_url: str, **fields) -> ImageToVideo:
    fields.setdefault("image", ImageRef(data=fixture_bytes("tiny.png")))
    node = ImageToVideo(server_url=server_url, **fields)
    node._id = "iv1"
    return node


async def test_process_returns_the_generated_video(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    video = await a_node(server_url).process(context)

    assert isinstance(video, VideoRef)
    assert video.data == fixture_bytes("tiny.mp4")


async def test_process_uploads_the_image_before_it_generates(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    await a_node(server_url).process(context)

    assert fake_server.args_for("wangp_create_gallery_upload") == [
        {"filename": "image.png"}
    ]
    assert list(fake_server.uploads.values()) == [fixture_bytes("tiny.png")]
    called = [call["name"] for call in fake_server.tool_calls]
    assert called.index("wangp_create_gallery_upload") < called.index("wangp_generate")


async def test_process_sends_the_expected_settings(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    node = a_node(
        server_url,
        prompt="the camera pushes in",
        negative_prompt="blurry",
        width=512,
        height=288,
        num_frames=17,
        fps=24,
        num_inference_steps=4,
        seed=7,
        loras=["speed.safetensors"],
        lora_multipliers=[0.8],
    )
    await node.process(context)

    assert fake_server.args_for("wangp_generate") == [
        {
            "source": {
                "model_type": "i2v_2_2",
                "prompt": "the camera pushes in",
                "negative_prompt": "blurry",
                "resolution": "512x288",
                "video_length": 17,
                "force_fps": 24,
                "num_inference_steps": 4,
                "seed": 7,
                "image_start": "visual:0a1b2c3d4e5f",
                "image_prompt_type": "S",
                "activated_loras": ["speed.safetensors"],
                "loras_multipliers": "0.8",
            },
            "wait": False,
        }
    ]


async def test_process_never_sends_a_filesystem_path(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    await a_node(server_url).process(context)

    image_start = fake_server.args_for("wangp_generate")[0]["source"]["image_start"]
    assert image_start.startswith("visual:")


async def test_process_posts_progress(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    await a_node(server_url).process(context)

    progress = progress_messages(context)
    assert [(m.progress, m.total) for m in progress] == [(30, 30)]
    assert progress[0].node_id == "iv1"


async def test_process_picks_the_extension_from_the_image_bytes(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 32
    await a_node(server_url, image=ImageRef(data=jpeg)).process(context)

    assert fake_server.args_for("wangp_create_gallery_upload") == [
        {"filename": "image.jpg"}
    ]


async def test_an_empty_image_is_rejected_before_any_call(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    with pytest.raises(ValueError, match="needs a starting image"):
        await ImageToVideo(server_url=server_url).process(context)

    assert fake_server.tool_calls == []


def test_the_node_is_not_cacheable_and_needs_no_gpu():
    assert ImageToVideo.is_cacheable() is False
    assert ImageToVideo().requires_gpu() is False
    assert ImageToVideo.is_visible() is True
    assert ImageToVideo.get_node_type() == "wan2gp.image_to_video.ImageToVideo"
