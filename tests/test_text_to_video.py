"""Tests for the TextToVideo node, run against the in-process fake server."""

from __future__ import annotations

import pytest
from nodetool.metadata.types import VideoRef
from nodetool.workflows.processing_context import NodeCancelledError, ProcessingContext

from nodetool.nodes.wan2gp.text_to_video import TextToVideo

from conftest import FakeWan2GP, fixture, fixture_bytes, progress_messages


class CancellingContext(ProcessingContext):
    """A context that reports a cancel request after the first poll."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.cancelled = False

    @property
    def is_cancelled(self) -> bool:
        was = self.cancelled
        self.cancelled = True
        return was


def a_node(server_url: str, **fields) -> TextToVideo:
    node = TextToVideo(server_url=server_url, **fields)
    node._id = "tv1"
    return node


async def test_process_returns_the_generated_video(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    video = await a_node(server_url).process(context)

    assert isinstance(video, VideoRef)
    assert video.data == fixture_bytes("tiny.mp4")


async def test_process_sends_the_expected_settings(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    node = a_node(
        server_url,
        prompt="a kite over a lake",
        negative_prompt="blurry",
        width=512,
        height=288,
        num_frames=17,
        fps=24,
        num_inference_steps=4,
        seed=7,
    )
    await node.process(context)

    assert fake_server.args_for("wangp_generate") == [
        {
            "source": {
                "model_type": "t2v_2_2",
                "prompt": "a kite over a lake",
                "negative_prompt": "blurry",
                "resolution": "512x288",
                "video_length": 17,
                "force_fps": 24,
                "num_inference_steps": 4,
                "seed": 7,
            },
            "wait": False,
        }
    ]


async def test_process_posts_progress(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    fake_server.job_snapshots = [
        fixture("job_submitted"),
        fixture("job_running"),
        fixture("job_done"),
    ]

    await a_node(server_url).process(context)

    progress = progress_messages(context)
    assert [(m.progress, m.total) for m in progress] == [(12, 30), (30, 30)]
    assert {m.node_id for m in progress} == {"tv1"}


async def test_process_falls_back_to_the_percentage_without_steps(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    running = fixture("job_running")
    running["events"][1]["data"]["current_step"] = None
    running["events"][1]["data"]["total_steps"] = None
    fake_server.job_snapshots = [running, fixture("job_done")]

    await a_node(server_url).process(context)

    progress = progress_messages(context)
    assert (progress[0].progress, progress[0].total) == (40, 100)


async def test_process_downloads_the_first_gallery_item(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    done = fixture("job_done")
    items = done["result"]["gallery_items"]
    items.append({**items[0], "media_id": "visual:second", "filename": "clip_002.mp4"})
    fake_server.job_snapshots = [done]

    await a_node(server_url).process(context)

    assert fake_server.args_for("wangp_create_gallery_download") == [
        {"media_id": "visual:9f8e7d6c5b4a"}
    ]


async def test_a_failed_job_raises_with_the_server_message(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    fake_server.job_snapshots = [fixture("job_failed")]

    with pytest.raises(ValueError, match=r"CUDA out of memory \(stage: denoising\)"):
        await a_node(server_url).process(context)


async def test_a_job_without_gallery_items_raises(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    done = fixture("job_done")
    done["result"]["gallery_items"] = []
    fake_server.job_snapshots = [done]

    with pytest.raises(ValueError, match="no media in its gallery"):
        await a_node(server_url).process(context)


async def test_cancellation_cancels_the_wan2gp_job(
    server_url, tmp_path, wan2gp_nodes, fake_server: FakeWan2GP
):
    fake_server.job_snapshots = [fixture("job_running")]
    cancelling = CancellingContext(workspace_dir=str(tmp_path))

    with pytest.raises(NodeCancelledError):
        await a_node(server_url).process(cancelling)

    assert fake_server.cancelled_jobs == ["3d9a1c0e5b7f4a2d8c6e0f1a2b3c4d5e"]


async def test_an_off_grid_resolution_never_reaches_the_server(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    with pytest.raises(ValueError, match="multiple of 16"):
        await a_node(server_url, width=500).process(context)

    assert fake_server.args_for("wangp_generate") == []


async def test_the_node_is_not_cacheable_and_needs_no_gpu():
    assert TextToVideo.is_cacheable() is False
    assert TextToVideo().requires_gpu() is False
    assert TextToVideo.is_visible() is True
    assert TextToVideo.get_node_type() == "wan2gp.text_to_video.TextToVideo"
