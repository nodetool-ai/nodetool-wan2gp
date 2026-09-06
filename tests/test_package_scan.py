"""The package metadata scan must find exactly the three v1 nodes.

This runs the real ``nodetool-pkg scan`` in a subprocess, the same command that
writes ``src/nodetool/package_metadata/nodetool-wan2gp.json``. A node that fails
to import, or a node this package should not ship, fails here.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
METADATA = REPO_ROOT / "src" / "nodetool" / "package_metadata" / "nodetool-wan2gp.json"

EXPECTED_NODE_TYPES = [
    "wan2gp.generate.Generate",
    "wan2gp.image_to_video.ImageToVideo",
    "wan2gp.text_to_video.TextToVideo",
]

SHARED_FIELDS = ["server_url", "timeout_seconds", "seed"]
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
def test_each_node_outputs_a_video(scanned, node_type):
    node = _node(scanned, node_type)
    assert [output["type"]["type"] for output in node["outputs"]] == ["video"]


@pytest.mark.parametrize("node_type", EXPECTED_NODE_TYPES)
def test_every_field_carries_a_description(scanned, node_type):
    node = _node(scanned, node_type)
    missing = [prop["name"] for prop in node["properties"] if not prop.get("description")]
    assert missing == []


@pytest.mark.parametrize("node_type", EXPECTED_NODE_TYPES)
def test_every_node_documents_use_cases(scanned, node_type):
    node = _node(scanned, node_type)
    assert "Use cases:" in node["description"]


def test_the_committed_metadata_matches_a_fresh_scan(scanned):
    committed = json.loads(METADATA.read_text())
    assert committed == scanned
