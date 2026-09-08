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

mcp_host="${WAN2GP_MCP_HOST:-127.0.0.1}"
if [[ "${mcp_host}" != "127.0.0.1" ]]; then
    echo "Refusing to start: WAN2GP_MCP_HOST must remain 127.0.0.1." >&2
    exit 64
fi
mcp_port="${WAN2GP_MCP_PORT:-7866}"
worker_host="${NODETOOL_WORKER_HOST:-0.0.0.0}"
worker_port="${NODETOOL_WORKER_PORT:-7777}"
for port in "${mcp_port}" "${worker_port}"; do
    if [[ ! "${port}" =~ ^[0-9]{1,5}$ ]] || (( 10#${port} < 1 || 10#${port} > 65535 )); then
        echo "Refusing to start: ports must be integers from 1 to 65535." >&2
        exit 64
    fi
done

config_dir="${WANGP_CONFIG_DIR:-${workspace_dir}/wan2gp/config}"
output_dir="${WANGP_OUTPUT_DIR:-${workspace_dir}/wan2gp/outputs}"
config_path="${config_dir}/wgp_config.json"
export WAN2GP_MCP_URL="http://${mcp_host}:$((10#${mcp_port}))/mcp"
export HF_HOME="${HF_HOME:-${workspace_dir}/cache/huggingface}"

mkdir -p "${config_dir}" "${output_dir}" "${HF_HOME}"

# Create the persisted WanGP config once. This process owns model settings, not
# NodeTool credentials; request credentials arrive only inside worker messages.
/opt/venv/bin/python - "${config_path}" "${output_dir}" <<'PY'
import json
import os
import sys
import tempfile
from pathlib import Path

path = Path(sys.argv[1])
if path.exists():
    raise SystemExit(0)
payload = {
    "save_path": sys.argv[2],
    "image_save_path": sys.argv[2],
    "audio_save_path": sys.argv[2],
}
fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
try:
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.link(temporary, path)
    except FileExistsError:
        pass
finally:
    try:
        os.unlink(temporary)
    except FileNotFoundError:
        pass
PY

wangp_pid=""
worker_pid=""
shutdown() {
    trap - TERM INT EXIT
    [[ -n "${wangp_pid}" ]] && kill -TERM "${wangp_pid}" 2>/dev/null || true
    [[ -n "${worker_pid}" ]] && kill -TERM "${worker_pid}" 2>/dev/null || true
}
trap shutdown TERM INT EXIT

cd /opt/Wan2GP
/opt/wan2gp-venv/bin/python -m shared.mcp_server \
    --root /opt/Wan2GP \
    --config "${config_path}" \
    --output-dir "${output_dir}" \
    --transport streamable-http \
    --host "${mcp_host}" \
    --port "${mcp_port}" \
    --job-event-limit 20 &
wangp_pid=$!

startup_timeout="${WAN2GP_STARTUP_TIMEOUT:-900}"
mcp_ready="0"
for _ in $(seq 1 "${startup_timeout}"); do
    if ! kill -0 "${wangp_pid}" 2>/dev/null; then
        echo "WanGP MCP exited during startup." >&2
        exit 1
    fi
    if /opt/venv/bin/python - "${mcp_host}" "${mcp_port}" <<'PY'
import socket
import sys
try:
    with socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=1):
        pass
except OSError:
    raise SystemExit(1)
PY
    then
        mcp_ready="1"
        break
    fi
    sleep 1
done

if [[ "${mcp_ready}" != "1" ]]; then
    echo "WanGP MCP did not become reachable within ${startup_timeout}s." >&2
    exit 1
fi

echo "Starting authenticated NodeTool Python worker on ${worker_host}:${worker_port}."
/opt/venv/bin/python -m nodetool.worker \
    --host "${worker_host}" \
    --port "${worker_port}" \
    --namespaces wan2gp &
worker_pid=$!

set +e
wait -n "${wangp_pid}" "${worker_pid}"
status=$?
set -e
echo "A required service exited with status ${status}; stopping the container." >&2
shutdown
wait "${wangp_pid}" "${worker_pid}" 2>/dev/null || true
exit "${status}"
