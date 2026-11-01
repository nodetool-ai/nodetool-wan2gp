# The Wan2GP MCP contract this package depends on

The client supports two API generations and picks one when it connects, from the
tool list. A server that offers `wangp_session` speaks API v2 or later. Any other
speaks API v1.

## API v2.1, the current default

Confirmed against a live server: WanGP v19.02, commit `616e605`, on 1 November
2026. TextToVideo, ImageToVideo and Generate completed generations through this
package with `ti2v_2_2_fastwan`, and model search, model defaults and job
cancellation were exercised. Other models and the client's API v1 path were not
run against this version.

| Operation | Call |
| --- | --- |
| Generate | `wangp_generate(settings={...}, wait=false)` |
| Read a job | `wangp_session(action="get_job", arguments={"job_id": ...})` |
| Cancel a job | `wangp_session(action="cancel_job", arguments={"job_id": ...})` |
| Upload media | `wangp_session(action="create_gallery_upload", arguments={"filename": ...})` |
| Download media | `wangp_session(action="create_gallery_download", arguments={"media_id": ...})` |
| Model defaults | `wangp_model(model_type=..., action="defaults", arguments={})` |
| Search models | `wangp_models(action="search", arguments={"query": ..., "limit": ...})` |

| Upload a workspace file | `wangp_session(action="create_file_upload", arguments={"filename": ..., "size_bytes": ...})` |
| Model capabilities | `wangp_model(model_type=..., action="capabilities")` |
| Validate settings | `wangp_validate(settings={...})` |

### Media settings the Generate node sends

Confirmed on 1 November 2026 against WanGP v19.02 (`616e605`) with
`wangp_validate`, run on a machine without a GPU, so no generation backed these
rows. The settings came from the node's own `build_settings` with real uploads.
Every case reported `valid: true` and listed the role among the inputs it read.

| Node input | Setting | Mode WanGP turned on | Model checked |
| --- | --- | --- | --- |
| `image` | `image_start` | `image_prompt_type` `S` | `ti2v_2_2_fastwan` |
| `image_end` | `image_end` | `image_prompt_type` `SE` with `image` | `minimax_h3_fl2va_pruned` |
| `reference_images` | `image_refs`, a list of media ids | `video_prompt_type` `KI` | `ltx2_25_22B_msr`, two images |
| `reference_images` with `video` | `image_refs`, `video_guide` | `video_prompt_type` `UVI` | `kiwi_edit` |
| `video` with `video_mask` | `video_guide`, `video_mask` | none: `video_prompt_type` `VA` came from settings | `ltx2_25_22B_distilled` |
| `source_video` | `video_source` | `image_prompt_type` `TV` | `ti2v_2_2_fastwan` |
| `audio` | `audio_guide` | `audio_prompt_type` `A` | `ltx2_25_22B_distilled` |
| `custom_file` | `custom_guide`, a workspace path | from the model's `custom_file` declaration | `wanmove` (`.npy`), `yue2` (`.abc`) |
| `reference_images` | `image_refs` | `video_prompt_type` `I` | `trellis2_shape`, a 3D model |

WanGP infers the start, end, continuation, reference and audio modes from the
media it receives (`apply_media_flag_defaults` in `shared/api.py`). It does not
infer the control and mask modes: `video_guide` without a `V` in
`video_prompt_type` fails with `input would be ignored; requires an enabled
Control or Reference Video mode`. The node leaves that mode to `settings`.

`image_refs` takes a list. Audio goes through the gallery upload like images
and video, and comes back as an `audio:` media id.

### Custom files

The gallery refuses files that are not image, video, audio, 3D or world media,
such as Wan-Move's `.npy` trajectory or YuE's `.abc` score.
`create_file_upload` takes any file name. The client sends `size_bytes`, then
PUTs the raw bytes to the returned `/wangp_api/files/upload/<token>` URL. A
complete upload finalizes itself and answers:

```json
{"status": "done", "offset": 2720, "size_bytes": 2720, "filename": "traj.npy",
 "path": "@documents/uploads/<id>/traj.npy", "mime_type": "application/octet-stream"}
```

