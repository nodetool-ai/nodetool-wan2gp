# Combined image worker and secrets boundary

The combined image is a GPU execution worker, not a NodeTool main process. It
runs two processes:

1. WanGP's MCP server on IPv4 loopback only.
2. The NodeTool Python WebSocket worker on port 7777.

The image does not start the TypeScript backend, open a NodeTool database, use
the desktop keychain, or create/read a `SECRETS_MASTER_KEY`. The loopback MCP
URL is internal plumbing between the Python node package and WanGP; it is not a
second public service.

The worker also advertises the `wangp` model-preparation backend. A
`models.prepare` request launches a short-lived adapter in WanGP's isolated
Python environment. The adapter calls WanGP's existing download functions and
does not patch or replace them. It observes the model/cache directories and the
adapter process's Linux I/O counters, reporting bytes written, transfer rate,
active files, free disk space, and time since activity. Unknown remote totals
are reported as `total_bytes: 0`. After the configured quiet period, progress
continues with `stalled: true`; the worker does not abort automatically.
The combined Dockerfile pins the NodeTool worker revision that implements this
protocol so it does not depend on when the moving base image is rebuilt.

The same worker advertises WanGP as a provider with video model discovery,
`text_to_video`, and `image_to_video` capabilities. These requests launch a
short-lived adapter in WanGP's isolated interpreter and call its public
in-process API directly. Model identifiers and capabilities come from the
pinned WanGP runtime. Encoded inputs cross the interpreter boundary through a
worker-owned temporary file; the adapter returns an output path and the worker
streams the resulting video bytes over its existing authenticated protocol.
WanGP progress callbacks are relayed as provider progress frames. No WanGP code
is imported into the NodeTool environment and no upstream source is modified.

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
