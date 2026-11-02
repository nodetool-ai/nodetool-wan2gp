# Contributor Guidelines

This repository builds the combined image: a pinned WanGP release serving its
MCP server behind a bearer-token proxy, for NodeTool's built-in Wan2GP support.
The Python node pack that lived here is discontinued. NodeTool's `lib.wan2gp`
nodes and `wangp` provider, in the nodetool repository, replace it.

## License and distribution boundary (read this first)

`Dockerfile.combined` may redistribute a revision-pinned WanGP, including the
mmgp it vendors, for free, non-monetized use under the WanGP Community License
2.0. The combined image must:

- include the complete WanGP license, its vendored mmgp license, and WanGP's
  bundled third-party notices;
- identify the exact upstream revision and state whether it was modified;
- identify itself prominently as non-commercial and not endorsed by WanGP;
- contain no NodeTool code: NodeTool reaches WanGP over the network only;
- never be sold, white-labelled, embedded in a paid product, or exposed as a
  paid, sponsored, ad-supported, SaaS, hosted, managed, API, OEM, marketplace,
  or otherwise monetized service without the necessary written licenses; and
- preserve all separate model, weight, dataset, and dependency license terms.

Do not add model weights to the image. Runtime-downloaded weights retain their
own licenses and must be reviewed before use or redistribution.

`combined/auth_proxy.py` and the scripts must not import WanGP. This check must
return nothing:

```bash
grep -rn "shared.api\|import wgp\|mmgp" combined scripts
```

## Code Style

- Python 3.10, the version the image's WanGP environment uses.
- The proxy uses only uvicorn, starlette and httpx, which WanGP's pinned `mcp`
  package already installs.

## Linting and Tests

```bash
ruff check .
pytest -q
```

## Contract documentation

`docs/wan2gp-contract.md` records the WanGP MCP tool shapes NodeTool's client
depends on, with the upstream commit hash. `tests/fixtures/` holds the
recorded responses it cites. Update both when the pin moves.
