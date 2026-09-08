#!/usr/bin/env bash
set -Eeuo pipefail

echo "NOTICE: WanGP/mmgp are provided only for free, non-monetized use."
echo "NOTICE: This image is not endorsed by the WanGP authors."
echo "NOTICE: License texts are under /opt/Wan2GP and /opt/licenses."

mkdir -p "${WANGP_CONFIG_DIR}" "${WANGP_OUTPUT_DIR}" "${HF_HOME}"

# Headless NodeTool deployments cannot use the desktop keychain. Generate a
# deployment-specific master key on first boot and keep it on the persistent
# workspace volume. An explicitly supplied key always takes precedence.
if [[ -z "${SECRETS_MASTER_KEY:-}" ]]; then
    master_key_file="${SECRETS_MASTER_KEY_FILE:-/workspace/.nodetool-secrets-master-key}"
    umask 077
    if [[ ! -s "${master_key_file}" ]]; then
        /opt/venv/bin/python -c \
            'import base64, secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())' \
            > "${master_key_file}"
    fi
    IFS= read -r SECRETS_MASTER_KEY < "${master_key_file}"
    export SECRETS_MASTER_KEY
fi

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
