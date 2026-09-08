from pathlib import Path


ENTRYPOINT = (Path(__file__).parents[1] / "scripts/combined-entrypoint.sh").read_text()


def test_combined_image_delegates_default_config_to_upstream() -> None:
    assert 'legacy_keys = {"save_path", "image_save_path", "audio_save_path"}' in ENTRYPOINT
    assert '"attention_mode" not in config' in ENTRYPOINT
    assert "path.rename(backup)" in ENTRYPOINT
    assert "json.dump(payload" not in ENTRYPOINT


def test_combined_image_still_runs_worker_only() -> None:
    assert "node backend/server.mjs" not in ENTRYPOINT
    assert "SECRETS_MASTER_KEY" not in ENTRYPOINT
    assert "/opt/venv/bin/python -m nodetool.worker" in ENTRYPOINT
