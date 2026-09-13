# nodetool-wan2gp

NodeTool nodes that generate video with a [Wan2GP](https://github.com/deepbeepmeep/Wan2GP)
server you run yourself. The nodes call Wan2GP's MCP server over HTTP, so no
model ever loads inside the NodeTool process.

## License boundary

This package is AGPL-3.0-or-later, because it subclasses `BaseNode` from
`nodetool-core`. WanGP is separately licensed under the WanGP Community License
2.0, and `mmgp` permits non-commercial use with credit. The Python package does
not import either project; it communicates over MCP. Free, non-monetized
redistribution is supported by the optional combined image below. Selling,
white-labelling, or monetizing access to WanGP needs a separate written license;
see [NOTICE.md](NOTICE.md).

## Install Wan2GP

Wan2GP needs its own conda environment and its own PyTorch build. Do not install
it into the NodeTool environment. From Wan2GP's `docs/INSTALLATION.md`, for
RTX 20xx to RTX 50xx with CUDA 13.1:

```bash
git clone https://github.com/deepbeepmeep/Wan2GP.git
cd Wan2GP
conda create -n wan2gp python=3.11.14
conda activate wan2gp
pip install torch==2.10.0 torchvision==0.25.0 torchaudio==2.10.0 --index-url https://download.pytorch.org/whl/cu130
pip install -r requirements.txt
```

For GTX 10xx with CUDA 12.8, the same file gives:

```bash
conda create -n wan2gp python=3.10.9
conda activate wan2gp
pip install torch==2.7.1 torchvision==0.22.1 torchaudio==2.7.1 --index-url https://download.pytorch.org/whl/test/cu128
pip install -r requirements.txt
```

Start Wan2GP with its MCP server on streamable HTTP, from `docs/API.md`:

```bash
python wgp.py --mcp --mcp-transport streamable-http --mcp-host 127.0.0.1 --mcp-port 7866
```

MCP clients connect to `http://<host>:<port>/mcp`. Use `--mcp-host 0.0.0.0` only
on a trusted network or behind an authenticated reverse proxy.

## Install the pack

In the NodeTool environment, not the Wan2GP one:

```bash
git clone https://github.com/nodetool-ai/nodetool-wan2gp.git
cd nodetool-wan2gp
pip install -e .
```

It requires `nodetool-core>=0.8.0` with its `audio` extra, `httpx`, and MCP
`>=1.16,<2`. The audio extra provides the dependencies needed for
`ProcessingContext` asset conversion. No PyTorch, no diffusers.

## Point NodeTool at your server

Set `WAN2GP_MCP_URL` before you run a workflow. Nodes with a blank `server_url`
resolve this environment variable at execution time:

```bash
export WAN2GP_MCP_URL=http://127.0.0.1:7866/mcp
```

Without it they fall back to `http://127.0.0.1:7866/mcp`. An explicit non-blank
`server_url` on a node always takes precedence, so it can reach a second machine.

## Combined non-commercial GPU image

`Dockerfile.combined` is a provider-only GPU worker. It runs the NodeTool
Python worker and calls a revision-pinned WanGP runtime directly from its
isolated Python environment. It does not start WanGP's MCP server or the
NodeTool main process; connect an external NodeTool main process to the
authenticated worker on port 7777. The regular package above remains the
MCP-only client for a separately run Wan2GP server.

```bash
docker build -f Dockerfile.combined -t nodetool-wan2gp:combined .
export NODETOOL_WORKER_TOKEN="$(openssl rand -hex 32)"
docker run --gpus all --rm -p 7777:7777 \
  -e WAN2GP_ACCEPT_LICENSE=1 \
  -e NODETOOL_WORKER_TOKEN \
  -v nodetool-wangp-data:/workspace \
  nodetool-wan2gp:combined
```

Set the same `NODETOOL_WORKER_TOKEN` in the external NodeTool main process. The
worker stores WanGP configuration in `/workspace/wan2gp/config`, model weights
in `/workspace/wan2gp/models`, generated files in `/workspace/wan2gp/outputs`,
and Hugging Face cache data in `/workspace/cache/huggingface`. Review each
model's separate license. This image is only for free, non-monetized use.
Read [the combined-image license and attribution notes](docs/combined-image-licenses.md)
before building, running, or redistributing it.

Every node also has a `max_media_bytes` limit for gallery uploads and downloads.
It defaults to 512 MiB to avoid allocating the server's 8 GiB ticket limit by
accident, and can be deliberately raised or lowered up to the explicit 8 GiB
ceiling. Downloads are streamed through a small bounded spool before the final
asset bytes are returned.

## The nodes

### `wan2gp.text_to_video.TextToVideo`

Generates a clip from a prompt. Fields map to Wan2GP settings: `width` and
`height` become `resolution`, `num_frames` becomes `video_length`, `fps` becomes
`force_fps`.

```python
TextToVideo(
    prompt="A paper boat drifts down a rain gutter, seen from just above the water.",
    model_type="t2v_2_2",
    width=832,
    height=480,
    num_frames=81,
    num_inference_steps=30,
)
```

### `wan2gp.image_to_video.ImageToVideo`

Animates a still image. The image is uploaded to the server's gallery and passed
as `image_start` with `image_prompt_type="S"`. Filesystem paths are never sent.

```python
ImageToVideo(
    image=ImageRef(uri="https://example.com/still.png"),
    prompt="The camera pushes in as the leaves start to move.",
    model_type="i2v_2_2",
    width=832,
    height=480,
    num_frames=81,
)
```

### `wan2gp.generate.Generate`

Runs any model with a settings dict applied on top of that model's own defaults.
Use it for models and settings the other two nodes do not cover. The reserved
`_api` key is removed from your dict.

```python
Generate(
    model_type="ti2v_2_2",
    settings={
        "prompt": "A lighthouse beam sweeps across fog.",
        "resolution": "1280x704",
        "video_length": 121,
        "guidance_scale": 5.0,
    },
)
```

`Generate` returns an image, video, or audio reference according to the
returned gallery item's `media_type`; the dedicated video nodes reject
non-video outputs. `model_type` values are the stems of the JSON files in
Wan2GP's `defaults/` directory, such as `t2v`, `t2v_2_2`, `i2v`, `i2v_2_2`, and
`ti2v_2_2`. Call the
`wangp_models` tool on your own server for the list it offers. See
[docs/wan2gp-contract.md](docs/wan2gp-contract.md) for the MCP tool shapes this
package depends on.

## Run the smoke script

`scripts/smoke.py` runs one cheap generation against a real Wan2GP with no
NodeTool server: 512x288, 17 frames, 4 denoising steps. It prints the settings
it sent and each progress event, then writes the clip into a workspace
directory.

```bash
python scripts/smoke.py
python scripts/smoke.py --server-url http://127.0.0.1:7866/mcp --model-type t2v_2_2 --prompt "a red kite"
```

It exits non-zero when the generation fails or the server is unreachable.

## Development

```bash
conda activate nodetool
pip install -e .
ruff check .
ty check .
pytest -q
```

The tests answer every MCP call from an in-process fake, so they need no Wan2GP
and no network. After you add or change a node, regenerate the metadata with
`nodetool-pkg scan --write` and commit the result. Never hand-edit
`src/nodetool/package_metadata/nodetool-wan2gp.json`. See [AGENTS.md](AGENTS.md)
for the rest of the contributor rules.
