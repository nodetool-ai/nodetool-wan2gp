#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${WAN2GP_ACCEPT_LICENSE:-}" != "1" ]]; then
    echo "Refusing to start: review the bundled licenses and set WAN2GP_ACCEPT_LICENSE=1." >&2
    exit 64
fi
if [[ -z "${NODETOOL_WORKER_TOKEN:-}" ]]; then
    echo "Refusing to start: NODETOOL_WORKER_TOKEN must be non-empty." >&2
    exit 64
fi

echo "NOTICE: Bundled generation components are for free, non-monetized use only."
echo "NOTICE: This image is not endorsed by the WanGP authors."
echo "NOTICE: License texts are under /opt/Wan2GP and /opt/licenses."

workspace_dir="${WORKSPACE_DIR:-/workspace}"
if [[ "${workspace_dir}" != /* ]]; then
    echo "Refusing to start: WORKSPACE_DIR must be an absolute path." >&2
    exit 64
fi

worker_host="${NODETOOL_WORKER_HOST:-0.0.0.0}"
worker_port="${NODETOOL_WORKER_PORT:-7777}"
if [[ ! "${worker_port}" =~ ^[0-9]{1,5}$ ]] || (( 10#${worker_port} < 1 || 10#${worker_port} > 65535 )); then
    echo "Refusing to start: NODETOOL_WORKER_PORT must be an integer from 1 to 65535." >&2
    exit 64
fi

config_dir="${WANGP_CONFIG_DIR:-${workspace_dir}/wan2gp/config}"
model_dir="${WANGP_MODEL_DIR:-${workspace_dir}/wan2gp/models}"
output_dir="${WANGP_OUTPUT_DIR:-${workspace_dir}/wan2gp/outputs}"
config_path="${config_dir}/wgp_config.json"
export WANGP_CONFIG_PATH="${config_path}"
export HF_HOME="${HF_HOME:-${workspace_dir}/cache/huggingface}"

mkdir -p "${config_dir}" "${model_dir}" "${output_dir}" "${HF_HOME}"

# WanGP owns its config schema and creates a complete default file when none is
# present. Archive the incomplete three-key file produced by combined images
# before this fix, then let the pinned upstream revision initialize it.
/opt/venv/bin/python - "${config_path}" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.exists():
    raise SystemExit(0)
try:
    config = json.loads(path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    raise SystemExit("Existing WanGP config is unreadable; refusing to overwrite it")

legacy_keys = {"save_path", "image_save_path", "audio_save_path"}
if isinstance(config, dict) and set(config) <= legacy_keys and "attention_mode" not in config:
    backup = path.with_suffix(".incomplete.json")
    counter = 1
    while backup.exists():
        backup = path.with_suffix(f".incomplete-{counter}.json")
        counter += 1
    path.rename(backup)
    print(f"Archived incomplete WanGP config as {backup}.")
PY

echo "Starting authenticated NodeTool Python worker on ${worker_host}:${worker_port}."
exec /opt/venv/bin/python -m nodetool.worker \
    --host "${worker_host}" \
    --port "${worker_port}"
