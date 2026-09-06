"""Tests for the Wan2GP MCP client against the in-process fake server."""

from __future__ import annotations

import pytest

from nodetool.nodes.wan2gp._client import (
    Wan2GPClient,
    Wan2GPError,
    job_error_message,
    media_type_for,
    progress_from_job,
)

from conftest import FakeWan2GP, fixture, fixture_bytes


async def _client(server_url, client_factory) -> Wan2GPClient:
    return await Wan2GPClient(server_url, httpx_client_factory=client_factory).connect()


async def test_handshake_lists_tools(server_url, client_factory, fake_server: FakeWan2GP):
    async with Wan2GPClient(server_url, httpx_client_factory=client_factory) as client:
        names = await client.list_tools()

    assert "wangp_generate" in names
    assert fake_server.requests[0]["rpc_method"] == "initialize"
    assert "notifications/initialized" in [r.get("rpc_method") for r in fake_server.requests]


async def test_list_models_returns_the_registry_page(server_url, client_factory):
    async with Wan2GPClient(server_url, httpx_client_factory=client_factory) as client:
        models = await client.list_models(query="wan", limit=10)

    assert [entry["model_type"] for entry in models["models"]] == [
        "t2v_2_2",
        "i2v_2_2",
        "t2v",
        "i2v",
    ]


async def test_get_model_defaults_uses_the_defaults_view(
    server_url, client_factory, fake_server: FakeWan2GP
):
    async with Wan2GPClient(server_url, httpx_client_factory=client_factory) as client:
        defaults = await client.get_model_defaults("i2v_2_2")

    assert defaults["image_prompt_type"] == "S"
    assert fake_server.args_for("wangp_model") == [
        {"model_type": "i2v_2_2", "view": "defaults"}
    ]


async def test_upload_round_trip_returns_a_media_id(
    server_url, client_factory, fake_server: FakeWan2GP
):
    payload = fixture_bytes("tiny.png")
    async with Wan2GPClient(server_url, httpx_client_factory=client_factory) as client:
        media_id = await client.upload_bytes("start.png", payload)

    assert media_id == "visual:0a1b2c3d4e5f"
    assert list(fake_server.uploads.values()) == [payload]
    assert fake_server.args_for("wangp_create_gallery_upload") == [{"filename": "start.png"}]
    put_requests = [r for r in fake_server.requests if r["method"] == "PUT"]
    assert len(put_requests) == 1
    assert put_requests[0]["path"].startswith("/wangp_api/gallery/upload/")


async def test_upload_rejects_an_unsupported_extension(server_url, client_factory):
    async with Wan2GPClient(server_url, httpx_client_factory=client_factory) as client:
        with pytest.raises(Wan2GPError, match="does not accept the file extension"):
            await client.upload_bytes("notes.txt", b"hello")


async def test_download_round_trip_returns_the_bytes(
    server_url, client_factory, fake_server: FakeWan2GP
):
    async with Wan2GPClient(server_url, httpx_client_factory=client_factory) as client:
        data = await client.download_media("visual:9f8e7d6c5b4a")

    assert data == fixture_bytes("tiny.mp4")
    assert data[4:8] == b"ftyp"
    assert fake_server.args_for("wangp_create_gallery_download") == [
        {"media_id": "visual:9f8e7d6c5b4a"}
    ]


async def test_submit_returns_the_job_id(server_url, client_factory, fake_server: FakeWan2GP):
    settings = {"model_type": "t2v_2_2", "prompt": "an octopus", "resolution": "832x480"}
    async with Wan2GPClient(server_url, httpx_client_factory=client_factory) as client:
        job_id = await client.submit(settings)

    assert job_id == "3d9a1c0e5b7f4a2d8c6e0f1a2b3c4d5e"
    assert fake_server.args_for("wangp_generate") == [{"source": settings, "wait": False}]


