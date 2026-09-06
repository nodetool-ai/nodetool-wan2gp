#!/usr/bin/env python
"""Run one small TextToVideo generation against a real Wan2GP server.

There is no NodeTool server involved. This script builds a ProcessingContext by
hand, runs the node, prints the settings it sent and every progress event, and
writes the resulting clip into the workspace directory.

Start Wan2GP first, in its own conda environment, with the MCP server on:

    conda activate wan2gp
    cd /path/to/Wan2GP
    python wgp.py --mcp --mcp-transport streamable-http \\
        --mcp-host 127.0.0.1 --mcp-port 7866

Then, in the nodetool environment:

    python scripts/smoke.py

The run is deliberately cheap: 512x288, 17 frames, 4 denoising steps. Expect a
few seconds of video and a first run that spends most of its time downloading
model weights.

Exit code 0 means the clip arrived. Any other code means it did not.
"""

from __future__ import annotations

import argparse
import asyncio
import queue
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any

# Make `src/` importable when this script runs from a checkout that was never
# installed. An installed package shadows nothing, because the path comes last.
sys.path.append(str(Path(__file__).resolve().parent.parent / "src"))

WIDTH = 512
HEIGHT = 288
NUM_FRAMES = 17
NUM_INFERENCE_STEPS = 4

DEFAULT_PROMPT = "A paper boat drifts down a rain gutter, seen from just above the water."


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser. Importable so a test can check the flags."""
    parser = argparse.ArgumentParser(
        prog="smoke.py",
        description=(
            "Run one small Wan2GP text-to-video generation and save the clip. "
            "Needs a Wan2GP server started with --mcp --mcp-transport streamable-http."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Start Wan2GP first:\n"
            "  python wgp.py --mcp --mcp-transport streamable-http "
            "--mcp-host 127.0.0.1 --mcp-port 7866"
        ),
    )
    parser.add_argument(
        "--server-url",
        default=None,
        help="MCP endpoint of the Wan2GP server. Defaults to WAN2GP_MCP_URL, "
        "then to http://127.0.0.1:7866/mcp.",
    )
    parser.add_argument(
        "--model-type",
        default=None,
        help="Wan2GP model id to run. Defaults to the node default. "
        "Call wangp_models on your server for the ids it offers.",
    )
    parser.add_argument(
        "--prompt",
        default=DEFAULT_PROMPT,
        help="Prompt to generate from.",
    )
    parser.add_argument(
        "--workspace-dir",
        default=None,
        help="Where to write the clip. Defaults to a new temporary directory.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=1800,
        help="How long to wait for the generation before giving up.",
    )
    return parser


def make_node(args: argparse.Namespace):
    """Build the TextToVideo node this script runs."""
    from nodetool.nodes.wan2gp.text_to_video import TextToVideo

    fields: dict[str, Any] = {
        "id": "smoke",
        "prompt": args.prompt,
        "width": WIDTH,
        "height": HEIGHT,
        "num_frames": NUM_FRAMES,
        "num_inference_steps": NUM_INFERENCE_STEPS,
        "timeout_seconds": args.timeout_seconds,
    }
    if args.server_url:
        fields["server_url"] = args.server_url
    if args.model_type:
        fields["model_type"] = args.model_type
    return TextToVideo(**fields)


def drain(message_queue: "queue.Queue[Any]") -> None:
    """Print every message the node has posted so far."""
    from nodetool.workflows.types import NodeProgress

    while True:
        try:
            message = message_queue.get_nowait()
        except queue.Empty:
            return
        if isinstance(message, NodeProgress):
            print(f"progress: {message.progress}/{message.total}", flush=True)
        else:
            print(f"message: {message}", flush=True)


def flatten(error: BaseException) -> list[BaseException]:
    """Return the leaf exceptions of an error, unwrapping exception groups.

    The MCP streamable-HTTP client runs its transport in a task group, so a
    connection refusal reaches the caller inside a BaseExceptionGroup.
    """
    if isinstance(error, BaseExceptionGroup):
        leaves: list[BaseException] = []
        for inner in error.exceptions:
            leaves.extend(flatten(inner))
        return leaves
    return [error]


def report_failure(error: BaseException, server_url: str) -> None:
    """Print one clear line about a failed run, then the detail."""
    import httpx

    leaves = flatten(error)
    connect = [leaf for leaf in leaves if isinstance(leaf, httpx.ConnectError)]
    if connect:
        print(
            f"\nFAILED: cannot reach a Wan2GP MCP server at {server_url}.\n"
            "Start Wan2GP with:\n"
            "  python wgp.py --mcp --mcp-transport streamable-http "
            "--mcp-host 127.0.0.1 --mcp-port 7866\n"
            "or point this script at another server with --server-url.",
            file=sys.stderr,
        )
        return
    first = leaves[0] if leaves else error
    print(f"\nFAILED: {type(first).__name__}: {first}", file=sys.stderr)
    traceback.print_exception(error, file=sys.stderr)


async def run(args: argparse.Namespace) -> int:
    """Run the node once. Return the process exit code."""
    from nodetool.workflows.processing_context import ProcessingContext

    workspace = args.workspace_dir or tempfile.mkdtemp(prefix="wan2gp-smoke-")
    Path(workspace).mkdir(parents=True, exist_ok=True)
    context = ProcessingContext(workspace_dir=workspace)

    node = make_node(args)
    print(f"server:    {node.server_url}")
    print(f"workspace: {workspace}")
    print("settings sent to wangp_generate:")
    for key, value in node.build_settings().items():
        print(f"  {key}: {value!r}")
    print("", flush=True)

    task = asyncio.create_task(node.process(context))
    while not task.done():
        drain(context.message_queue)
        await asyncio.sleep(0.2)
    drain(context.message_queue)

    try:
        video = await task
    except BaseException as error:  # noqa: BLE001 - the script reports and exits
        report_failure(error, node.server_url)
        return 1

    data = await context.asset_to_bytes(video)
    output = Path(workspace) / "smoke.mp4"
    output.write_bytes(data)
    print(f"\nOK: wrote {len(data)} bytes to {output}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
