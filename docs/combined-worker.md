# Combined image: processes and network boundary

The combined image runs two processes, both in WanGP's Python environment:

1. WanGP's MCP server: `wgp.py --mcp --mcp-async --mcp-transport
   streamable-http`, bound to `127.0.0.1:7867` inside the container. It serves
   MCP at `/mcp` and the one-use media transfer routes under `/wangp_api/`.
2. `combined/auth_proxy.py`, bound to `0.0.0.0:7866`. It forwards a request
   only when it carries `Authorization: Bearer <WAN2GP_MCP_TOKEN>`, compared in
   constant time, and answers 401 otherwise. It strips that header and sets
   `Host` to WanGP's loopback address before forwarding. Bodies stream in both
   directions, so uploads and the MCP event stream are not buffered. It answers
   502 while WanGP is not listening.

The entrypoint stops the container when either process stops, with that
process's exit status. The healthcheck asks the proxy for `/mcp` with the token
and counts any answer from WanGP as healthy.

No NodeTool code runs in the image. It holds no NodeTool database, secret store
or master key, and no provider credential. NodeTool's `lib.wan2gp` nodes and
`wangp` provider call it with `WAN2GP_MCP_URL` and `WAN2GP_MCP_TOKEN`. Media
crosses the network as gallery and file uploads and downloads through the
transfer tickets WanGP issues, which NodeTool checks before it follows them.

## Runtime configuration

Starting the container requires both:

- `WAN2GP_ACCEPT_LICENSE=1`, confirming review of the non-commercial bundle
  licenses; and
- a strong, random `WAN2GP_MCP_TOKEN`, shared with NodeTool.

`WAN2GP_MCP_PORT` (default 7866) is the published port and
`WANGP_UPSTREAM_PORT` (default 7867) is WanGP's loopback port. Only the
published port is exposed. The proxy speaks plain HTTP: put TLS in front of it,
or keep it on a private network, when NodeTool runs on another machine.