async def test_poll_until_done_forwards_progress(
    server_url, client_factory, fake_server: FakeWan2GP
):
    fake_server.job_snapshots = [
        fixture("job_submitted"),
        fixture("job_running"),
        fixture("job_done"),
    ]
    seen: list[dict] = []

    async def no_sleep(_seconds: float) -> None:
        return None

    async with Wan2GPClient(server_url, httpx_client_factory=client_factory) as client:
        job = await client.poll_until_done(
            "3d9a1c0e5b7f4a2d8c6e0f1a2b3c4d5e", on_progress=seen.append, sleep=no_sleep
        )

    assert job["done"] is True
    assert job["result"]["success"] is True
    assert [entry["progress"] for entry in seen] == [40, 100]
    assert [entry["current_step"] for entry in seen] == [12, 30]
    assert len(fake_server.args_for("wangp_get_job")) == 3


async def test_poll_until_done_times_out(server_url, client_factory, fake_server: FakeWan2GP):
    fake_server.job_snapshots = [fixture("job_running")]

    async def no_sleep(_seconds: float) -> None:
        return None

    async with Wan2GPClient(server_url, httpx_client_factory=client_factory) as client:
        with pytest.raises(Wan2GPError, match="did not finish within"):
            await client.poll_until_done("job-1", timeout=0.0, sleep=no_sleep)


async def test_cancel_requests_cancellation(server_url, client_factory, fake_server: FakeWan2GP):
    async with Wan2GPClient(server_url, httpx_client_factory=client_factory) as client:
        job = await client.cancel("3d9a1c0e5b7f4a2d8c6e0f1a2b3c4d5e")

    assert fake_server.cancelled_jobs == ["3d9a1c0e5b7f4a2d8c6e0f1a2b3c4d5e"]
    assert job["cancel_requested"] is True
    assert job["result"]["cancelled"] is True


async def test_server_error_surfaces_with_the_server_message(
    server_url, client_factory, fake_server: FakeWan2GP
):
    fake_server.tool_errors["wangp_generate"] = "Unknown model_type: wan9"

    async with Wan2GPClient(server_url, httpx_client_factory=client_factory) as client:
        with pytest.raises(Wan2GPError, match="Unknown model_type: wan9"):
            await client.submit({"model_type": "wan9"})


async def test_calling_before_connect_raises(server_url, client_factory):
    client = Wan2GPClient(server_url, httpx_client_factory=client_factory)
    with pytest.raises(Wan2GPError, match="not connected"):
        _ = client.session


async def test_relative_transfer_urls_resolve_against_the_origin(client_factory):
    client = Wan2GPClient("http://wan2gp.test:7866/mcp", httpx_client_factory=client_factory)
    assert client.origin == "http://wan2gp.test:7866/"


def test_job_error_message_joins_message_and_stage():
    assert job_error_message(fixture("job_failed")) == "CUDA out of memory (stage: denoising)"


def test_progress_from_job_takes_the_latest_event():
    latest = progress_from_job(fixture("job_running"))
    assert latest is not None
    assert latest["current_step"] == 12
    assert progress_from_job(fixture("job_submitted")) is None


def test_media_type_for_maps_extensions():
    assert media_type_for("a.png") == "image"
    assert media_type_for("a.mp4") == "video"
    assert media_type_for("a.wav") == "audio"


async def test_every_tool_the_client_uses_is_exercised(
    server_url, client_factory, fake_server: FakeWan2GP
):
    """The fake's request log must show each tool the client wraps."""
    fake_server.job_snapshots = [fixture("job_done")]

    async def no_sleep(_seconds: float) -> None:
        return None

    async with Wan2GPClient(server_url, httpx_client_factory=client_factory) as client:
        await client.list_models()
        await client.get_model_defaults("t2v_2_2")
        await client.upload_bytes("start.png", fixture_bytes("tiny.png"))
        job_id = await client.submit({"model_type": "t2v_2_2", "prompt": "hi"})
        await client.poll_until_done(job_id, sleep=no_sleep)
        await client.download_media("visual:9f8e7d6c5b4a")
        await client.cancel(job_id)

    assert fake_server.tool_names_called() == {
        "wangp_models",
        "wangp_model",
        "wangp_create_gallery_upload",
        "wangp_generate",
        "wangp_get_job",
        "wangp_create_gallery_download",
        "wangp_cancel_job",
    }
