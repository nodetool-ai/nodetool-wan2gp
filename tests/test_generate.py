"""Tests for the Generate passthrough node, run against the fake server."""

from __future__ import annotations

import pytest
from nodetool.metadata.types import AudioRef, ImageRef, VideoRef

from nodetool.nodes.wan2gp._client import Wan2GPError
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


async def test_node_media_limit_is_passed_to_the_client(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    with pytest.raises(Wan2GPError, match="exceeds the 1 byte transfer limit"):
        await a_node(server_url, max_media_bytes=1).process(context)


async def test_process_dispatches_an_image_output(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    done = fixture("job_done")
    done["result"]["gallery_items"][0]["media_type"] = "image"
    fake_server.job_snapshots = [done]
    fake_server.download_payload = fixture_bytes("tiny.png")

    image = await a_node(server_url).process(context)

    assert isinstance(image, ImageRef)
    assert image.data == fixture_bytes("tiny.png")


async def test_process_dispatches_an_audio_output(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    import io
    import wave

    done = fixture("job_done")
    done["result"]["gallery_items"][0]["media_type"] = "audio"
    fake_server.job_snapshots = [done]
    audio = io.BytesIO()
    with wave.open(audio, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\\x00\\x00" * 80)
    fake_server.download_payload = audio.getvalue()

    result = await a_node(server_url).process(context)

    assert isinstance(result, AudioRef)


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
        {"settings": expected, "wait": False}
    ]
    assert fake_server.args_for("wangp_model") == [
        {"model_type": "t2v_2_2", "action": "defaults", "arguments": {}}
    ]


async def test_process_strips_the_api_key(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    node = a_node(server_url, settings={"_api": {"return_media": True}, "prompt": "x"})
    await node.process(context)

    source = fake_server.args_for("wangp_generate")[0]["settings"]
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

    source = fake_server.args_for("wangp_generate")[0]["settings"]
    assert source["image_start"] == "visual:0a1b2c3d4e5f"
    assert fake_server.session_args("create_gallery_upload") == [
        {"filename": "image.png"}
    ]


async def test_process_uploads_an_optional_video_as_video_guide(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    node = a_node(server_url, video=VideoRef(data=fixture_bytes("tiny.mp4")))
    await node.process(context)

    source = fake_server.args_for("wangp_generate")[0]["settings"]
    assert source["video_guide"] == "visual:0a1b2c3d4e5f"
    assert fake_server.session_args("create_gallery_upload") == [
        {"filename": "video.mp4"}
    ]


async def test_process_uploads_nothing_when_no_media_is_connected(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    await a_node(server_url).process(context)

    assert fake_server.session_args("create_gallery_upload") == []
    source = fake_server.args_for("wangp_generate")[0]["settings"]
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


# -- media inputs beyond image_start and video_guide --------------------------


def wav_bytes() -> bytes:
    import io
    import wave

    audio = io.BytesIO()
    with wave.open(audio, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\x00\x00" * 80)
    return audio.getvalue()


async def test_process_uploads_an_end_image_as_image_end(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    node = a_node(server_url, image_end=ImageRef(data=fixture_bytes("tiny.png")))
    await node.process(context)

    source = fake_server.args_for("wangp_generate")[0]["settings"]
    assert source["image_end"] == "visual:0a1b2c3d4e5f"
    assert "image_start" not in source


async def test_process_uploads_reference_images_as_an_ordered_image_refs_list(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    png = fixture_bytes("tiny.png")
    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 16
    node = a_node(
        server_url,
        reference_images=[ImageRef(data=png), ImageRef(data=jpeg)],
    )
    await node.process(context)

    source = fake_server.args_for("wangp_generate")[0]["settings"]
    assert source["image_refs"] == ["visual:0a1b2c3d4e5f", "visual:0a1b2c3d4e5f"]
    assert fake_server.session_args("create_gallery_upload") == [
        {"filename": "image.png"},
        {"filename": "image.jpg"},
    ]
    assert fake_server.upload_bodies == [png, jpeg]


async def test_process_skips_empty_reference_images(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    await a_node(server_url, reference_images=[ImageRef()]).process(context)

    source = fake_server.args_for("wangp_generate")[0]["settings"]
    assert "image_refs" not in source
    assert fake_server.session_args("create_gallery_upload") == []


async def test_process_uploads_a_mask_video_and_a_source_video(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    clip = fixture_bytes("tiny.mp4")
    node = a_node(
        server_url,
        video_mask=VideoRef(data=clip),
        source_video=VideoRef(data=clip),
    )
    await node.process(context)

    source = fake_server.args_for("wangp_generate")[0]["settings"]
    assert source["video_mask"] == "visual:0a1b2c3d4e5f"
    assert source["video_source"] == "visual:0a1b2c3d4e5f"
    assert "video_guide" not in source


async def test_process_uploads_audio_as_audio_guide(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    node = a_node(server_url, audio=AudioRef(data=wav_bytes()))
    await node.process(context)

    source = fake_server.args_for("wangp_generate")[0]["settings"]
    assert source["audio_guide"] == "visual:0a1b2c3d4e5f"
    assert fake_server.session_args("create_gallery_upload") == [
        {"filename": "audio.wav"}
    ]


async def test_media_inputs_override_the_same_keys_in_user_settings(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    node = a_node(
        server_url,
        settings={"image_end": "visual:ffffffffffff", "video_prompt_type": "I"},
        image_end=ImageRef(data=fixture_bytes("tiny.png")),
    )
    await node.process(context)

    source = fake_server.args_for("wangp_generate")[0]["settings"]
    assert source["image_end"] == "visual:0a1b2c3d4e5f"
    assert source["video_prompt_type"] == "I"


# -- custom_file: a model's extra input file -----------------------------------


async def test_process_uploads_a_custom_file_to_the_workspace_as_custom_guide(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    from nodetool.metadata.types import AssetRef

    trajectory = b"\x93NUMPY\x01\x00" + b"\x00" * 32
    node = a_node(
        server_url,
        model_type="wanmove",
        custom_file=AssetRef(data=trajectory),
        custom_file_name="trajectory.npy",
    )
    await node.process(context)

    source = fake_server.args_for("wangp_generate")[0]["settings"]
    assert source["custom_guide"] == "@documents/uploads/filetoken0/trajectory.npy"
    assert fake_server.session_args("create_file_upload") == [
        {"filename": "trajectory.npy", "size_bytes": len(trajectory)}
    ]
    assert list(fake_server.file_uploads.values()) == [trajectory]
    # The file never goes into the media gallery.
    assert fake_server.session_args("create_gallery_upload") == []


async def test_custom_file_name_falls_back_to_the_asset_uri(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    from nodetool.metadata.types import AssetRef

    score = b"X:1\nK:C\nCDEF|\n"
    node = a_node(
        server_url,
        model_type="yue2",
        custom_file=AssetRef(uri="https://example.test/scores/my%20tune.abc", data=score),
    )
    await node.process(context)

    assert fake_server.session_args("create_file_upload") == [
        {"filename": "my tune.abc", "size_bytes": len(score)}
    ]


async def test_custom_file_without_a_file_name_is_rejected_before_any_call(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    from nodetool.metadata.types import AssetRef

    node = a_node(server_url, custom_file=AssetRef(data=b"data"))
    with pytest.raises(ValueError, match="custom_file_name"):
        await node.process(context)
    assert fake_server.args_for("wangp_generate") == []


@pytest.mark.parametrize("name", ["../x.npy", "dir/x.npy", "noextension"])
async def test_custom_file_name_must_be_a_bare_name_with_an_extension(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP, name
):
    from nodetool.metadata.types import AssetRef

    node = a_node(server_url, custom_file=AssetRef(data=b"data"), custom_file_name=name)
    with pytest.raises(ValueError, match="custom_file_name"):
        await node.process(context)
    assert fake_server.args_for("wangp_generate") == []


async def test_custom_file_needs_api_v2(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    from nodetool.metadata.types import AssetRef

    fake_server.legacy = True
    node = a_node(
        server_url,
        model_type="wanmove",
        custom_file=AssetRef(data=b"data"),
        custom_file_name="trajectory.npy",
    )
    with pytest.raises(Wan2GPError, match="API v2"):
        await node.process(context)
    assert fake_server.args_for("wangp_generate") == []


async def test_custom_file_turns_on_the_mode_the_model_declares_for_it(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    from nodetool.metadata.types import AssetRef

    # yue2 declares custom_file with audio_prompt_type "1", and its defaults
    # use "0", which ignores the score without an error.
    assert fixture("model_defaults_yue2")["audio_prompt_type"] == "0"
    node = a_node(
        server_url,
        model_type="yue2",
        custom_file=AssetRef(data=b"X:1\nK:C\nCDEF|\n"),
        custom_file_name="tune.abc",
    )
    await node.process(context)

    source = fake_server.args_for("wangp_generate")[0]["settings"]
    assert source["audio_prompt_type"] == "1"
    assert fake_server.args_for("wangp_model")[-1] == {
        "model_type": "yue2",
        "action": "capabilities",
    }


async def test_a_mode_in_user_settings_wins_over_the_declared_custom_file_mode(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    from nodetool.metadata.types import AssetRef

    node = a_node(
        server_url,
        model_type="yue2",
        settings={"audio_prompt_type": "12"},
        custom_file=AssetRef(data=b"X:1\nK:C\nCDEF|\n"),
        custom_file_name="tune.abc",
    )
    await node.process(context)

    source = fake_server.args_for("wangp_generate")[0]["settings"]
    assert source["audio_prompt_type"] == "12"


# -- outputs beyond image, video and audio ------------------------------------


async def test_process_returns_a_3d_output_as_a_model3d_ref(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    from nodetool.metadata.types import Model3DRef

    done = fixture("job_done")
    done["result"]["gallery_items"][0].update(
        {"media_type": "3d", "gallery": "3d", "filename": "mesh_001.glb"}
    )
    fake_server.job_snapshots = [done]
    fake_server.download_payload = b"glTF\x02\x00\x00\x00" + b"\x00" * 16

    result = await a_node(server_url).process(context)

    assert isinstance(result, Model3DRef)
    assert result.format == "glb"
    assert result.data == fake_server.download_payload


async def test_process_rejects_a_world_output_with_a_clear_message(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    done = fixture("job_done")
    done["result"]["gallery_items"][0].update(
        {"media_type": "world", "gallery": "world", "filename": "scene.wgpworld"}
    )
    fake_server.job_snapshots = [done]

    with pytest.raises(ValueError, match="world"):
        await a_node(server_url).process(context)
    assert fake_server.session_args("create_gallery_download") == []


async def test_process_reports_a_text_only_result(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    done = fixture("job_done")
    done["result"]["gallery_items"] = []
    done["result"]["generated_files"] = ["/outputs/transcript.txt"]
    fake_server.job_snapshots = [done]

    with pytest.raises(ValueError, match="transcript.txt"):
        await a_node(server_url).process(context)
