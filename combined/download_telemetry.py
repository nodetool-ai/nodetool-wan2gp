"""Filesystem and process-I/O telemetry for opaque model downloads."""

from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, TypedDict


@dataclass(frozen=True)
class _FileState:
    allocated_bytes: int
    size_bytes: int
    modified_ns: int


class TelemetrySample(TypedDict):
    downloaded_bytes: int
    total_bytes: int
    downloaded_files: int
    total_files: int
    current_files: list[str]
    bytes_per_second: float
    seconds_since_activity: float
    elapsed_seconds: float
    free_bytes: int
    stalled: bool


def _allocated_bytes(stat: os.stat_result) -> int:
    blocks = getattr(stat, "st_blocks", None)
    if isinstance(blocks, int):
        return max(0, blocks * 512)
    return max(0, stat.st_size)


def _read_process_write_bytes(pid: int) -> int | None:
    try:
        text = Path(f"/proc/{pid}/io").read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    for line in text.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip() == "write_bytes":
            try:
                return max(0, int(value.strip()))
            except ValueError:
                return None
    return None


class DownloadTelemetry:
    """Measure download activity without intercepting downloader functions."""

    def __init__(
        self,
        roots: Iterable[str | os.PathLike[str]],
        *,
        pid: int,
        stall_seconds: float = 90.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if stall_seconds <= 0:
            raise ValueError("stall_seconds must be positive")
        self.roots = tuple(Path(root).resolve() for root in roots)
        if not self.roots:
            raise ValueError("at least one telemetry root is required")
        self.pid = pid
        self.stall_seconds = stall_seconds
        self._clock = clock
        self._files = self._snapshot_files()
        self._baseline_files = dict(self._files)
        self._baseline_process_bytes = _read_process_write_bytes(pid)
        self._last_process_bytes = self._baseline_process_bytes
        self._started_at = self._clock()
        self._sampled_at = self._started_at
        self._last_activity_at = self._started_at
        self._downloaded_bytes = 0

    def _snapshot_files(self) -> dict[Path, _FileState]:
        files: dict[Path, _FileState] = {}
        for root in self.roots:
            if not root.exists():
                continue
            stack = [root]
            while stack:
                directory = stack.pop()
                try:
                    entries = list(os.scandir(directory))
                except OSError:
                    continue
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            stat = entry.stat(follow_symlinks=False)
                            files[Path(entry.path)] = _FileState(
                                allocated_bytes=_allocated_bytes(stat),
                                size_bytes=max(0, stat.st_size),
                                modified_ns=max(0, stat.st_mtime_ns),
                            )
                    except OSError:
                        continue
        return files

    def _display_path(self, path: Path) -> str:
        for root in self.roots:
            try:
                return str(path.relative_to(root))
            except ValueError:
                continue
        return path.name

    def _free_bytes(self) -> int:
        values: list[int] = []
        for root in self.roots:
            probe = root
            while not probe.exists() and probe != probe.parent:
                probe = probe.parent
            try:
                values.append(shutil.disk_usage(probe).free)
            except OSError:
                continue
        return min(values) if values else 0

    def sample(self) -> TelemetrySample:
        """Return one monotonic activity sample in manager-compatible fields."""
        now = self._clock()
        files = self._snapshot_files()
        changed: list[Path] = []
        for path, state in files.items():
            previous = self._files.get(path)
            if previous is None or state != previous:
                changed.append(path)

        filesystem_delta = sum(
            max(0, state.allocated_bytes - self._baseline_files.get(path, _FileState(0, 0, 0)).allocated_bytes)
            for path, state in files.items()
        )
        process_bytes = _read_process_write_bytes(self.pid)
        process_delta = 0
        if process_bytes is not None and self._baseline_process_bytes is not None:
            process_delta = max(0, process_bytes - self._baseline_process_bytes)

        measured = max(filesystem_delta, process_delta)
        previous_downloaded = self._downloaded_bytes
        self._downloaded_bytes = max(self._downloaded_bytes, measured)
        process_moved = (
            process_bytes is not None
            and self._last_process_bytes is not None
            and process_bytes > self._last_process_bytes
        )
        if changed or process_moved or self._downloaded_bytes > previous_downloaded:
            self._last_activity_at = now

        elapsed = max(0.0, now - self._sampled_at)
        bytes_per_second = (
            max(0, self._downloaded_bytes - previous_downloaded) / elapsed
            if elapsed > 0
            else 0.0
        )
        quiet = max(0.0, now - self._last_activity_at)
        active_files = sorted(self._display_path(path) for path in changed)[:20]
        self._files = files
        self._last_process_bytes = process_bytes
        self._sampled_at = now

        return {
            "downloaded_bytes": self._downloaded_bytes,
            "total_bytes": 0,
            "downloaded_files": 0,
            "total_files": 0,
            "current_files": active_files,
            "bytes_per_second": round(bytes_per_second, 2),
            "seconds_since_activity": round(quiet, 2),
            "elapsed_seconds": round(max(0.0, now - self._started_at), 2),
            "free_bytes": self._free_bytes(),
            "stalled": quiet >= self.stall_seconds,
        }
