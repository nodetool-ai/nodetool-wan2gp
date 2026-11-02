#!/usr/bin/env bash
# Start WanGP's MCP server on the container's loopback and publish it through
# the bearer-token proxy. NodeTool connects with WAN2GP_MCP_URL and
# WAN2GP_MCP_TOKEN. The container stops when either process stops.
set -Eeuo pipefail

if [[ "${WAN2GP_ACCEPT_LICENSE:-}" != "1" ]]; then
    echo "Refusing to start: review the bundled licenses and set WAN2GP_ACCEPT_LICENSE=1." >&2
    exit 64
fi
if [[ -z "${WAN2GP_MCP_TOKEN:-}" ]]; then
    echo "Refusing to start: WAN2GP_MCP_TOKEN must be non-empty." >&2
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

valid_port() {
    [[ "$1" =~ ^[0-9]{1,5}$ ]] && (( 10#$1 >= 1 && 10#$1 <= 65535 ))
}
public_port="${WAN2GP_MCP_PORT:-7866}"
upstream_port="${WANGP_UPSTREAM_PORT:-7867}"
for port in "${public_port}" "${upstream_port}"; do
    if ! valid_port "${port}"; then
        echo "Refusing to start: ports must be integers from 1 to 65535, got ${port}." >&2
        exit 64
    fi
done
if [[ "${public_port}" == "${upstream_port}" ]]; then
    echo "Refusing to start: WAN2GP_MCP_PORT and WANGP_UPSTREAM_PORT must differ." >&2
    exit 64
fi

config_dir="${WANGP_CONFIG_DIR:-${workspace_dir}/wan2gp/config}"
model_dir="${WANGP_MODEL_DIR:-${workspace_dir}/wan2gp/models}"
output_dir="${WANGP_OUTPUT_DIR:-${workspace_dir}/wan2gp/outputs}"
export HF_HOME="${HF_HOME:-${workspace_dir}/cache/huggingface}"
mkdir -p "${config_dir}" "${model_dir}" "${output_dir}" "${HF_HOME}"

python="${WANGP_PYTHON:-/opt/wan2gp-venv/bin/python}"
wangp_root="${WANGP_ROOT:-/opt/Wan2GP}"
proxy="${WANGP_PROXY:-/opt/nodetool-wan2gp-combined/auth_proxy.py}"

cd "${wangp_root}"
"${python}" wgp.py --mcp --mcp-async --mcp-transport streamable-http \
    --mcp-host 127.0.0.1 --mcp-port "${upstream_port}" \
    --config "${config_dir}" &
wangp_pid=$!

WAN2GP_MCP_PORT="${public_port}" WANGP_UPSTREAM_PORT="${upstream_port}" "${python}" "${proxy}" &
proxy_pid=$!

stop() {
    kill -TERM "${wangp_pid}" "${proxy_pid}" 2>/dev/null || true
}
trap stop TERM INT

echo "Serving WanGP's MCP server on port ${public_port}. Requests need Authorization: Bearer <WAN2GP_MCP_TOKEN>."
status=0
wait -n "${wangp_pid}" "${proxy_pid}" || status=$?
stop
wait "${wangp_pid}" "${proxy_pid}" 2>/dev/null || true
exit "${status}"
