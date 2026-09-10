# The Wan2GP MCP contract this package depends on

Every item below was resolved by reading the Wan2GP source at commit
`362c3467a70e1136ceb52eec95907205a8f88543`. **None of it was
confirmed against a live server.** There was no Wan2GP instance and no GPU on
the machine where this package was written. Treat each shape as source-derived
until someone runs `scripts/smoke.py` against a real server.

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
(`shared/mcp_server.py:390`).

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
| `negative_prompt` | text |
| `resolution` | `"<width>x<height>"`, e.g. `"832x480"` |
| `video_length` | frame count as int, or a duration string like `"10s"` |
| `force_fps` | fps; accepted as `24` or `"24"` (`docs/API.md:517`) |
| `num_inference_steps` | int |
| `seed` | int, `-1` for random |
| `image_start` | gallery `media_id` |
| `image_prompt_type` | `"S"` for an image-to-video run |
| `activated_loras` | list of ids from `wangp_list_loras` |
| `loras_multipliers` | matching weights as one space separated string |

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
`wangp_cancel_job` before letting `NodeCancelledError` propagate.

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
