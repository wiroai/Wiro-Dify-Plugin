"""Model parameters as Wiro AI's Tool/Detail describes them.

A run refuses a required parameter that is left out, while optional ones get
the catalog value on Wiro AI's side. The catalog value of a "sample" parameter
(file inputs, ids that contain "input", the prompt and the LLM chat fields) is
an example from the model page, so it is never sent on the user's behalf.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

FILE_TYPES = {"fileinput", "multifileinput", "multifileinputdrop", "combinefileinput", "fileexplorer"}
SAMPLE_IDS = {"prompt", "messages", "tools", "tool_choice", "previousTaskToken", "toolOutputs", "response_format"}
CHECKBOX_OFF = {"", "false", "0", "no", "off", "null", "undefined"}
RATIO_IDS = ("aspectRatio", "ratio", "aspect_ratio", "aspect")
VOICE_IDS = ("voice", "voiceId", "voice_id", "speaker")
SECONDARY_IMAGE_WORDS = ("mask", "last", "middle", "end", "tail", "style", "reference")


def param_items(detail: Mapping[str, Any]) -> list[dict]:
    items: list[dict] = []
    for group in detail.get("parameters") or []:
        for item in (group or {}).get("items") or []:
            if isinstance(item, dict) and item.get("id"):
                items.append(item)
    return items


def is_required(item: Mapping[str, Any]) -> bool:
    return item.get("required") is True or str(item.get("required")).lower() == "true"


def is_file(item: Mapping[str, Any]) -> bool:
    return str(item.get("type")) in FILE_TYPES


def is_sample(item: Mapping[str, Any]) -> bool:
    item_id = str(item.get("id"))
    return is_file(item) or "input" in item_id or item_id in SAMPLE_IDS


def default_value(item: Mapping[str, Any]) -> str | None:
    """The catalog value of a parameter, as text. None when the catalog has none."""
    if item.get("type") == "checkbox":
        initial = item["value"] if "value" in item else item.get("defaultvalue")
        if isinstance(initial, bool):
            return "true" if initial else "false"
        return "false" if str(initial if initial is not None else "").strip().lower() in CHECKBOX_OFF else "true"
    raw = item.get("defaultvalue")
    if raw in (None, ""):
        raw = item.get("value")
    if raw in (None, "") or raw == []:
        return None
    if isinstance(raw, (list, dict)):
        return json.dumps(raw)
    return str(raw)


def option_values(item: Mapping[str, Any]) -> list[str]:
    values = []
    for option in item.get("options") or []:
        value = option.get("value") if isinstance(option, dict) else option
        if value is not None:
            values.append(str(value))
    return values


def find(items: list[dict], *ids: str) -> dict | None:
    by_id = {str(item["id"]): item for item in items}
    for item_id in ids:
        if item_id in by_id:
            return by_id[item_id]
    return None


def prompt_param(items: list[dict]) -> dict | None:
    return find(items, "prompt") or next((item for item in items if item.get("type") == "textarea"), None)


def text_param(items: list[dict]) -> dict | None:
    """The text a speech model reads aloud."""
    return find(items, "prompt", "text", "input_text") or next(
        (item for item in items if item.get("type") == "textarea"), None
    )


def image_param(items: list[dict]) -> dict | None:
    """The main image input: inputImage, or the first image file field that is not a mask or end frame."""
    exact = find(items, "inputImage")
    if exact and is_file(exact):
        return exact
    for item in items:
        item_id = str(item["id"]).lower()
        if is_file(item) and "image" in item_id and not any(word in item_id for word in SECONDARY_IMAGE_WORDS):
            return item
    return None


def ratio_param(items: list[dict]) -> dict | None:
    return find(items, *RATIO_IDS)


def voice_param(items: list[dict]) -> dict | None:
    return find(items, *VOICE_IDS)


def put_files(item: Mapping[str, Any], urls: list[str], parameters: dict[str, Any]) -> None:
    """Place file URLs the way each file field takes them."""
    item_id = str(item["id"])
    kind = str(item.get("type"))
    if kind == "combinefileinput":
        limit = int(item.get("maxinputlenght") or 0)
        if limit and len(urls) > limit:
            raise ValueError(f"{item_id} takes at most {limit} files, and {len(urls)} were given.")
        parameters[item_id] = urls
    elif kind in ("multifileinput", "multifileinputdrop"):
        url_field = item_id.replace("Multiple", "UrlMultiple") if item_id.endswith("Multiple") else item_id
        parameters[url_field] = ",".join(urls)
    else:
        if len(urls) > 1:
            raise ValueError(f"{item_id} takes one file, and {len(urls)} were given.")
        parameters[item_id] = urls[0]


def fill_required(items: list[dict], parameters: dict[str, Any]) -> dict[str, Any]:
    """Send the catalog value for required parameters the caller left out, and name the ones only the caller can give."""
    filled = dict(parameters)
    missing = []
    for item in items:
        item_id = str(item["id"])
        if not is_required(item) or filled.get(item_id) not in (None, "", []):
            continue
        if is_file(item) and any(key.startswith(item_id) and filled.get(key) for key in filled):
            continue
        value = None if is_sample(item) else default_value(item)
        if value is None:
            missing.append(item_id)
        else:
            filled[item_id] = value
    if missing:
        raise ValueError(
            "This model needs a value for: " + ", ".join(missing) + ". Get Model Parameters shows what each one takes."
        )
    return filled