`custom_guide` accepts that `path` on a server started without
`--mcp-allow-read-file-system`. It is a handle the server issued, not a path
from the NodeTool machine. `wanmove` without `custom_guide` fails validation
with `custom_guide is required for the selected input mode.`

`wangp_model(action="capabilities")` returns the declaration under
`metadata.media_inputs.custom_file`, for example
`{"name": "ABC Score", "file_types": [".abc"], "required": true,
"audio_prompt_type": "1"}` for `yue2`. Its defaults use `audio_prompt_type`
`"0"`, which ignores the score, and `wangp_validate` still reports the request
as valid. When `custom_file` is connected, Generate applies the declared
`model_mode`, `video_prompt_type` or `audio_prompt_type` unless the user's
settings set it. API v1 has no workspace uploads, so the node refuses
`custom_file` there.

### Outputs

A finished job's `gallery_items[].media_type` is `image`, `video`, `audio`,
`3d` or `world` (`_gallery_media_type` in `shared/mcp/server.py`). Generate
returns a `Model3DRef` for `3d`, with the format taken from the item's file
extension. NodeTool has no reference type for `world`, so Generate fails with a
message that names it. The two transcription models
(`nemotron_transcribe`, `nemotron_transcribe_q4`) list `text` as an output.
Their result shape was not observed, since no model ran. When a finished job
has no gallery item, Generate names the generated files in its error.

### Model search

`wangp_models(action="search")` pages with `cursor` and `next_cursor`, up to 100
rows a page. A search with a `query` returns full rows including
`media_inputs`. A search without one returns compact rows (`model_type`, `name`
and sizes), so ListModels reads `wangp_model(action="capabilities")` for each.
`filters` takes `main_output`, `inputs` and `capabilities` (a list). The live
server listed 291 models: 173 with a video output, 16 with a 3D output.

Asynchronous jobs are off by default on a headless server, so it must be started
with `--mcp-async`. `--mcp-webui` always allows them.

A running job snapshot carries its latest `progress` at the top level, with no
`events` by default. A finished one keeps `done` and `result` and adds `status`
(`done`, `error` or `interrupted`). Upload tickets stay under
`/wangp_api/gallery/upload/`. Download tickets moved to
`/wangp_api/files/download/`, and the client accepts both routes.

## API v1

Used by servers before API v2, and by `--mcp-api-version 1`. The combined image's
pinned commit below speaks this API.

Every item below was resolved by reading the Wan2GP source at commit
`362c3467a70e1136ceb52eec95907205a8f88543`. On 1 November 2026 this package also
completed generations against that commit, with both video nodes, using
`ti2v_2_2_fastwan`. The remaining shapes are source-derived.

Line references point into the Wan2GP checkout, not into this repository. This
package never imports Wan2GP; it only speaks to it over HTTP.

## What had to be discovered, and where it is answered

