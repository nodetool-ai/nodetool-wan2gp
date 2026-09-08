#!/usr/bin/env python3
"""Check the private MCP listener and authenticated public worker handshake."""

from __future__ import annotations

import os
import socket

from websockets.sync.client import connect


def main() -> None:
    token = os.environ.get("NODETOOL_WORKER_TOKEN", "")
    if not token:
        raise SystemExit("NODETOOL_WORKER_TOKEN is missing")

    mcp_port = int(os.environ.get("WAN2GP_MCP_PORT", "7866"))
    worker_port = int(os.environ.get("NODETOOL_WORKER_PORT", "7777"))
    with socket.create_connection(("127.0.0.1", mcp_port), timeout=3):
        pass
    with connect(
        f"ws://127.0.0.1:{worker_port}",
        open_timeout=5,
        close_timeout=5,
        additional_headers={"Authorization": f"Bearer {token}"},
    ):
        pass


if __name__ == "__main__":
    main()
