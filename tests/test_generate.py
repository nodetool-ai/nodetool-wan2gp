"""Tests for the Generate passthrough node, run against the fake server."""

from __future__ import annotations

from nodetool.metadata.types import ImageRef, VideoRef

from nodetool.nodes.wan2gp.generate import Generate

from conftest import FakeWan2GP, fixture, fixture_bytes, progress_messages


def a_node(server_url: str, **fields) -> Generate:
    node = Generate(server_url=server_url, **fields)
    node._id = "g1"
    return node


async def test_process_returns_the_generated_video(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    video = await a_node(server_url, settings={"prompt": "a kite"}).process(context)

    assert isinstance(video, VideoRef)
    assert video.data == fixture_bytes("tiny.mp4")


async def test_process_merges_user_settings_over_the_model_defaults(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    node = a_node(
        server_url,
        model_type="t2v_2_2",
        seed=42,
        settings={"prompt": "a kite", "num_inference_steps": 4},
    )
    await node.process(context)

    expected = dict(fixture("model_defaults_t2v_2_2"))
    expected.update(
        {
            "prompt": "a kite",
            "num_inference_steps": 4,
            "seed": 42,
            "model_type": "t2v_2_2",
        }
    )
    assert fake_server.args_for("wangp_generate") == [
        {"source": expected, "wait": False}
    ]
    assert fake_server.args_for("wangp_model") == [
        {"model_type": "t2v_2_2", "view": "defaults"}
    ]


async def test_process_strips_the_api_key(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    node = a_node(server_url, settings={"_api": {"return_media": True}, "prompt": "x"})
    await node.process(context)

    source = fake_server.args_for("wangp_generate")[0]["source"]
    assert "_api" not in source
    assert source["prompt"] == "x"


async def test_process_uploads_an_optional_image_as_image_start(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    node = a_node(
        server_url,
        model_type="i2v_2_2",
        image=ImageRef(data=fixture_bytes("tiny.png")),
    )
    await node.process(context)

    source = fake_server.args_for("wangp_generate")[0]["source"]
    assert source["image_start"] == "visual:0a1b2c3d4e5f"
    assert fake_server.args_for("wangp_create_gallery_upload") == [
        {"filename": "image.png"}
    ]


async def test_process_uploads_an_optional_video_as_video_guide(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    node = a_node(server_url, video=VideoRef(data=fixture_bytes("tiny.mp4")))
    await node.process(context)

    source = fake_server.args_for("wangp_generate")[0]["source"]
    assert source["video_guide"] == "visual:0a1b2c3d4e5f"
    assert fake_server.args_for("wangp_create_gallery_upload") == [
        {"filename": "video.mp4"}
    ]


async def test_process_uploads_nothing_when_no_media_is_connected(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    await a_node(server_url).process(context)

    assert fake_server.args_for("wangp_create_gallery_upload") == []
    source = fake_server.args_for("wangp_generate")[0]["source"]
    assert "image_start" not in source
    assert "video_guide" not in source


async def test_process_posts_progress(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    await a_node(server_url).process(context)

    progress = progress_messages(context)
    assert [(m.progress, m.total) for m in progress] == [(30, 30)]
    assert progress[0].node_id == "g1"


def test_the_node_is_not_cacheable_and_needs_no_gpu():
    assert Generate.is_cacheable() is False
    assert Generate().requires_gpu() is False
    assert Generate.is_visible() is True
    assert Generate.get_node_type() == "wan2gp.generate.Generate"
