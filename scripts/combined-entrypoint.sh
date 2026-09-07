#!/usr/bin/env bash
set -Eeuo pipefail

echo "NOTICE: WanGP/mmgp are provided only for free, non-monetized use."
echo "NOTICE: This image is not endorsed by the WanGP authors."
echo "NOTICE: License texts are under /opt/Wan2GP and /opt/licenses."

mkdir -p "${WANGP_CONFIG_DIR}" "${WANGP_OUTPUT_DIR}" "${HF_HOME}"

shutdown() {
    trap - TERM INT
    kill -TERM "${wangp_pid:-}" "${nodetool_pid:-}" 2>/dev/null || true
    wait "${wangp_pid:-}" "${nodetool_pid:-}" 2>/dev/null || true
}
trap shutdown TERM INT

cd /opt/Wan2GP
/opt/wan2gp-venv/bin/python wgp.py \
    --mcp \
    --mcp-transport streamable-http \
    --mcp-host 127.0.0.1 \
    --mcp-port 7866 \
    --config "${WANGP_CONFIG_DIR}" \
    --output-dir "${WANGP_OUTPUT_DIR}" \
    ${WANGP_EXTRA_ARGS:-} &
wangp_pid=$!

cd /app
node backend/server.mjs &
nodetool_pid=$!

set +e
wait -n "${wangp_pid}" "${nodetool_pid}"
status=$?
set -e

echo "A required service exited with status ${status}; stopping the container."
shutdown
exit "${status}"
