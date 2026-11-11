import os
import sys
from pathlib import Path

import pytest
import yaml

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT))

from dify_plugin.entities.model import AIModelEntity  # noqa: E402

from models.llm.llm import WiroLargeLanguageModel  # noqa: E402


def load_schemas() -> list[AIModelEntity]:
    files = sorted((PLUGIN_ROOT / "models" / "llm").glob("*.yaml"))
    return [
        AIModelEntity.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        for path in files
        if not path.name.startswith("_")
    ]


@pytest.fixture(scope="session")
def llm() -> WiroLargeLanguageModel:
    return WiroLargeLanguageModel(model_schemas=load_schemas())


class Credentials(dict):
    """A dict that never shows its values, so test reports cannot print the key."""

    def __repr__(self) -> str:
        return "<credentials hidden>"

    __str__ = __repr__


@pytest.fixture(scope="session")
def credentials() -> Credentials:
    key = os.environ.get("WIRO_API_KEY")
    if not key:
        pytest.skip("WIRO_API_KEY is not set; live tests are skipped")
    return Credentials(api_key=key, api_secret=os.environ.get("WIRO_API_SECRET", ""))
