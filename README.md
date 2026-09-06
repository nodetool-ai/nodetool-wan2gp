# nodetool-wan2gp

NodeTool nodes that generate video with a Wan2GP server you run yourself. The
nodes talk to Wan2GP's MCP server over HTTP and never load a model in the
NodeTool process.

## License boundary

This package is AGPL-3.0-or-later because it subclasses `BaseNode` from
`nodetool-core`. Wan2GP itself is proprietary under the WanGP Community License
2.0, and its memory manager `mmgp` is non-commercial-only, so this package never
imports either one. Hosting Wan2GP as a paid service needs a license from its
author; see [NOTICE.md](NOTICE.md).

Full README follows in phase P5.
