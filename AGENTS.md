# Contributor Guidelines

This repository provides Wan2GP nodes for the [nodetool](https://github.com/nodetool-ai/nodetool)
project and depends on [nodetool-core](https://github.com/nodetool-ai/nodetool-core).

## License boundary (read this first)

Wan2GP is proprietary (WanGP Community License 2.0) and `mmgp` is
non-commercial-only. This package must never import from either one, at runtime,
in tests, or in scripts. The only connection to Wan2GP is an MCP HTTP call to a
server the user runs. Keep it that way.

This check must return nothing:

```bash
grep -rn "shared.api\|import wgp\|mmgp" src tests scripts
```

## Code Style

- Use **Python 3.11+** syntax.
- All nodes live under `src/nodetool/nodes/wan2gp` and must inherit from `BaseNode`.
- Node attributes are defined with `pydantic.Field`. Async `process` methods return
  the matching reference type.
- Each node must contain a short docstring describing the model and several
  example use cases. The docstring is the node description in the UI.
- Provide a `get_basic_fields` class method listing the most relevant fields.
- Nodes never build JSON-RPC. Every MCP call goes through `_client.py`.
- The private modules split the work: `_client.py` speaks MCP, `_settings.py`
  maps node fields to a Wan2GP settings dict, and `_base.py` holds
  `_Wan2GPNode` with the connection fields and the submit, poll, download loop.
  A node file adds fields, a docstring, and the settings it wants.
- A node type id follows the module path, for example
  `wan2gp.text_to_video.TextToVideo`.

## Python Environment

Use the conda `nodetool` environment. Do not use system Python.

```bash
conda activate nodetool
```

## Commands

After you add or change a node, regenerate the metadata:

```bash
nodetool-pkg scan --write
```

Never hand-edit `src/nodetool/package_metadata/nodetool-wan2gp.json`.

## Linting and Tests

Run these before you open a pull request:

```bash
ruff check .
ty check .
pytest -q
```

## Contract documentation

`docs/wan2gp-contract.md` records the Wan2GP MCP tool shapes this package
depends on, with the upstream commit hash. If you change a call, update that
file and the matching fixture in `tests/fixtures/`.
