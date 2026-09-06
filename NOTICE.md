# Notice

This package is licensed under the GNU Affero General Public License v3.0 or
later, because it subclasses `BaseNode` from `nodetool-core`, which is AGPL-3.0.

Wan2GP is a separate program under the proprietary WanGP Community License 2.0,
and its memory manager `mmgp` is licensed for non-commercial use only. This
package therefore never imports Wan2GP or `mmgp`: it reaches a Wan2GP process
the user runs themselves, over an MCP HTTP connection, and that process boundary
is the license boundary.

You may run Wan2GP locally and use it for client work. You may not sell it,
white-label it, embed it in a paid product, or offer paid API, SaaS, or hosted
access to it without a separate commercial license from its author.
