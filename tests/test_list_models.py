"""Tests for the ListModels node, run against the fake server."""

from __future__ import annotations

import pytest

from nodetool.nodes.wan2gp.list_models import ListModels, OutputKind

from conftest import FakeWan2GP, fixture


def a_node(server_url: str, **fields) -> ListModels:
    node = ListModels(server_url=server_url, **fields)
    node._id = "lm1"
    return node


def compact(row: dict) -> dict:
    """A search row without a query: WanGP returns only names and sizes."""
    return {"model_type": row["model_type"], "name": row["name"], "accelerated": "profiles"}


async def test_lists_models_across_pages_with_their_media_inputs(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    recorded = fixture("models_search_v2_pages")
    fake_server.model_pages = recorded["pages"]

    models = await a_node(
        server_url,
        query="fastwan",
        main_output=OutputKind.VIDEO,
        media_input="image",
        limit=2,
    ).process(context)

    assert [row["model_type"] for row in models] == ["ovi_fastwan", "ovi_1_1_10s_fastwan"]
    assert models[0]["media_inputs"] == recorded["pages"][0]["models"][0]["media_inputs"]
    assert models[0]["main_output"] == ["video"]
    searches = [call["arguments"] for call in fake_server.args_for("wangp_models")]
    assert searches[0] == {
        "query": "fastwan",
        "filters": {"main_output": "video", "inputs": "image"},
        "limit": 2,
    }
    assert searches[1]["cursor"] == recorded["pages"][0]["next_cursor"]
    # Full rows need no extra capability calls.
    assert fake_server.args_for("wangp_model") == []


async def test_stops_at_the_limit(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    fake_server.model_pages = fixture("models_search_v2_pages")["pages"]

    models = await a_node(server_url, query="fastwan", limit=1).process(context)

    assert [row["model_type"] for row in models] == ["ovi_fastwan"]
    assert len(fake_server.args_for("wangp_models")) == 1


async def test_reads_capabilities_for_compact_rows(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    capabilities = fixture("model_capabilities_ti2v_2_2_fastwan")
    row = capabilities["metadata"]
    fake_server.model_pages = [{"status": "done", "models": [compact(row)], "has_more": False}]

    models = await a_node(server_url).process(context)

    assert models == [
        {
            "model_type": "ti2v_2_2_fastwan",
            "name": row["name"],
            "family": "wan2_2",
            "main_output": ["video"],
            "outputs": ["video"],
            "inputs": ["text", "image", "video"],
            "media_inputs": {"image": ["start"], "video": ["continue", "last"]},
            "capabilities": row["capabilities"],
        }
    ]
    assert fake_server.args_for("wangp_model") == [
        {"model_type": "ti2v_2_2_fastwan", "action": "capabilities"}
    ]
    assert fake_server.args_for("wangp_models")[0]["arguments"] == {"query": "", "limit": 50}


async def test_capability_filter_is_sent_as_a_list(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    fake_server.model_pages = [{"status": "done", "models": [], "has_more": False}]

    assert await a_node(server_url, capability="reference_images").process(context) == []
    assert fake_server.args_for("wangp_models")[0]["arguments"]["filters"] == {
        "capabilities": ["reference_images"]
    }


async def test_legacy_servers_return_their_rows(
    server_url, context, wan2gp_nodes, fake_server: FakeWan2GP
):
    fake_server.legacy = True

    models = await a_node(server_url, query="wan").process(context)

    assert [row["model_type"] for row in models] == ["t2v_2_2", "i2v_2_2", "t2v", "i2v"]
    assert models[1]["inputs"] == ["image"]
    assert fake_server.args_for("wangp_models") == [{"query": "wan", "limit": 50}]


@pytest.mark.parametrize("limit", [0, 501])
def test_limit_is_bounded(limit):
    with pytest.raises(ValueError):
        ListModels(limit=limit)


def test_the_node_is_not_cacheable():
    assert ListModels.is_cacheable() is False
    assert ListModels.get_node_type() == "wan2gp.list_models.ListModels"
