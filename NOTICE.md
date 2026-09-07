# Notice

This package is licensed under the GNU Affero General Public License v3.0 or
later, because it subclasses `BaseNode` from `nodetool-core`, which is AGPL-3.0.

Wan2GP is a separately licensed program under the WanGP Community License 2.0,
and its memory manager `mmgp` is licensed for non-commercial use with credit.
The Python package never imports either project and reaches WanGP over MCP.

The optional `Dockerfile.combined` distribution includes revision-pinned copies
in a separate Python environment for free, non-monetized use. It preserves the
WanGP source tree and its license/notices, includes the mmgp license and credit,
records upstream revisions, and does not bundle model weights. See
`docs/combined-image-licenses.md`.

You may run Wan2GP locally and use it for client work. You may not sell it,
white-label it, embed it in a paid product, or offer paid API, SaaS, or hosted
access to it without a separate written reseller or commercial license from its
author. Free redistribution and non-monetized integrations are permitted when
the WanGP Community License 2.0 redistribution conditions are satisfied.
