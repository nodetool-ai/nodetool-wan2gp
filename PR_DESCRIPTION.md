# nodetool-wan2gp: NodeTool nodes for a self-hosted Wan2GP

## Summary

A new node pack that generates video with a Wan2GP server the user runs. It adds
three nodes and nothing else:

| Node type | Output |
| --- | --- |
| `wan2gp.text_to_video.TextToVideo` | `VideoRef` |
| `wan2gp.image_to_video.ImageToVideo` | `VideoRef` |
| `wan2gp.generate.Generate` | `VideoRef` |

The pack reaches Wan2GP through its MCP server over streamable HTTP, using the
official `mcp` client. Every call goes through `_client.py`; nodes never build
JSON-RPC. Input media is uploaded through `wangp_create_gallery_upload` and
passed by gallery `media_id`, and output media is fetched through
`wangp_create_gallery_download`, so NodeTool and Wan2GP never need a shared
filesystem. Progress comes from polling `wangp_get_job` once a second and is
forwarded as `NodeProgress`. A cancelled node sends `wangp_cancel_job` before it
unwinds.

The process boundary is a license boundary. Wan2GP is proprietary under the
WanGP Community License 2.0 and its memory manager `mmgp` is non-commercial
only, so this pack never imports either one. It depends on `nodetool-core`,
`httpx`, and `mcp`. No PyTorch. `NOTICE.md` states the boundary and README.md
repeats it.

## How to test

```bash
conda activate nodetool
pip install -e .
ruff check .
ty check .
pytest -q
nodetool-pkg scan          # 3 nodes, JSON matches the committed file
grep -rn "shared.api\|import wgp\|mmgp" src tests scripts   # must print nothing
```

The suite is 93 tests and needs no network and no Wan2GP. `tests/conftest.py`
serves a fake MCP server in-process over `httpx.ASGITransport`, injected into
the `mcp` client through its `httpx_client_factory`. It answers `initialize`,
`tools/list`, and `tools/call` from `tests/fixtures/`, records every request,
captures the bytes of a PUT upload, and returns a 1.7 KB real MP4 from the
download route.

Against a real server:

```bash
# In the Wan2GP environment
python wgp.py --mcp --mcp-transport streamable-http --mcp-host 127.0.0.1 --mcp-port 7866

# In the nodetool environment
python scripts/smoke.py
```

## Not verified: no Wan2GP instance was reachable

**No Wan2GP server and no GPU were available on the machine where this was
written, so `scripts/smoke.py` was never run against a live server.** It was run
only in two ways: `--help`, which exits 0 with no server, and a no-server run,
which exits 1 with a connection error naming the URL. `tests/test_smoke_script.py`
drives the whole script path against the in-process fake.

Everything the pack believes about Wan2GP's MCP surface was read out of the
Wan2GP source at commit `057f9ecab9ad57dfbec9768b2daf7a4426ce986c` (2026-09-06).
`docs/wan2gp-contract.md` records each item with its upstream file and line, and
`tests/fixtures/` pins the shapes as JSON. These rest on source reading rather
than a live call:

1. **The input schema of `wangp_generate.source`.** Read as accepting an inline
   settings dict, a task dict, a manifest, or a list of tasks
   (`shared/mcp_server.py:1513-1526`). The pack always sends a single settings
   dict with `wait=False`.
2. **The job snapshot shape that `wangp_generate` and `wangp_get_job` return.**
   Read from `_JobRecord.snapshot` (`shared/mcp_server.py:1050-1071`). There is
   no `status` string: terminal state is the boolean `done` and success is
   `result.success`.
3. **How the upload PUT wants its body.** Read as a plain PUT of raw file bytes,
   no multipart and no required content type (`shared/mcp_server.py:1136-1160`), with
   a one-use token that expires after 600 seconds.
4. **What `wangp_create_gallery_download` returns.** A relative `download_url`
   plus `filename`, `media_type`, and `size` (`shared/mcp_server.py:754-761`).
   Relative transfer URLs are resolved against the MCP origin per
   `docs/API.md:391`.
5. **The `model_type` strings.** Derived from `defaults/*.json` file stems
   (`wgp.py:3280-3295`): `t2v`, `t2v_1.3B`, `t2v_2_2`, `i2v`, `i2v_720p`,
   `i2v_2_2`, `ti2v_2_2`. The defaults are `t2v_2_2` and `i2v_2_2`. Which ids a
   given install exposes depends on its `defaults/` directory.
6. **`image_prompt_type="S"` for an image-to-video run.** From
   `docs/SETTINGS.md:190` and Wan2GP's own factory default at
   `models/wan/wan_handler.py:1257-1258`.
7. **`loras_multipliers` as one space-separated string.** Documented form at
   `docs/SETTINGS.md:177`; the parser also accepts a list.
8. **Whether `structuredContent` carries a dict return value verbatim or
   wrapped.** Not observed from a live FastMCP server. `parse_tool_result` in
   `_client.py` handles both and falls back to parsing the JSON text block.

## Docker

`Dockerfile` mirrors `nodetool-huggingface`: `ARG CORE_IMAGE=nodetool-core:local`
and one `uv pip install` of this pack, with EXPOSE, HEALTHCHECK, and CMD
inherited from the core image. **The build was not run. `docker build` failed
with:**

```
ERROR: failed to connect to the docker API at unix:///Users/mg/.docker/run/docker.sock; check if the path is correct and if the daemon is running: dial unix /Users/mg/.docker/run/docker.sock: connect: no such file or directory
```

The Docker CLI is installed (Docker Engine 29.2.1) but no daemon was running,
and the `nodetool-core:local` base image was therefore also unavailable.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01BfugwEqvGwBFFeX7Yyvrj6
