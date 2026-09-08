# Combined image worker and secrets boundary

The combined image is a GPU execution worker, not a NodeTool main process. It
runs two processes:

1. WanGP's MCP server on IPv4 loopback only.
2. The NodeTool Python WebSocket worker on port 7777.

The image does not start the TypeScript backend, open a NodeTool database, use
the desktop keychain, or create/read a `SECRETS_MASTER_KEY`. The loopback MCP
URL is internal plumbing between the Python node package and WanGP; it is not a
second public service.

## Runtime configuration

Starting the container requires both:

- `WAN2GP_ACCEPT_LICENSE=1`, confirming review of the non-commercial bundle
  licenses; and
- a strong, random `NODETOOL_WORKER_TOKEN`, shared with the external NodeTool
  main process and used to authenticate the WebSocket connection.

Only port 7777 should be exposed. WanGP's port 7866 must remain private inside
the container.

## Request-scoped secrets

The external NodeTool main process remains the sole owner of its encrypted
secret store and master key. Before dispatching a node, main resolves only the
settings required for that execution and includes them in the authenticated
worker request's `secrets` map. The Python worker constructs the execution
context from that map and does not decrypt or query the main process's store.

Consequently, `NODETOOL_WORKER_TOKEN` authenticates the transport but is not a
provider credential, and provider secrets should not be configured globally in
the worker container. They exist in worker memory for the lifetime of the
request that needs them.
