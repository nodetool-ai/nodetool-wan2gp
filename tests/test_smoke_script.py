"""Cover scripts/smoke.py so CI notices when the script stops working."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

SMOKE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "smoke.py"


def load_smoke():
    """Import scripts/smoke.py by path. It is a script, not a package module."""
    spec = importlib.util.spec_from_file_location("wan2gp_smoke", SMOKE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def smoke():
    return load_smoke()


def test_help_runs_without_a_server():
    """--help must work with no Wan2GP running and no arguments to guess."""
    result = subprocess.run(
        [sys.executable, str(SMOKE_PATH), "--help"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "--server-url" in result.stdout
    assert "--model-type" in result.stdout
    assert "--prompt" in result.stdout


def test_parser_flags(smoke):
    args = smoke.build_parser().parse_args(
        ["--server-url", "http://example.test/mcp", "--model-type", "t2v", "--prompt", "hi"]
    )
    assert args.server_url == "http://example.test/mcp"
    assert args.model_type == "t2v"
    assert args.prompt == "hi"


def test_node_uses_the_small_settings(smoke):
    """The smoke run stays cheap: 512x288, 17 frames, 4 steps."""
    args = smoke.build_parser().parse_args([])
    settings = smoke.make_node(args).build_settings()
    assert settings["resolution"] == "512x288"
    assert settings["video_length"] == 17
    assert settings["num_inference_steps"] == 4


def test_connection_failure_reports_the_server_url(smoke, capsys):
    error = BaseExceptionGroup("unhandled", [httpx.ConnectError("All attempts failed")])
    smoke.report_failure(error, "http://127.0.0.1:7866/mcp")
    message = capsys.readouterr().err
    assert "cannot reach a Wan2GP MCP server at http://127.0.0.1:7866/mcp" in message


def test_run_against_the_fake_server(smoke, wan2gp_nodes, tmp_path, capsys):
    """The whole script path, from settings to a written file."""
    import asyncio

    args = smoke.build_parser().parse_args(
        ["--server-url", "http://wan2gp.test/mcp", "--workspace-dir", str(tmp_path)]
    )
    assert asyncio.run(smoke.run(args)) == 0
    output = tmp_path / "smoke.mp4"
    assert output.exists() and output.stat().st_size > 0
    printed = capsys.readouterr().out
    assert "settings sent to wangp_generate" in printed
    assert str(output) in printed
