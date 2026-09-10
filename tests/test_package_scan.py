"""The package metadata scan must find exactly the three v1 nodes.

This runs the real ``nodetool-pkg scan`` in a subprocess, the same command that
writes ``src/nodetool/package_metadata/nodetool-wan2gp.json``. A node that fails
to import, or a node this package should not ship, fails here.
"""

from __future__ import annotations

import inspect
import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
METADATA = REPO_ROOT / "src" / "nodetool" / "package_metadata" / "nodetool-wan2gp.json"

EXPECTED_NODE_TYPES = [
    "wan2gp.generate.Generate",
    "wan2gp.image_to_video.ImageToVideo",
    "wan2gp.text_to_video.TextToVideo",
]

SHARED_FIELDS = ["server_url", "timeout_seconds", "max_media_bytes", "seed"]
VIDEO_FIELDS = [
    "prompt",
    "negative_prompt",
    "model_type",
    "width",
    "height",
    "num_frames",
    "fps",
    "num_inference_steps",
    "loras",
    "lora_multipliers",
]

EXPECTED_FIELDS = {
    "wan2gp.text_to_video.TextToVideo": SHARED_FIELDS + VIDEO_FIELDS,
    "wan2gp.image_to_video.ImageToVideo": SHARED_FIELDS + ["image"] + VIDEO_FIELDS,
    "wan2gp.generate.Generate": SHARED_FIELDS + ["model_type", "settings", "image", "video"],
}

EXPECTED_BASIC_FIELDS = {
    "wan2gp.text_to_video.TextToVideo": ["prompt", "model_type", "width", "height", "num_frames"],
    "wan2gp.image_to_video.ImageToVideo": [
        "image",
        "prompt",
        "model_type",
        "width",
        "height",
        "num_frames",
    ],
    "wan2gp.generate.Generate": ["model_type", "settings"],
}


@pytest.fixture(scope="module")
def scanned() -> dict:
    """Run the scanner and return the package metadata it produces."""
    result = subprocess.run(
        [sys.executable, "-m", "nodetool.package_tools", "scan"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _node(scanned: dict, node_type: str) -> dict:
    matches = [node for node in scanned["nodes"] if node["node_type"] == node_type]
    assert len(matches) == 1, f"{node_type} appears {len(matches)} times"
    return matches[0]


def test_the_scan_finds_exactly_the_three_v1_nodes(scanned):
    assert sorted(node["node_type"] for node in scanned["nodes"]) == EXPECTED_NODE_TYPES


def test_runtime_dependencies_are_compatible():
    dependencies = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())["project"]["dependencies"]
    assert "nodetool-core[audio]>=0.8.0" in dependencies
    assert "mcp>=1.16.0,<2.0.0" in dependencies


def test_the_scan_reports_no_warnings(scanned):
    assert scanned.get("warnings") in (None, [])


@pytest.mark.parametrize("node_type", EXPECTED_NODE_TYPES)
def test_each_node_declares_the_expected_fields(scanned, node_type):
    node = _node(scanned, node_type)
    assert [prop["name"] for prop in node["properties"]] == EXPECTED_FIELDS[node_type]


@pytest.mark.parametrize("node_type", EXPECTED_NODE_TYPES)
def test_each_node_declares_its_basic_fields(scanned, node_type):
    node = _node(scanned, node_type)
    assert node["basic_fields"] == EXPECTED_BASIC_FIELDS[node_type]


@pytest.mark.parametrize("node_type", EXPECTED_NODE_TYPES)
def test_server_url_metadata_is_runtime_safe(scanned, node_type):
    node = _node(scanned, node_type)
    server_url = next(prop for prop in node["properties"] if prop["name"] == "server_url")
    assert server_url["default"] is None


@pytest.mark.parametrize("node_type", EXPECTED_NODE_TYPES)
def test_media_limit_metadata_is_safe_and_bounded(scanned, node_type):
    node = _node(scanned, node_type)
    media_limit = next(
        prop for prop in node["properties"] if prop["name"] == "max_media_bytes"
    )
    assert media_limit["default"] == 512 * 1024**2
    assert media_limit["min"] == 1
    assert media_limit["max"] == 8 * 1024**3


@pytest.mark.parametrize("node_type", EXPECTED_NODE_TYPES)
def test_each_node_declares_its_output_type(scanned, node_type):
    node = _node(scanned, node_type)
    output_type = node["outputs"][0]["type"]
    if node_type == "wan2gp.generate.Generate":
        assert output_type == {
            "type": "union",
            "type_args": [{"type": "image"}, {"type": "video"}, {"type": "audio"}],
        }
    else:
        assert output_type == {"type": "video"}


@pytest.mark.parametrize("node_type", EXPECTED_NODE_TYPES)
def test_every_field_carries_a_description(scanned, node_type):
    node = _node(scanned, node_type)
    missing = [prop["name"] for prop in node["properties"] if not prop.get("description")]
    assert missing == []


@pytest.mark.parametrize("node_type", EXPECTED_NODE_TYPES)
def test_every_node_documents_use_cases(scanned, node_type):
    node = _node(scanned, node_type)
    assert "Use cases:" in node["description"]


def _canonicalize_description_whitespace(metadata: dict) -> dict:
    """Ignore only docstring indentation differences between core releases."""
    canonical = dict(metadata)
    canonical["nodes"] = [
        {
            **node,
            "description": inspect.cleandoc(node["description"]),
        }
        for node in metadata["nodes"]
    ]
    return canonical


def test_the_committed_metadata_matches_a_fresh_scan(scanned):
    committed = json.loads(METADATA.read_text())
    assert _canonicalize_description_whitespace(committed) == _canonicalize_description_whitespace(
        scanned
    )
