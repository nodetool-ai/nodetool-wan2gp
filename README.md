# nodetool-wan2gp

NodeTool nodes that generate video, images, audio and 3D models with a
[Wan2GP](https://github.com/deepbeepmeep/Wan2GP) server you run yourself. The nodes call Wan2GP's MCP server over HTTP, so no
model ever loads inside the NodeTool process.

## License boundary

This package is AGPL-3.0-or-later, because it subclasses `BaseNode` from
`nodetool-core`. WanGP is separately licensed under the WanGP Community License
2.0, and `mmgp` permits non-commercial use with credit. The Python package does
not import either project; it communicates over MCP. Free, non-monetized
redistribution is supported by the optional combined image below. Selling,
white-labelling, or monetizing access to WanGP needs a separate written license;
see [NOTICE.md](NOTICE.md).

## Model licenses

Each model Wan2GP downloads keeps its own license, separate from WanGP's and
this package's. Read it before you use the model or what it makes. Two of the
newest model lines carry terms that decide who may use them:

- **MiniMax H3** (`minimax_h3_*`) is under the MiniMax H3 Community License
  Agreement, shipped in Wan2GP as `models/minimax_h3/X2_VAE_LICENSE`. It grants
  rights only outside its Excluded Territories: the European Union, the United
  Kingdom, the Republic of Korea and the United States. It does not authorize
  using the model or its outputs there. Commercial products and services must
  display "MiniMax H3", and those with more than 20 million US dollars in yearly
  revenue need MiniMax's written authorization.
- **LTX-2** (`ltx2_*`) is under Lightricks'
  [LTX-2 Community License Agreement](https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2).
  Entities with annual revenue of 10 million US dollars or more need a paid
  commercial license from Lightricks.

This summary is not legal advice, and license texts change. The license file
or model card at the source is authoritative.

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
python wgp.py --mcp --mcp-async --mcp-transport streamable-http --mcp-host 127.0.0.1 --mcp-port 7866
```

`--mcp-async` is required on Wan2GP's current MCP API: the nodes submit a job and
poll it, and the server refuses that without the flag. The nodes detect the API
version when they connect, so servers from before API v2 keep working without it.

MCP clients connect to `http://<host>:<port>/mcp`. Use `--mcp-host 0.0.0.0` only
on a trusted network or behind an authenticated reverse proxy.

## Install the pack

In the desktop app, open **Tools → Package Manager** and install the
**Wan2GP** pack. NodeTool installs `nodetool-wan2gp` from PyPI into its own
Python environment, setting up Python first if needed.

Without the desktop app, install it from PyPI into the environment that runs
the NodeTool Python worker, not the Wan2GP one:

```bash
pip install "nodetool-wan2gp>=0.2.0"
```

Version 0.2.0 requires `nodetool-core>=0.8.1` with its `audio` extra, `httpx2`,
and MCP `>=2.3,<3`. Version 0.1.0 still uses MCP 1.x and `httpx`. The audio
extra provides the dependencies needed for `ProcessingContext` asset conversion.
No PyTorch, no diffusers. To work on the pack itself, see
[Development](#development).

## Point NodeTool at your server

Each node resolves the server URL when it runs, in this order:

1. The node's `server_url` field, when it is not blank. This can reach a second
   machine.
2. `WAN2GP_MCP_URL`, set in NodeTool's Settings or in the environment.
3. `http://127.0.0.1:7866/mcp`.

The Python worker reads `WAN2GP_MCP_URL` from the environment NodeTool gives it
when it starts, so set the variable before you start NodeTool, and restart
NodeTool after changing it:

```bash
export WAN2GP_MCP_URL=http://127.0.0.1:7866/mcp
nodetool serve
```

A desktop app launched from the Finder or the Start menu never sees a shell
`export`. Set the URL in Settings there, or fill in the node's `server_url`.

## Use your server in the composer and Create view

The nodes above take a plain prompt. To pick Wan2GP models in the chat
composer, the Create view and ejected preset workflows, where presets compile
before the prompt is sent, run this package as NodeTool's `wangp` provider. Set
these variables in the environment of the NodeTool Python worker that has the
pack installed, then restart NodeTool:

```bash
export NODETOOL_PROVIDER_ADAPTER_COMMAND_WANGP=nodetool-wan2gp-provider
export NODETOOL_PROVIDER_ADAPTER_CAPABILITIES_WANGP=text_to_video,image_to_video,reference_to_video,text_to_image,image_to_image
export NODETOOL_PROVIDER_ADAPTER_DISPLAY_NAME_WANGP=Wan2GP
export WAN2GP_MCP_URL=http://127.0.0.1:7866/mcp
```

`nodetool-wan2gp-provider` is installed with the pack. If the worker's `PATH`
does not include it, give its full path or `<worker python> -m
nodetool.nodes.wan2gp._provider`. The worker runs it once per request, and it
talks to your server over MCP like the nodes do, so the model never loads in
NodeTool. It lists the server's video and image models with the tasks their
capabilities allow, uploads start and reference images through the gallery,
and returns the first output. It does not send reference videos yet. Speech
and music models stay with the nodes. `WAN2GP_PROVIDER_TIMEOUT_SECONDS`
changes the 30-minute limit for one generation.

NodeTool's Settings cannot set these variables yet. Set them in the
environment NodeTool starts from. A desktop app started from the Finder or the
Start menu does not see a shell `export`.

On WanGP v19.02 the server listed 172 video and 139 image models through this
adapter, and text, image and reference requests reached the server as jobs.
No generation completed, because the test machine had no GPU.

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

Then point the NodeTool main process at the container. `NODETOOL_WORKER_URL`
selects the WebSocket transport. Without it, NodeTool starts its own local
Python worker and never contacts the container:

```bash
export NODETOOL_WORKER_URL=ws://<gpu-host>:7777
export NODETOOL_WORKER_TOKEN=<the token the container was started with>
nodetool serve
```

The worker stores WanGP configuration in `/workspace/wan2gp/config`, model weights
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

`Generate` takes optional media inputs and uploads each one to the server's
gallery before it submits the job:

| Input | Wan2GP setting |
| --- | --- |
| `image` | `image_start` |
| `image_end` | `image_end` |
| `reference_images` (a list) | `image_refs` |
| `video` | `video_guide` |
| `video_mask` | `video_mask` |
| `source_video` | `video_source` |
| `audio` | `audio_guide` |
| `custom_file` | `custom_guide` |

Wan2GP turns on the start, end, reference, continuation and audio modes itself.
A control video with a mask also needs `"video_prompt_type": "VA"` in
`settings`, unless the model's defaults enable it. `custom_file` is the extra
file some models require, such as a `.npy` trajectory for `wanmove` or an
`.abc` score for `yue2`. It goes to the server's workspace instead of the
gallery, which needs MCP API v2 or later. Set `custom_file_name` when the asset
has no file name in its URI.

`Generate` returns an image, video, audio or 3D model reference according to
the returned gallery item's `media_type`. It fails with a clear message for
interactive worlds, which NodeTool cannot store. The dedicated video nodes
reject non-video outputs.

These settings were checked with `wangp_validate` on WanGP v19.02. No
generation has run through the new inputs yet. See
[docs/wan2gp-contract.md](docs/wan2gp-contract.md#media-settings-the-generate-node-sends).

### `wan2gp.list_models.ListModels`

Lists the models the running server offers, with each one's outputs and
`media_inputs`. Filter by `query`, `main_output`, `media_input` and
`capability`. The list includes finetunes, so it reflects your install, not
this package's release.

```python
ListModels(main_output="video", media_input="image")
```

`model_type` values are the stems of the JSON files in Wan2GP's `defaults/`
and `finetunes/` directories, such as `t2v_2_2`, `i2v_2_2` and
`ti2v_2_2_fastwan`. The node fields take them as free text, because the list
depends on the server. See [docs/wan2gp-contract.md](docs/wan2gp-contract.md)
for the MCP tool shapes this package depends on.

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
