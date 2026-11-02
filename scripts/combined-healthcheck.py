#!/usr/bin/env python3
"""Check that the token proxy and WanGP's MCP server both answer.

The proxy answers 502 while WanGP is down and 401 to a wrong token. Any other
status below 500 comes from WanGP itself: a bare GET on /mcp is refused by
the MCP server, which proves it is listening.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request


def main() -> None:
    token = os.environ.get("WAN2GP_MCP_TOKEN", "")
    if not token:
        raise SystemExit("WAN2GP_MCP_TOKEN is missing")
    port = int(os.environ.get("WAN2GP_MCP_PORT", "7866"))
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/mcp",
        headers={"Authorization": f"Bearer {token}", "Accept": "text/event-stream"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            status = response.status
    except urllib.error.HTTPError as error:
        status = error.code
    if status == 401 or status >= 500:
        raise SystemExit(f"WanGP MCP is not ready (HTTP {status})")


if __name__ == "__main__":
    main()
