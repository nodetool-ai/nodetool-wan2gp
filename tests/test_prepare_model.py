import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from combined.prepare_model import (  # noqa: E402
    _configure_wangp_root,
    _model_files,
    _prepare,
)


class FakeWanGP:
    transformer_quantization = "int8"
    transformer_dtype_policy = "bf16"
    text_encoder_quantization = "fp8"

    def __init__(self) -> None:
        self.downloads: list[tuple] = []

    def get_model_def(self, model_type: str):
        assert model_type == "wan-test"
        return {
            "URLs": ["https://example.test/main.safetensors"],
            "URLs2": ["https://example.test/secondary.safetensors"],
            "modules": [
                {
                    "URLs": ["https://example.test/module-a.safetensors"],
                    "URLs2": ["https://example.test/module-b.safetensors"],
                }
            ],
            "text_encoder_URLs": ["https://example.test/text.safetensors"],
            "text_encoder_folder": "text_encoder",
        }

    def get_model_filename(self, *args, **kwargs):
        urls = kwargs.get("URLs")
        if urls:
            return urls[0]
        if kwargs.get("submodel_no") == 2:
            return "https://example.test/secondary.safetensors"
        return "https://example.test/main.safetensors"

    def get_model_recursive_prop(self, _model_type, prop, **_kwargs):
        return self.get_model_def("wan-test").get(prop, [])

    def download_models(self, *args, **kwargs):
        self.downloads.append((*args, kwargs))


def test_configure_wangp_root_adds_copied_checkout_to_import_path(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "shared").mkdir()
    monkeypatch.setenv("WANGP_ROOT", str(tmp_path))
    monkeypatch.setattr(sys, "path", list(sys.path))

    root = _configure_wangp_root()

    assert root == tmp_path.resolve()
    assert sys.path[0] == str(tmp_path.resolve())


def test_model_files_match_wangp_primary_secondary_and_modules() -> None:
    module = FakeWanGP()

    selected = _model_files(SimpleNamespace(module=module), "wan-test")

    assert selected == [
        ("https://example.test/main.safetensors", 0, 1),
        ("https://example.test/secondary.safetensors", 0, 2),
        ("https://example.test/module-a.safetensors", 1, 1),
        ("https://example.test/module-b.safetensors", 1, 2),
    ]


def test_prepare_calls_wangp_downloads_without_loading_model() -> None:
    module = FakeWanGP()

    _prepare(SimpleNamespace(module=module), "wan-test")

    calls = [(args[0], args[2], args[3]) for args in module.downloads]
    assert calls == [
        ("https://example.test/main.safetensors", 0, 1),
        ("https://example.test/secondary.safetensors", 0, 2),
        ("https://example.test/module-a.safetensors", 1, 1),
        ("https://example.test/module-b.safetensors", 1, 2),
        ("https://example.test/text.safetensors", 2, -1),
    ]


def test_prepare_adapter_reserves_stdout_for_json_protocol() -> None:
    root = Path(__file__).resolve().parents[1]
    code = """
import os
from combined.prepare_model import _Emitter, _reserve_stdout_for_protocol

emitter = _Emitter()
_reserve_stdout_for_protocol()
os.write(1, b"upstream noise\\n")
emitter.send({"status": "completed"})
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=root,
        text=True,
        capture_output=True,
        env={**os.environ, "PYTHONPATH": str(root)},
        check=True,
    )
    assert json.loads(result.stdout) == {"status": "completed"}
    assert "upstream noise" in result.stderr
