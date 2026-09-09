#!/usr/bin/env python3
"""Check the authenticated public worker handshake."""

from __future__ import annotations

import os

from websockets.sync.client import connect


def main() -> None:
    token = os.environ.get("NODETOOL_WORKER_TOKEN", "")
    if not token:
        raise SystemExit("NODETOOL_WORKER_TOKEN is missing")

    worker_port = int(os.environ.get("NODETOOL_WORKER_PORT", "7777"))
    with connect(
        f"ws://127.0.0.1:{worker_port}",
        open_timeout=5,
        close_timeout=5,
        additional_headers={"Authorization": f"Bearer {token}"},
    ):
        pass


if __name__ == "__main__":
    main()
