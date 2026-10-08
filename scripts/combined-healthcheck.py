#!/usr/bin/env python3
"""Check the authenticated public worker handshake."""

from __future__ import annotations

import os

from websockets.sync.client import connect


def worker_host() -> str:
    """Return the address the worker listens on, as a URL host."""
    host = os.environ.get("NODETOOL_WORKER_HOST", "").strip()
    # A wildcard bind accepts loopback connections.
    if host in ("", "0.0.0.0", "::"):
        return "127.0.0.1"
    return f"[{host}]" if ":" in host else host


def main() -> None:
    token = os.environ.get("NODETOOL_WORKER_TOKEN", "")
    if not token:
        raise SystemExit("NODETOOL_WORKER_TOKEN is missing")

    worker_port = int(os.environ.get("NODETOOL_WORKER_PORT", "7777"))
    with connect(
        f"ws://{worker_host()}:{worker_port}",
        open_timeout=5,
        close_timeout=5,
        additional_headers={"Authorization": f"Bearer {token}"},
    ):
        pass


if __name__ == "__main__":
    main()
