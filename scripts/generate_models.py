#!/usr/bin/env python3
"""Regenerate the predefined model files of the Wiro AI model provider.

- LLMs come from the gateway catalog (GET https://llm.wiro.ai/v1/models).
- Text to speech and speech to text models come from the Run API catalog
  (Tool/List and Tool/Detail on https://api.wiro.ai/v1).

All of these calls are free. Each model gets one YAML file under
models/wiro/models/<type>/, plus a _position.yaml with the display order.

    WIRO_API_KEY=... python scripts/generate_models.py

Signature-authenticated projects also set WIRO_API_SECRET.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "models" / "wiro"
MODELS_DIR = PLUGIN / "models"
sys.path.insert(0, str(PLUGIN))

from models._wiro import (  # noqa: E402
    CATALOG_TIMEOUT,
    GATEWAY_URL,
    catalog_headers,
    model_schema,
)
from models._wiro_run import RunClient, is_realtime, stt_schema, tts_schema  # noqa: E402

# Vendors listed first in Dify's model picker. Others follow alphabetically.
VENDOR_ORDER = ["openai", "claude", "google", "xai", "deepseek", "moonshot", "glm", "bytedance", "qwen"]

# Name parts kept out of the predefined lists. Such models can still be added by ID.
SKIP_NAME_PARTS = ("uncensored", "obliterated", "heretic")


class _Dumper(yaml.SafeDumper):
    def ignore_aliases(self, data) -> bool:  # write repeated lists out in full
        return True


def _str_presenter(dumper: yaml.SafeDumper, value: str) -> yaml.Node:
    return dumper.represent_scalar("tag:yaml.org,2002:str", value)


_Dumper.add_representer(str, _str_presenter)


def credentials() -> dict:
    return {"api_key": os.environ["WIRO_API_KEY"], "api_secret": os.environ.get("WIRO_API_SECRET", "")}


def write_models(kind: str, schemas: list[dict]) -> None:
    folder = MODELS_DIR / kind
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("*.yaml"):
        old.unlink()
    for schema in schemas:
        path = folder / (schema["model"].replace("/", "__") + ".yaml")
        path.write_text(yaml.dump(schema, Dumper=_Dumper, sort_keys=False, allow_unicode=True), encoding="utf-8")
    position = [schema["model"] for schema in schemas]
    (folder / "_position.yaml").write_text(yaml.dump(position, Dumper=_Dumper, sort_keys=False), encoding="utf-8")
    print(f"wrote {len(schemas)} {kind} models")


def llm_schemas() -> list[dict]:
    response = requests.get(
        f"{GATEWAY_URL}/models",
        params={"limit": 1000},
        headers=catalog_headers(credentials()),
        timeout=CATALOG_TIMEOUT,
    )
    response.raise_for_status()
    body = response.json()
    if body.get("has_more"):
        raise SystemExit("The catalog has more than 1000 models; add paging to this script.")

    def sort_key(entry: dict) -> tuple:
        vendor = entry["id"].split("/", 1)[0]
        rank = VENDOR_ORDER.index(vendor) if vendor in VENDOR_ORDER else len(VENDOR_ORDER)
        return (rank, vendor, -int(entry.get("created") or 0), entry["id"])

    catalog = [
        entry
        for entry in body["data"]
        if "chat" in ((entry.get("capabilities") or {}).get("endpoints") or [])
        and not any(part in entry["id"] for part in SKIP_NAME_PARTS)
    ]
    return [model_schema(entry) for entry in sorted(catalog, key=sort_key)]


def run_api_schemas(client: RunClient, category: str, build) -> list[dict]:
    """Models of one Run API category, most used first, that the builder accepts."""
    rows = (
        client.post(
            "/Tool/List",
            {"start": "0", "limit": "100", "categories": [category], "hideworkflows": True, "summary": True},
        ).get("tool")
        or []
    )
    ranked = sorted(rows, key=lambda t: -int((t.get("taskstat") or {}).get("runcount") or 0))
    schemas = []
    for row in ranked:
        model_id = f"{row.get('cleanslugowner')}/{row.get('cleanslugproject')}"
        if any(part in model_id for part in SKIP_NAME_PARTS) or category not in (row.get("categories") or []):
            continue
        detail = client.model_detail(model_id)
        if is_realtime(detail, model_id):
            continue
        schema = build(model_id, detail)
        if schema:
            schemas.append(schema)
    return schemas


def main() -> None:
    write_models("llm", llm_schemas())
    client = RunClient(credentials())
    write_models("tts", run_api_schemas(client, "text-to-speech", tts_schema))
    write_models("speech2text", run_api_schemas(client, "speech-to-text", stt_schema))


if __name__ == "__main__":
    main()
