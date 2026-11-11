"""Readable summaries of Wiro AI catalog entries for Search Models and Get Model Parameters."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from wiroapi.params import default_value, is_required, is_sample, option_values, param_items

MODEL_PAGE = "https://wiro.ai/models/{model}"
PUBLIC_CATEGORIES = {
    "llm",
    "llm-tool-call",
    "image-editing",
    "voice-clone",
    "music-generation",
    "upscale",
    "background-removal",
}
PER_RUN = {"cpr": "per run", "cpo": "per output"}


def model_id_of(entry: Mapping[str, Any]) -> str:
    owner = entry.get("cleanslugowner") or entry.get("slugowner") or ""
    project = entry.get("cleanslugproject") or entry.get("slugproject") or ""
    return f"{owner}/{project}"


def public_categories(entry: Mapping[str, Any]) -> list[str]:
    return [c for c in entry.get("categories") or [] if "-to-" in str(c) or c in PUBLIC_CATEGORIES]


def price_text(dynamic_price: Any) -> str:
    rows = dynamic_price
    if isinstance(rows, str):
        try:
            rows = json.loads(rows)
        except json.JSONDecodeError:
            rows = []
    prices = []
    for row in rows or []:
        try:
            prices.append((float(row.get("price")), str(row.get("priceMethod") or "")))
        except (TypeError, ValueError, AttributeError):
            continue
    if not prices:
        return "price on the model page"
    methods = {method for _, method in prices}
    if len(methods) == 1 and next(iter(methods)) in PER_RUN:
        unit = PER_RUN[next(iter(methods))]
        low = min(price for price, _ in prices)
        prefix = "from " if len({price for price, _ in prices}) > 1 else ""
        return f"{prefix}${low:g} {unit}"
    return "usage-based price, see the model page"


def model_card(entry: Mapping[str, Any]) -> dict:
    model_id = model_id_of(entry)
    description = " ".join(str(entry.get("description") or "").split())
    if len(description) > 300:
        description = description[:297].rsplit(" ", 1)[0] + "..."
    return {
        "model": model_id,
        "title": str(entry.get("title") or model_id),
        "description": description,
        "categories": public_categories(entry),
        "price": price_text(entry.get("dynamicprice")),
        "page": MODEL_PAGE.format(model=model_id),
    }


def parameter_rows(detail: Mapping[str, Any]) -> list[dict]:
    rows = []
    for item in param_items(detail):
        row: dict[str, Any] = {
            "id": str(item["id"]),
            "type": str(item.get("type") or ""),
            "label": str(item.get("label") or ""),
            "required": is_required(item),
        }
        if not is_sample(item):
            value = default_value(item)
            if value is not None:
                row["default"] = value
        options = option_values(item)
        if options:
            row["options"] = options[:50]
        note = " ".join(str(item.get("note") or "").split())
        if note:
            row["note"] = note[:300]
        rows.append(row)
    return rows
