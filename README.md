# nodetool-wan2gp

NodeTool nodes that generate video with a [Wan2GP](https://github.com/deepbeepmeep/Wan2GP)
server you run yourself. The nodes call Wan2GP's MCP server over HTTP, so no
model ever loads inside the NodeTool process.

## License boundary

This package is AGPL-3.0-or-later, because it subclasses `BaseNode` from
`nodetool-core`. Wan2GP is a separate program under the proprietary WanGP
Community License 2.0, and its memory manager `mmgp` is licensed for
non-commercial use only, so this package never imports either one. You may run
Wan2GP locally and use it for client work, but selling it, white-labelling it,
or offering paid API, SaaS, or hosted access to it needs a separate license from
its author; see [NOTICE.md](NOTICE.md).

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

It pulls in `nodetool-core`, `httpx`, and `mcp`. No PyTorch, no diffusers.

## Point NodeTool at your server

Set `WAN2GP_MCP_URL` before you start NodeTool. It becomes the default value of
the `server_url` field on every node:

```bash
export WAN2GP_MCP_URL=http://127.0.0.1:7866/mcp
```

Without it the nodes default to `http://127.0.0.1:7866/mcp`. You can also
override `server_url` on a single node to reach a second machine.

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

`model_type` values are the stems of the JSON files in Wan2GP's `defaults/`
directory, such as `t2v`, `t2v_2_2`, `i2v`, `i2v_2_2`, and `ti2v_2_2`. Call the
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
