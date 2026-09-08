from pathlib import Path

from combined import download_telemetry as telemetry_module
from combined.download_telemetry import DownloadTelemetry


class Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


def test_observer_reports_growth_rate_and_stall(tmp_path: Path) -> None:
    clock = Clock()
    observer = DownloadTelemetry(
        [tmp_path], pid=999_999_999, stall_seconds=10, clock=clock
    )

    partial = tmp_path / "models--org--model" / "blob.incomplete"
    partial.parent.mkdir()
    partial.write_bytes(b"x" * 8192)
    clock.value = 2
    active = observer.sample()

    assert active["downloaded_bytes"] >= 8192
    assert active["bytes_per_second"] >= 4096
    assert active["current_files"] == ["models--org--model/blob.incomplete"]
    assert active["seconds_since_activity"] == 0
    assert active["stalled"] is False
    assert active["total_bytes"] == 0

    clock.value = 13
    stalled = observer.sample()
    assert stalled["downloaded_bytes"] == active["downloaded_bytes"]
    assert stalled["seconds_since_activity"] == 11
    assert stalled["stalled"] is True


def test_observer_uses_process_io_when_file_size_is_preallocated(
    tmp_path: Path, monkeypatch
) -> None:
    values = iter([1000, 5096])
    monkeypatch.setattr(
        telemetry_module,
        "_read_process_write_bytes",
        lambda _pid: next(values),
    )
    clock = Clock()
    observer = DownloadTelemetry([tmp_path], pid=42, clock=clock)

    clock.value = 1
    sample = observer.sample()

    assert sample["downloaded_bytes"] == 4096
    assert sample["bytes_per_second"] == 4096
    assert sample["stalled"] is False


def test_observer_does_not_follow_symlinks(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (outside / "secret.bin").write_bytes(b"secret")
    (tmp_path / "linked").symlink_to(outside, target_is_directory=True)
    observer = DownloadTelemetry([tmp_path], pid=999_999_999)

    sample = observer.sample()

    assert sample["downloaded_bytes"] == 0
    assert sample["current_files"] == []
