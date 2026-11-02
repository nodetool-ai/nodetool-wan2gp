"""The combined image's entrypoint, run with a stand-in interpreter, and its Dockerfile."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
ENTRYPOINT = ROOT / "scripts/combined-entrypoint.sh"
DOCKERFILE = (ROOT / "Dockerfile.combined").read_text()


def start(tmp_path: Path, **env: str) -> subprocess.CompletedProcess[str]:
    """Run the entrypoint with a fake python that logs its arguments."""
    log = tmp_path / "calls.log"
    fake = tmp_path / "python"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$PWD|$*|port=${{WAN2GP_MCP_PORT:-}}|upstream=${{WANGP_UPSTREAM_PORT:-}}" >> {log}\n'
        # WanGP stands in as a process that stops with status 3.
        'if [[ "$1" == "wgp.py" ]]; then sleep 0.2; exit 3; fi\n'
        "exec sleep 30\n"
    )
    fake.chmod(0o755)
    root = tmp_path / "Wan2GP"
    root.mkdir()
    base = {
        "PATH": os.environ["PATH"],
        "WAN2GP_ACCEPT_LICENSE": "1",
        "WAN2GP_MCP_TOKEN": "token",
        "WORKSPACE_DIR": str(tmp_path / "workspace"),
        "WANGP_PYTHON": str(fake),
        "WANGP_ROOT": str(root),
        "WANGP_PROXY": "/opt/proxy.py",
    }
    base.update(env)
    base = {key: value for key, value in base.items() if value != ""}
    return subprocess.run(
        ["bash", str(ENTRYPOINT)], env=base, capture_output=True, text=True, timeout=20
    )


def calls(tmp_path: Path) -> list[str]:
    return sorted((tmp_path / "calls.log").read_text().splitlines())


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"WAN2GP_ACCEPT_LICENSE": ""}, "WAN2GP_ACCEPT_LICENSE=1"),
        ({"WAN2GP_MCP_TOKEN": ""}, "WAN2GP_MCP_TOKEN must be non-empty"),
        ({"WORKSPACE_DIR": "relative"}, "absolute path"),
        ({"WAN2GP_MCP_PORT": "70000"}, "integers from 1 to 65535"),
        ({"WANGP_UPSTREAM_PORT": "7866"}, "must differ"),
    ],
)
def test_refuses_to_start(tmp_path: Path, env: dict[str, str], message: str) -> None:
    result = start(tmp_path, **env)
    assert result.returncode == 64
    assert message in result.stderr
    assert not (tmp_path / "calls.log").exists()


def test_binds_wangp_to_loopback_and_publishes_the_proxy(tmp_path: Path) -> None:
    result = start(tmp_path)
    # WanGP stopped with 3, so the container stops with 3 and takes the proxy down.
    assert result.returncode == 3
    root = tmp_path / "Wan2GP"
    config = tmp_path / "workspace/wan2gp/config"
    assert calls(tmp_path) == sorted(
        [
            f"{root}|/opt/proxy.py|port=7866|upstream=7867",
            f"{root}|wgp.py --mcp --mcp-async --mcp-transport streamable-http "
            f"--mcp-host 127.0.0.1 --mcp-port 7867 --config {config}|port=|upstream=",
        ]
    )
    assert (tmp_path / "workspace/wan2gp/models").is_dir()
    assert "Authorization: Bearer" in result.stdout


def test_dockerfile_pins_wangp_v19_02_and_runs_no_nodetool_code() -> None:
    assert "ARG WANGP_COMMIT=616e60506aff10086bbbde02a3bf4554c572adde" in DOCKERFILE
    assert "https://download.pytorch.org/whl/cu128" in DOCKERFILE
    assert "nodetool.worker" not in DOCKERFILE
    assert "NODETOOL_PROVIDER_ADAPTER" not in DOCKERFILE
    assert "MMGP_COMMIT" not in DOCKERFILE
    assert "EXPOSE 7866" in DOCKERFILE
    assert "combined/auth_proxy.py" in DOCKERFILE


def test_healthcheck_never_opens_an_event_stream() -> None:
    # WanGP answers a GET on /mcp that accepts text/event-stream with a stream
    # that never ends, which would hang the healthcheck.
    healthcheck = (ROOT / "scripts/combined-healthcheck.py").read_text()
    assert '"Accept": "application/json"' in healthcheck
    assert '"Accept": "text/event-stream"' not in healthcheck


def test_healthcheck_reports_a_proxy_that_is_down() -> None:
    result = subprocess.run(
        ["python3", str(ROOT / "scripts/combined-healthcheck.py")],
        env={"PATH": os.environ["PATH"], "WAN2GP_MCP_TOKEN": "t", "WAN2GP_MCP_PORT": "9"},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 1
    assert "The token proxy is not answering" in result.stderr


def test_nothing_here_imports_wangp() -> None:
    for path in [ROOT / "combined/auth_proxy.py", ROOT / "scripts/combined-healthcheck.py"]:
        text = path.read_text()
        assert "import wgp" not in text
        assert "shared.api" not in text
        assert "mmgp" not in text
