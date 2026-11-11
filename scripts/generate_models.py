#!/usr/bin/env python3
"""Regenerate the predefined model files of the Wiro AI model provider.

Reads the gateway catalog (GET https://llm.wiro.ai/v1/models, free to call) and
writes one YAML file per model to models/wiro/models/llm/, plus _position.yaml.

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
LLM_DIR = PLUGIN / "models" / "llm"
sys.path.insert(0, str(PLUGIN))

from models._wiro import (  # noqa: E402
    CATALOG_TIMEOUT,
    GATEWAY_URL,
    catalog_headers,
    model_schema,
)

# Vendors listed first in Dify's model picker. Others follow alphabetically.
VENDOR_ORDER = ["openai", "claude", "google", "xai", "deepseek", "moonshot", "glm", "bytedance", "qwen"]

# Name parts kept out of the predefined list. Such models can still be added by ID.
SKIP_NAME_PARTS = ("uncensored", "obliterated", "heretic")


class _Dumper(yaml.SafeDumper):
    pass


def _str_presenter(dumper: yaml.SafeDumper, value: str) -> yaml.Node:
    return dumper.represent_scalar("tag:yaml.org,2002:str", value)


_Dumper.add_representer(str, _str_presenter)


def fetch_catalog() -> list[dict]:
    credentials = {"api_key": os.environ["WIRO_API_KEY"], "api_secret": os.environ.get("WIRO_API_SECRET", "")}
    response = requests.get(
        f"{GATEWAY_URL}/models",
        params={"limit": 1000},
        headers=catalog_headers(credentials),
        timeout=CATALOG_TIMEOUT,
    )
    response.raise_for_status()
    body = response.json()
    if body.get("has_more"):
        raise SystemExit("The catalog has more than 1000 models; add paging to this script.")
    return body["data"]


def sort_key(entry: dict) -> tuple:
    vendor = entry["id"].split("/", 1)[0]
    rank = VENDOR_ORDER.index(vendor) if vendor in VENDOR_ORDER else len(VENDOR_ORDER)
    return (rank, vendor, -int(entry.get("created") or 0), entry["id"])


def main() -> None:
    catalog = [
        entry
        for entry in fetch_catalog()
        if "chat" in ((entry.get("capabilities") or {}).get("endpoints") or [])
        and not any(part in entry["id"] for part in SKIP_NAME_PARTS)
    ]
    catalog.sort(key=sort_key)

    for old in LLM_DIR.glob("*.yaml"):
        old.unlink()

    for entry in catalog:
        schema = model_schema(entry)
        path = LLM_DIR / (entry["id"].replace("/", "__") + ".yaml")
        path.write_text(yaml.dump(schema, Dumper=_Dumper, sort_keys=False, allow_unicode=True), encoding="utf-8")

    position = [entry["id"] for entry in catalog]
    (LLM_DIR / "_position.yaml").write_text(yaml.dump(position, Dumper=_Dumper, sort_keys=False), encoding="utf-8")
    print(f"wrote {len(catalog)} models to {LLM_DIR.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
