"""Tests for the MCP provider adapter, run against the fake server."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from nodetool.nodes.wan2gp._client import Wan2GPError
from nodetool.nodes.wan2gp._provider import run_request

from conftest import FakeWan2GP, fixture, fixture_bytes

SERVER_URL = "http://wan2gp.test/mcp"


async def run(request, client_factory, tmp_path):
    events: list[tuple[str, dict]] = []
    await run_request(
        request,
        lambda kind, data: events.append((kind, data)),
        server_url=SERVER_URL,
        output_dir=tmp_path,
        httpx_client_factory=client_factory,
    )
    return events


def result_of(events):
    results = [data for kind, data in events if kind == "result"]
    assert len(results) == 1
    return results[0]


def capability_rows(*model_types: str) -> list[dict]:
    return [{"status": "done", "models": [
        {"model_type": mt, "name": fixture(f"model_capabilities_{mt}")["metadata"]["name"]}
        for mt in model_types
    ], "has_more": False}]


# -- models -------------------------------------------------------------------


async def test_video_models_carry_the_tasks_their_capabilities_allow(
    client_factory, fake_server: FakeWan2GP, tmp_path
):
    fake_server.model_pages = capability_rows("ti2v_2_2_fastwan", "kiwi_edit")

    events = await run({"operation": "models", "model_type": "video"}, client_factory, tmp_path)

    assert result_of(events) == {"models": [
        {"id": "ti2v_2_2_fastwan", "name": "Wan2.2 TextImage2video FastWan 5B", "provider": "wangp",
         "supportedTasks": ["text_to_video", "image_to_video"]},
        {"id": "kiwi_edit", "name": fixture("model_capabilities_kiwi_edit")["metadata"]["name"],
         "provider": "wangp", "supportedTasks": ["text_to_video", "reference_to_video"]},
    ]}
    search = fake_server.args_for("wangp_models")[0]["arguments"]
    assert search["filters"] == {"main_output": "video"}


async def test_image_models_carry_image_tasks(client_factory, fake_server: FakeWan2GP, tmp_path):
    fake_server.model_pages = capability_rows("flux", "qwen_image_edit_20B")

    events = await run({"operation": "models", "model_type": "image"}, client_factory, tmp_path)

    assert [(m["id"], m["supportedTasks"]) for m in result_of(events)["models"]] == [
        ("flux", ["text_to_image"]),
        ("qwen_image_edit_20B", ["text_to_image", "image_to_image"]),
    ]


@pytest.mark.parametrize("kind", ["language", "tts", "music", "asr"])
async def test_other_model_kinds_are_empty(client_factory, fake_server: FakeWan2GP, tmp_path, kind):
    events = await run({"operation": "models", "model_type": kind}, client_factory, tmp_path)

    assert result_of(events) == {"models": []}
    assert fake_server.args_for("wangp_models") == []


# -- generation -----------------------------------------------------------------


async def test_text_to_video_maps_params_and_returns_the_clip(
    client_factory, fake_server: FakeWan2GP, tmp_path
):
    request = {"operation": "text_to_video", "params": {
        "model": "ti2v_2_2_fastwan", "prompt": "A courtyard. Camera dollies in.",
        "negativePrompt": "blur", "numFrames": 33, "resolution": "720p", "aspectRatio": "9:16",
        "numInferenceSteps": 4, "seed": 7, "guidanceScale": 1.0,
    }}

    events = await run(request, client_factory, tmp_path)

    assert fake_server.args_for("wangp_generate") == [{"settings": {
        "model_type": "ti2v_2_2_fastwan", "prompt": "A courtyard. Camera dollies in.",
        "negative_prompt": "blur", "video_length": 33, "resolution": "720x1280",
        "num_inference_steps": 4, "seed": 7, "guidance_scale": 1.0,
    }, "wait": False}]
    path = result_of(events)["path"]
    assert path.endswith(".mp4") and str(tmp_path) in path
    assert open(path, "rb").read() == fixture_bytes("tiny.mp4")
    assert ("progress", {"phase": "saving", "status": "Saving", "progress": 100,
                         "current_step": 30, "total_steps": 30}) in events


async def test_duration_becomes_seconds_and_width_height_a_resolution(
    client_factory, fake_server: FakeWan2GP, tmp_path
):
    await run({"operation": "text_to_video", "params": {
        "model": {"id": "t2v_2_2"}, "prompt": "x", "duration_seconds": 5, "width": 832, "height": 480,
    }}, client_factory, tmp_path)

    settings = fake_server.args_for("wangp_generate")[0]["settings"]
    assert settings["video_length"] == "5s"
    assert settings["resolution"] == "832x480"


async def test_image_to_video_uploads_the_start_image(
    client_factory, fake_server: FakeWan2GP, tmp_path
):
    image = tmp_path / "input.png"
    image.write_bytes(fixture_bytes("tiny.png"))

    await run({"operation": "image_to_video", "image_path": str(image),
               "params": {"model": "ti2v_2_2_fastwan", "prompt": "x"}}, client_factory, tmp_path)

    settings = fake_server.args_for("wangp_generate")[0]["settings"]
    assert settings["image_start"] == "visual:0a1b2c3d4e5f"
    assert fake_server.upload_bodies == [fixture_bytes("tiny.png")]
    assert fake_server.session_args("create_gallery_upload") == [{"filename": "image.png"}]


async def test_reference_to_video_uploads_ordered_image_refs(
    client_factory, fake_server: FakeWan2GP, tmp_path
):
    paths = []
    for index, data in enumerate((fixture_bytes("tiny.png"), b"\xff\xd8\xff\xe0" + b"\x00" * 16)):
        path = tmp_path / f"reference-image-{index}"
        path.write_bytes(data)
        paths.append(str(path))

    await run({"operation": "reference_to_video", "reference_image_paths": paths, "reference_video_paths": [],
               "params": {"model": "kiwi_edit", "prompt": "x"}}, client_factory, tmp_path)

    settings = fake_server.args_for("wangp_generate")[0]["settings"]
    assert settings["image_refs"] == ["visual:0a1b2c3d4e5f", "visual:0a1b2c3d4e5f"]
    assert [a["filename"] for a in fake_server.session_args("create_gallery_upload")] == ["image.png", "image.jpg"]


async def test_reference_videos_are_refused_before_any_job(
    client_factory, fake_server: FakeWan2GP, tmp_path
):
    video = tmp_path / "reference-video-0.mp4"
    video.write_bytes(fixture_bytes("tiny.mp4"))

    with pytest.raises(Wan2GPError, match="reference videos"):
        await run({"operation": "reference_to_video", "reference_image_paths": [],
                   "reference_video_paths": [str(video)], "params": {"model": "kiwi_edit", "prompt": "x"}},
                  client_factory, tmp_path)
    assert fake_server.args_for("wangp_generate") == []


async def test_text_to_image_asks_for_an_image_and_returns_one(
    client_factory, fake_server: FakeWan2GP, tmp_path
):
    done = fixture("job_done")
    done["result"]["gallery_items"][0].update({"media_type": "image", "filename": "kite.png"})
    fake_server.job_snapshots = [done]
    fake_server.download_payload = fixture_bytes("tiny.png")

    events = await run({"operation": "text_to_image", "params": {"model": "flux", "prompt": "a red kite"}},
                       client_factory, tmp_path)

    assert fake_server.args_for("wangp_generate")[0]["settings"]["image_mode"] == 1
    assert result_of(events)["path"].endswith(".png")


async def test_image_to_image_uses_the_role_the_model_accepts(
    client_factory, fake_server: FakeWan2GP, tmp_path
):
    done = fixture("job_done")
    done["result"]["gallery_items"][0].update({"media_type": "image", "filename": "edit.png"})
    fake_server.job_snapshots = [done]
    image = tmp_path / "input.png"
    image.write_bytes(fixture_bytes("tiny.png"))

    await run({"operation": "image_to_image", "image_path": str(image),
               "params": {"model": "qwen_image_edit_20B", "prompt": "make it blue"}}, client_factory, tmp_path)

    settings = fake_server.args_for("wangp_generate")[0]["settings"]
    assert settings["image_refs"] == ["visual:0a1b2c3d4e5f"]
    assert "image_start" not in settings


async def test_image_to_image_refuses_a_model_without_an_image_input(
    client_factory, fake_server: FakeWan2GP, tmp_path
):
    image = tmp_path / "input.png"
    image.write_bytes(fixture_bytes("tiny.png"))

    with pytest.raises(Wan2GPError, match="flux"):
        await run({"operation": "image_to_image", "image_path": str(image),
                   "params": {"model": "flux", "prompt": "x"}}, client_factory, tmp_path)
    assert fake_server.args_for("wangp_generate") == []


async def test_a_video_request_that_returns_an_image_fails(
    client_factory, fake_server: FakeWan2GP, tmp_path
):
    done = fixture("job_done")
    done["result"]["gallery_items"][0]["media_type"] = "image"
    fake_server.job_snapshots = [done]

    with pytest.raises(Wan2GPError, match="image"):
        await run({"operation": "text_to_video", "params": {"model": "t2v_2_2", "prompt": "x"}},
                  client_factory, tmp_path)
    assert list(tmp_path.iterdir()) == []


async def test_a_failed_job_reports_its_errors(client_factory, fake_server: FakeWan2GP, tmp_path):
    fake_server.job_snapshots = [fixture("job_failed")]

    with pytest.raises(Wan2GPError, match=fixture("job_failed")["result"]["errors"][0]["message"]):
        await run({"operation": "text_to_video", "params": {"model": "t2v_2_2", "prompt": "x"}},
                  client_factory, tmp_path)


async def test_cancelling_the_adapter_cancels_the_remote_job(
    client_factory, fake_server: FakeWan2GP, tmp_path
):
    import asyncio

    fake_server.job_snapshots = [fixture("job_running")]
    task = asyncio.ensure_future(
        run({"operation": "text_to_video", "params": {"model": "t2v_2_2", "prompt": "x"}}, client_factory, tmp_path)
    )
    while not fake_server.session_args("get_job"):
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert fake_server.cancelled_jobs == [fixture("job_submitted")["job_id"]]


@pytest.mark.parametrize("operation", ["tts_encoded", "text_to_audio", "delete_everything"])
async def test_unsupported_operations_are_refused(client_factory, fake_server: FakeWan2GP, tmp_path, operation):
    with pytest.raises(Wan2GPError, match=operation):
        await run({"operation": operation, "params": {"model": "t2v_2_2"}}, client_factory, tmp_path)


def test_the_command_reports_failures_on_stderr_and_keeps_stdout_for_events():
    completed = subprocess.run(
        [sys.executable, "-m", "nodetool.nodes.wan2gp._provider"],
        input=json.dumps({"operation": "delete_everything"}) + "\n",
        capture_output=True,
        text=True,
        env={"WAN2GP_MCP_URL": "http://127.0.0.1:9/mcp", "PATH": ""},
        timeout=60,
    )
    assert completed.returncode == 1
    assert completed.stdout == ""
    assert "delete_everything" in completed.stderr
