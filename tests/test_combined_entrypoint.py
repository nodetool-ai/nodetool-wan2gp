from pathlib import Path


ENTRYPOINT = (Path(__file__).parents[1] / "scripts/combined-entrypoint.sh").read_text()
HEALTHCHECK = (Path(__file__).parents[1] / "scripts/combined-healthcheck.py").read_text()
DOCKERFILE = (Path(__file__).parents[1] / "Dockerfile.combined").read_text()


def test_combined_image_delegates_default_config_to_upstream() -> None:
    assert 'legacy_keys = {"save_path", "image_save_path", "audio_save_path"}' in ENTRYPOINT
    assert '"attention_mode" not in config' in ENTRYPOINT
    assert "path.rename(backup)" in ENTRYPOINT
    assert "json.dump(payload" not in ENTRYPOINT


def test_combined_image_still_runs_worker_only() -> None:
    assert "node backend/server.mjs" not in ENTRYPOINT
    assert "SECRETS_MASTER_KEY" not in ENTRYPOINT
    assert "/opt/venv/bin/python -m nodetool.worker" in ENTRYPOINT
    assert "exec /opt/venv/bin/python -m nodetool.worker" in ENTRYPOINT
    assert "--namespaces wan2gp" not in ENTRYPOINT


def test_combined_image_has_no_mcp_service() -> None:
    runtime = ENTRYPOINT + HEALTHCHECK + DOCKERFILE
    assert "WAN2GP_MCP" not in runtime
    assert "7866" not in runtime
    assert "shared.mcp_server" not in runtime
    assert "pip install" not in DOCKERFILE.split("COPY . /tmp/nodetool-wan2gp", 1)[1]


def test_combined_image_installs_worker_runtime_dependencies() -> None:
    core_install = DOCKERFILE.split(
        "# Pin the worker protocol implementation", 1
    )[1].split("# WanGP deliberately lives", 1)[0]
    assert "pip install" in core_install
    assert "--no-deps" not in core_install
def test_combined_image_uses_a40_compatible_pytorch_wheels() -> None:
    assert "https://download.pytorch.org/whl/cu128" in DOCKERFILE
    assert "https://download.pytorch.org/whl/cu130" not in DOCKERFILE
