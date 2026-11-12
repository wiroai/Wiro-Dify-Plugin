import importlib.util
import os
import sys
from pathlib import Path

import dify_plugin  # noqa: F401  (the SDK patches gevent; it must load before requests and ssl)
import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT))


class Credentials(dict):
    """A dict that never shows its values, so test reports cannot print the key."""

    def __repr__(self) -> str:
        return "<credentials hidden>"

    __str__ = __repr__


def load_class(relative_path: str, class_name: str):
    """Load a tool or provider class by file path, the way the plugin runtime does."""
    path = PLUGIN_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, class_name)


class FakeFile:
    """Stands in for a Dify file: the SDK's File loads .blob from Dify's file URL."""

    def __init__(self, blob: bytes, mime_type: str, filename: str) -> None:
        self.blob = blob
        self.mime_type = mime_type
        self.filename = filename
        self.extension = "." + filename.rsplit(".", 1)[-1]


@pytest.fixture(scope="session")
def credentials() -> Credentials:
    key = os.environ.get("WIRO_API_KEY")
    if not key:
        pytest.skip("WIRO_API_KEY is not set; live tests are skipped")
    return Credentials(api_key=key, api_secret=os.environ.get("WIRO_API_SECRET", ""))
