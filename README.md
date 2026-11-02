# nodetool-wan2gp

A non-commercial GPU image that serves a pinned
[Wan2GP](https://github.com/deepbeepmeep/Wan2GP) release over MCP, for
NodeTool's built-in Wan2GP support.

## The nodes moved into NodeTool

The Python node pack that lived here is discontinued. NodeTool now has the
Wan2GP nodes and provider built in, in TypeScript:

- `lib.wan2gp.TextToVideo`, `ImageToVideo`, `Generate` and `ListModels`
  replace `wan2gp.text_to_video.TextToVideo`, `wan2gp.image_to_video.ImageToVideo`,
  `wan2gp.generate.Generate` and `wan2gp.list_models.ListModels`. The node ids
  changed, so a workflow that used the old nodes needs them replaced.
- The `wangp` provider lists your server's models in the composer and the
  Create view without a Python worker or `NODETOOL_PROVIDER_ADAPTER_*`
  variables.

See NodeTool's [Wan2GP guide](https://github.com/nodetool-ai/nodetool/blob/main/docs/wan2gp.md).
The last `nodetool-wan2gp` release stays on PyPI but gets no updates.

## License boundary

WanGP is licensed under the WanGP Community License 2.0, and so is the mmgp
memory manager it vendors. NodeTool reaches WanGP only over the network and
ships none of it. Free, non-monetized redistribution is supported by the
combined image below. Selling, white-labelling, or monetizing access to WanGP
needs a separate written license; see [NOTICE.md](NOTICE.md).

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

NodeTool's Package Manager installs Wan2GP for you: **Tools → Package Manager
→ Engines & tools → Wan2GP**, or `nodetool runtime add wan2gp`. It downloads
the pinned release and runs Wan2GP's own unattended installer, and NodeTool
starts the server on demand. See NodeTool's
[Wan2GP guide](https://github.com/nodetool-ai/nodetool/blob/main/docs/wan2gp.md).

To run Wan2GP yourself instead, install it by hand:

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

`--mcp-async` is required: NodeTool submits a job and polls it, and the server
refuses that without the flag. NodeTool needs MCP API v2 or later.

MCP clients connect to `http://<host>:<port>/mcp`. Use `--mcp-host 0.0.0.0` only
on a trusted network or behind an authenticated reverse proxy.

## Combined non-commercial GPU image

`Dockerfile.combined` runs WanGP v19.02 (`616e605`) with its MCP server, bound
to the container's loopback, behind a proxy that requires a bearer token. No
NodeTool code runs in it. Every request, MCP calls and media transfers alike,
needs `Authorization: Bearer <WAN2GP_MCP_TOKEN>`.

```bash
docker build -f Dockerfile.combined -t nodetool-wan2gp:combined .
export WAN2GP_MCP_TOKEN="$(openssl rand -hex 32)"
docker run --gpus all --rm -p 7866:7866 \
  -e WAN2GP_ACCEPT_LICENSE=1 \
  -e WAN2GP_MCP_TOKEN \
  -v nodetool-wangp-data:/workspace \
  nodetool-wan2gp:combined
```

Then point NodeTool at it. Set both in **Settings → Integrations → Wan2GP** or
in the environment NodeTool starts from:

```bash
export WAN2GP_MCP_URL=http://<gpu-host>:7866/mcp
export WAN2GP_MCP_TOKEN=<the token the container was started with>
```

The image keeps WanGP's configuration in `/workspace/wan2gp/config`, model
weights in `/workspace/wan2gp/models`, generated files in
`/workspace/wan2gp/outputs`, and the Hugging Face cache in
`/workspace/cache/huggingface`. WanGP downloads a model's weights the first
time it runs that model. The proxy speaks plain HTTP, so put TLS in front of
it, or use a private network, when the server is not on your machine.

This image was not built or run on a GPU for this release. The entrypoint, the
proxy and the healthcheck are tested here. The proxy and the healthcheck also
ran in front of a WanGP v19.02 MCP server, started with `--offline` on a
machine without a GPU: NodeTool's client listed 172 video and 139 image models
through it, round-tripped a gallery upload, uploaded a custom file, and got the
server's missing-weights error back from a generation. A request without the
token got 401, and the proxy answered 502 once WanGP stopped. Whether WanGP's
requirements install on the CUDA 12.8 base is untested.

Review each model's separate license. This image is only for free,
non-monetized use. Read [the combined-image license and attribution notes](docs/combined-image-licenses.md)
before building, running, or redistributing it.

## Development

```bash
pip install "httpx>=0.28" "pytest>=8" "starlette>=0.40" "uvicorn>=0.30" ruff
ruff check .
pytest -q
```

`docs/wan2gp-contract.md` records the WanGP MCP tool shapes NodeTool's client
depends on, and `tests/fixtures/` holds the recorded responses it cites.
NodeTool's tests use copies of them.