| Question | Section | Pinned fixture |
| --- | --- | --- |
| Input schema of `wangp_generate.source` | [`wangp_generate`](#wangp_generatesource-waitfalse-timeout_snone-event_limitnone) | `tests/fixtures/job_submitted.json` |
| Shape `wangp_get_job` returns | [Job snapshot](#job-snapshot-what-wangp_get_jobjob_id-event_limit-returns) | `job_running.json`, `job_done.json`, `job_failed.json`, `job_cancelled.json` |
| How the upload PUT URL wants the body | [`wangp_create_gallery_upload`](#wangp_create_gallery_uploadfilename) | `gallery_upload_ticket.json`, `gallery_upload_result.json` |
| What `wangp_create_gallery_download` returns | [`wangp_create_gallery_download`](#wangp_create_gallery_downloadmedia_id) | `gallery_download_ticket.json`, `tiny.mp4` |
| `model_type` strings for Wan 2.1 and 2.2 T2V and I2V | [`model_type` strings](#model_type-strings) | `models.json`, `model_defaults_t2v_2_2.json`, `model_defaults_i2v_2_2.json` |
| `image_prompt_type` for an image-to-video run | [`image_prompt_type`](#image_prompt_type-for-an-image-to-video-run) | asserted in `tests/test_settings.py` |
| How nodetool-core signals cancellation | [Cancellation](#how-nodetool-signals-cancellation) | asserted in `tests/test_client.py` |

Every row was answered by reading source, not by calling a server.

## Transport

Launch the server one of two ways:

```bash
python wgp.py --mcp --mcp-transport streamable-http --mcp-host 127.0.0.1 --mcp-port 7866 \
  --config <config dir> --output-dir <output dir>

python -m shared.mcp_server --root <WanGP repo> --output-dir <dir> \
  --transport streamable-http --host 127.0.0.1 --port 7866 --job-event-limit 20
```

MCP clients connect to `http://<host>:<port>/mcp` (`docs/API.md:378`). The path
is fixed: FastMCP's streamable-HTTP app mounts there, and the launcher sets
`json_response=True` and `stateless_http=True` for this transport
(`shared/mcp_server.py:1576-1578`). Stateless means the server issues no
`mcp-session-id`, so the client never opens the server-to-client SSE stream.

`--job-event-limit` exists only on `python -m shared.mcp_server`
(`shared/mcp_server.py:1592`). The `wgp.py --mcp` path does not forward it
(`wgp.py:13741-13755`), so it uses the default of 20 events per snapshot.

The media transfer routes live on the same origin, one level up from `/mcp`:
`/wangp_api/gallery/upload/{token}` and `/wangp_api/gallery/download/{token}`
(`shared/mcp_server.py:1129`, `:1163`). Both tools return **relative** URLs, so a
client must resolve them against the MCP server origin (`docs/API.md:391`).

This package uses a safe 512 MiB default limit for each media transfer. The
shared node field `max_media_bytes` lets a workflow lower or raise that limit,
validated from 1 byte through the explicit 8 GiB client ceiling. The HTTP
operation timeout remains 30 seconds, while the MCP SSE read timeout is at least
300 seconds (or the node's generation timeout) so a long generation does not
close an otherwise healthy session. The outer generation deadline still bounds
job polling.

## `wangp_generate(source, wait=False, timeout_s=None, event_limit=None)`

Declared at `shared/mcp_server.py:1513`.

- `source` is an inline value, never a path. It accepts a settings dict, a task
  dict, a manifest dict, or a list of task dicts (`shared/mcp_server.py:1517`).
  This package always sends a single settings dict.
- `wait=False` returns as soon as the job is queued. `wait=True` blocks on
  `record.job.result(timeout=timeout_s)` before snapshotting
  (`shared/mcp_server.py:1523-1526`). This package uses `wait=False` and polls,
  so progress can reach the NodeTool UI.
- `timeout_s` applies only when `wait=True`.
- `event_limit` caps how many recent events the returned snapshot carries. It
  falls back to the server's `--job-event-limit`
  (`shared/mcp_server.py:1525`).
- The return value is a **job snapshot**, the same shape `wangp_get_job`
  returns, so `job_id` comes back from the submit call itself.

Media-valued settings are resolved server-side before submission. The keys that
get this treatment are `image_start`, `image_end`, `image_refs`, `image_guide`,
`image_mask`, `video_guide`, `video_guide2`, `video_mask`, `video_source`,
`audio_guide`, `audio_guide2`, `audio_source`, `replace_voice_sample`,
`replace_voice_sample2` and `custom_guide` (`shared/mcp_server.py:79-84`). Each
value must be a gallery media id, that is a string starting with `visual:` or
`audio:` (`shared/mcp_server.py:605-606`). A filesystem path raises
`PermissionError` unless the server was started with
`--mcp-allow-read-file-system` (`shared/mcp_server.py:616-617`). This package
never sends a path.

## Job snapshot: what `wangp_get_job(job_id, event_limit)` returns

Built by `_JobRecord.snapshot` (`shared/mcp_server.py:1050-1071`):

```json
{
  "job_id": "3d9a1c0e5b7f4a2d8c6e0f1a2b3c4d5e",
  "done": false,
  "cancel_requested": false,
  "webui_submission_ready": false,
  "webui_load_queue_token": "",
  "created_at": 1710000000.0,
  "updated_at": 1710000004.0,
  "events": [],
  "result": null
}
```

There is no single `status` string. Terminal state is the boolean `done`, and
success is `result.success`. `result` stays `null` until the job finishes.

Each event is `{"kind", "timestamp", "data"}` (`shared/mcp_server.py:183-188`).
Known kinds are `started`, `progress`, `preview`, `stream`, `status`, `info`,
`output`, `refresh_models`, `completed` and `error`
(`shared/api_cli.py:32-224`, `docs/API.md:766-788`).

A `progress` event's `data` is a `ProgressUpdate` flattened by dataclass
(`shared/api.py:178-186`):

```json
{"phase": "denoising", "status": "Denoising", "progress": 40,
 "current_step": 12, "total_steps": 30, "raw_phase": "Denoising", "unit": null}
```

`progress` is 0-100. `current_step` and `total_steps` are null in phases that do
not step (`shared/api.py:1001-1004`).

`result` is a `GenerationResult` dict (`shared/mcp_server.py:170-180`) with an
extra `gallery_items` list the snapshot adds for the generated files
(`shared/mcp_server.py:1058-1060`):

```json
{
  "success": true,
  "cancelled": false,
  "generated_files": ["/home/user/wan2gp/outputs/clip_001.mp4"],
  "errors": [],
  "total_tasks": 1, "successful_tasks": 1, "failed_tasks": 0,
  "artifacts": [],
  "gallery_items": [{"media_id": "visual:9f8e7d6c5b4a", "media_type": "video", "filename": "clip_001.mp4", "...": "..."}]
}
```

Each entry in `errors` is `{"message", "task_index", "task_id", "stage",
"cancelled"}` (`shared/mcp_server.py:160-167`).

`gallery_items` is how this package gets from a finished job to downloadable
bytes: take the first item's `media_id` and hand it to
`wangp_create_gallery_download`. Reading `generated_files` off disk would only
work when NodeTool and Wan2GP share a filesystem, so this package does not.

## `wangp_cancel_job(job_id, event_limit=None)`

`shared/mcp_server.py:1534`. It calls `job.cancel()` and returns a snapshot.
Cancellation is cooperative: the job keeps running until the model reaches a
checkpoint, then finishes with `result.success == false` and a cancellation
entry in `result.errors` whose `stage` is `cancelled`
(`shared/api.py:504-509`, `shared/api.py:262-267`, `docs/API.md:1055-1062`).

## `wangp_create_gallery_upload(filename)`

`shared/mcp_server.py:1431`, implemented at `shared/mcp_server.py:739-747`.
Registered only when the transport is not stdio
(`shared/mcp_server.py:1125`, `:1579`).

Returns:

```json
{"upload_url": "/wangp_api/gallery/upload/<32 hex>", "method": "PUT",
 "filename": "start.png", "expires_in_seconds": 600, "max_bytes": 8589934592}
```

`filename` must carry a supported extension or the tool raises
(`shared/mcp_server.py:741-742`). The accepted sets are
`.png .jpg .jpeg .webp .bmp .gif .tif .tiff` for images,
`.mp4 .mov .mkv .webm .avi` for video and
`.wav .mp3 .aac .m4a .flac .ogg .opus` for audio
(`shared/mcp_server.py:31-33`).

The upload itself is a plain `PUT` of the **raw file bytes** as the request
body, streamed (`shared/mcp_server.py:1145-1152`). No multipart, no JSON envelope,
no required content type. `Content-Length` is checked against the 8 GiB cap when
present (`shared/mcp_server.py:1136-1144`). The token is one-use: it is popped on the
first request (`shared/mcp_server.py:749-752`) and expires after 600 seconds
(`shared/mcp_server.py:23`).

A successful upload returns the registered gallery record plus a status:

```json
{"status": "uploaded", "size": 137, "media_id": "visual:0a1b2c3d4e5f",
 "gallery": "visual", "media_type": "image", "filename": "start.png",
 "description": "...", "source": "WanGP", "selected": true, "in_gallery": true}
```

(`shared/mcp_server.py:1160`, record shape at `shared/mcp_server.py:360-380`.)

**`media_id` is the value to pass as `image_start`.** Its format is
`<gallery>:<first 12 hex of a sha1 over the normalized path>` where gallery is
`visual` or `audio` (`shared/utils/gallery_media.py:18`). Upload failures return
JSON with an `error` key and status 400 or 413
(`shared/mcp_server.py:1153-1159`).

## `wangp_create_gallery_download(media_id)`

`shared/mcp_server.py:1437`, implemented at `shared/mcp_server.py:754-761`.
Returns:

```json
{"media_id": "visual:9f8e7d6c5b4a",
 "download_url": "/wangp_api/gallery/download/<32 hex>",
 "filename": "clip_001.mp4", "media_type": "video",
 "size": 1756, "expires_in_seconds": 600}
```

`GET` on that URL streams the file with its guessed content type
(`shared/mcp_server.py:1163-1170`). The token is one-use and the media must already
be registered in a gallery; an unknown `media_id` raises `KeyError`
(`shared/mcp_server.py:390`). The client streams the response into a bounded
spooled temporary file, enforcing the effective ticket/node limit on both the
advertised length and live chunks, then reads the bytes once for NodeTool.

## `wangp_models(query, filters, limit, offset)`

`shared/mcp_server.py:1188`. `filters` accepts only `family`,
`base_model_type`, `finetune`, `model_type`, `main_output`, `inputs` and `name`;
anything else raises (`shared/mcp_server.py:93-96`). `limit` is clamped to 1-50.
Returns:

```json
{"models": [...], "total": 4, "returned": 4, "offset": 0, "has_more": false}
```

`wangp_model(model_type, view)` (`shared/mcp_server.py:1203`) returns the
compact schema by default, the raw definition with `view="definition"`, or the
pristine generation defaults with `view="defaults"`. An unknown `model_type`
raises `KeyError` (`shared/mcp_server.py:116`).

## `model_type` strings

A `model_type` is the stem of a JSON file under `defaults/`:
`model_type = os.path.basename(file_path)[:-5]` (`wgp.py:3295`, discovery at
`wgp.py:3280-3281`). The Wan 2.1 and 2.2 video models are therefore:

| `model_type` | Name | `architecture` |
| --- | --- | --- |
| `t2v` | Wan2.1 Text2video 14B | `t2v` |
| `t2v_1.3B` | Wan2.1 Text2video 1.3B | `t2v` |
| `t2v_2_2` | Wan2.2 Text2video 14B | `t2v_2_2` |
| `i2v` | Wan2.1 Image2video 480p 14B | `i2v` |
| `i2v_720p` | Wan2.1 Image2video 720p 14B | `i2v` |
| `i2v_2_2` | Wan2.2 Image2video 14B | `i2v_2_2` |
| `ti2v_2_2` | Wan2.2 TextImage2video 5B | `ti2v_2_2` |

Sources: `defaults/t2v.json`, `defaults/t2v_1.3B.json`, `defaults/t2v_2_2.json`,
`defaults/i2v.json`, `defaults/i2v_720p.json`, `defaults/i2v_2_2.json`,
`defaults/ti2v_2_2.json`.

This package defaults to `t2v_2_2` for text to video and `i2v_2_2` for image to
video. Which of these a given server actually offers depends on what its
`defaults/` directory holds, so the node descriptions point at `wangp_models`
for the live list.

## `image_prompt_type` for an image-to-video run

Set `image_prompt_type` to `"S"` and put the uploaded `media_id` in
`image_start`.

`S` means "use `image_start` as the starting image"
(`docs/SETTINGS.md:190`). Wan2GP's own factory defaults do exactly this: for any
i2v-class model whose allowed flags contain `S`, it sets
`ui_defaults["image_prompt_type"] = "S"`
(`models/wan/wan_handler.py:1257-1258`).

The allowed flags for the Wan i2v models are `SEVL`
(`models/wan/wan_handler.py:974-975`), where `E` adds `image_end`, `V` continues
from `video_source`, and `L` continues from the last generated video. The
t2v models allow `TVL` only (`models/wan/wan_handler.py:964-965`), so they take no
`image_start`. Flags outside a model's allowed set are stripped during settings
migration (`wgp.py:3181-3185`).

## Settings keys this package writes

| Key | Value |
| --- | --- |
| `model_type` | one of the ids above |
| `prompt` | text |
| `negative_prompt` | non-empty text; omitted by the dedicated video nodes when blank |
| `resolution` | `"<width>x<height>"`, e.g. `"832x480"` |
| `video_length` | frame count as int, or a duration string like `"10s"` |
| `force_fps` | fps; accepted as `24` or `"24"` (`docs/API.md:517`) |
| `num_inference_steps` | int |
| `seed` | int, `-1` for random |
| `image_start` | gallery `media_id` |
| `image_prompt_type` | `"S"` for an image-to-video run |
| `activated_loras` | list of ids from `wangp_list_loras` |
| `loras_multipliers` | matching weights as one space separated string |

TextToVideo and ImageToVideo omit an empty `negative_prompt` so Wan2GP fills in
the model's default. An explicit empty string would override that default in
Wan2GP's settings merge. `Generate` retains explicit values in its user settings,
including an empty string. The default text-to-video request is recorded in
`tests/fixtures/text_to_video_default_request.json`.

`activated_loras` values must not be absolute paths or contain `..`; the server
raises `PermissionError` otherwise (`shared/mcp_server.py:653-658`).

`loras_multipliers` is documented as a string, space or newline separated, with
`#` starting a comment line (`docs/SETTINGS.md:177`). `preparse_loras_multipliers`
also accepts a list (`shared/utils/loras_mutipliers.py:4-6`), but this package
sends the documented form: one space separated string, in the order of
`activated_loras`.

`_api` is reserved API metadata, not a generation setting
(`docs/API.md:556-570`). This package strips it from user-supplied settings and
does not use `_api={"return_media": true}`, because it fetches output bytes
through the gallery download route instead.

## How NodeTool signals cancellation

`ProcessingContext.is_cancelled` is a property, and
`ProcessingContext.raise_if_cancelled()` raises `NodeCancelledError` when it is
true (`nodetool-core` `src/nodetool/workflows/processing_context.py:104`,
`:352`, `:361`). The base context always returns `False`; execution environments
that support cancellation override the property. Cancellation is cooperative, so
a node must call `raise_if_cancelled()` inside its own loop.

The nodes in this package call it once per poll and, when it raises, send
`wangp_cancel_job` before letting `NodeCancelledError` propagate. The node's
`timeout_seconds` is an overall generation deadline, not an HTTP request
timeout: each MCP/media request uses a short 30-second timeout, and each poll
 is bounded by the remaining generation deadline. A timeout or poll failure
 triggers a bounded best-effort `wangp_cancel_job` request.

## Output media and transfer safety

The first `gallery_items` entry determines the output. `Generate` dispatches
its bytes to `image_from_bytes`, `video_from_bytes`, or `audio_from_bytes` based
on the entry's validated `media_type` (`image`, `video`, or `audio`). The
TextToVideo and ImageToVideo nodes require `media_type="video"` and reject
other output types.

Upload and download tickets must provide relative URLs under the matching
`/wangp_api/gallery/{upload,download}/` route on the MCP server's origin. The
client requires PUT for uploads and GET for downloads, disables redirects, and
rejects non-2xx responses. Transfers are bounded by the ticket's `max_bytes` or
`size` value and a hard 8 GiB cap (with a configurable lower client limit);
downloads enforce the limit from Content-Length and while streaming bytes.

## Still unconfirmed

- Every shape above, since no live server answered any of these calls.
- Whether `structuredContent` on a `tools/call` response carries a dict return
  value verbatim or wrapped. The client handles both: it unwraps a lone
  `result` key and otherwise takes the object as-is, and falls back to parsing
  the JSON text block.
- Which `model_type` ids a particular install exposes. `defaults/` is the
  registry, and a user can add finetunes under `finetunes/`
  (`wgp.py:3281`).

## Reference video adapter

The combined worker targets WanGP commit `362c3467a70e1136ceb52eec95907205a8f88543`.
Reference support is discovered from `session.list_model_metadata()`. The
adapter uses the pinned metadata fields `media_inputs.image.reference` (or its
single or multiple reference roles), `media_inputs.video.control`, and the
declared `setting_values` choices for `image_ref_choices`,
`guide_custom_choices`, and `audio_prompt_type.sources`.

Reference images are sent as ordered `image_refs`. One or two reference videos
are sent as `video_guide` and `video_guide2`, selecting the advertised `V-U` or
`V+-U` mode. WanGP's `GV` choice is generic control video and is excluded.
Unsupported media kinds, counts, missing models, and missing task
support fail before `run_task`. Audio is enabled only when a reference video
is present and WanGP advertises a `K` audio source choice.

### Moving the combined pin to v19.02

`Dockerfile.combined` still pins `362c3467`. Nothing here built the image. On 1
November 2026 the adapter in `combined/` ran against a WanGP v19.02 checkout
(`616e605`) in its own interpreter, on a machine without a GPU, with CUDA
queries stubbed outside the WanGP tree. No model loaded and `run_task` was not
called.

What still works:

- `shared.api.init`, `list_model_metadata`, `get_model_metadata`, `run_task`,
  `GenerationResult` and `GeneratedArtifact` keep the names and fields the
  adapter uses. `prepare_model.py`'s calls into `wgp` (`get_model_def`,
  `get_model_filename`, `get_model_recursive_prop`, `download_models` and the
  quantization globals) keep compatible signatures.
- The `models` operation returned 172 video models (170 text to video, 101
  image to video, 69 reference to video), 139 image, 17 speech and 17 music
  models. `ltx2_25_22B_alpha_gen` is the one video model it leaves out.
- `_settings` built 612 requests, one for each model and operation, without an
  error. 493 of them passed `wangp_validate` once their file paths were swapped
  for gallery ids.

What breaks or degrades:

1. 66 requests fail because the model needs `image_refs`: text to video or
   text to image on reference-only models such as `phantom_14B`, `standin`,
   `lynx`, `kiwi_edit`, `ltx2_25_22B_msr` and the Flux Kontext and Qwen edit
   models. WanGP's `text_to_video` capability does not say that a reference is
   required, so the adapter offers tasks those models cannot run.
2. Models with locked resolutions (`evoke_turbo`, `flux_dev_umo`,
   `k5_lite_t2v_10s_distil_sparse`, `k5_pro_t2v_10s_sft_sparse`) reject the
   adapter's tier conversion, such as `480p` to `853x480`. The adapter ignores
   `allowed_resolutions`.
3. `wanmove` fails without `custom_guide`, which the provider protocol has no
   field for. `yue2` ignores its score in the default mode.
4. Text to speech sends `audio_guide` whenever a reference voice is attached.
   `qwen3_tts_customvoice` and `qwen3_tts_voicedesign` take none, and MCP
   validation rejects it. `run_task` may ignore it instead. That was not run.
5. v19.02 vendors mmgp 4.5.0 in its `mmgp/` folder instead of installing
   `mmgp==3.7.14` from PyPI. The image's separate `MMGP_COMMIT` checkout, which
   supplies the mmgp licence and attribution, would no longer describe the
   mmgp code that runs. The attribution must point at the vendored copy.
6. The requirements add `comfy-kitchen==0.2.35` and `optimum-quanto==0.2.7`,
   which mmgp needed from PyPI before. Both commits ask for the CUDA 13 nightly
   `onnxruntime-gpu` while the image installs CUDA 12.8 PyTorch. Whether the
   new set installs in the image is untested.
7. The adapter uses none of the inputs added since the pin: reference videos
   (`media_inputs.video.reference`, 12 video models), end images, audio-driven
   video and 3D outputs.

These are not adapter faults: 16 requests to `animate`, `scail`, `mocha`,
`steadydancer` and four other models fail inside WanGP with
`could not convert string to float: 'control'`, which a bare
`{"model_type": "scail", "prompt": "x"}` reproduces. The remaining failures
came from the probe request itself: 17 frames is too short for a 3-second voice
clip and for Ovi's sliding window.
