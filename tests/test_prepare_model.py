from types import SimpleNamespace

from combined.prepare_model import _model_files, _prepare


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
