"""Map the media tools' simple inputs onto a Wiro AI model's own parameters."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from wiroapi.client import WiroClient
from wiroapi.params import (
    fill_required,
    find,
    image_param,
    match_option,
    media_param,
    param_items,
    prompt_param,
    put_files,
    ratio_param,
    voice_param,
)
from wiroapi.tooling import upload_files


@dataclass
class Setting:
    """One optional tool input, written to the first model parameter named in ids that exists."""

    ids: Sequence[str]
    value: Any
    label: str
    numeric: bool = False


def build_parameters(
    client: WiroClient,
    model_id: str,
    *,
    text: str | None = None,
    text_finder: Callable[[list[dict]], dict | None] = prompt_param,
    files: list | None = None,
    image_required: bool = False,
    audio: list | None = None,
    video: list | None = None,
    aspect_ratio: str | None = None,
    voice: str | None = None,
    settings: Sequence[Setting] = (),
    extra: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Return the run parameters and notes about inputs the model could not take."""
    items = param_items(client.model_detail(model_id))
    parameters: dict[str, Any] = dict(extra or {})
    notes: list[str] = []

    if text and str(text).strip():
        item = text_finder(items)
        if item is None:
            raise ValueError(f"{model_id} takes no text prompt. Use Run Any Model with its own parameters.")
        parameters[str(item["id"])] = str(text)

    for uploads, finder, kind in (
        (files, image_param, "image"),
        (audio, lambda found: media_param(found, "audio"), "audio"),
        (video, lambda found: media_param(found, "video"), "video"),
    ):
        if not uploads:
            if kind == "image" and image_required and image_param(items) is None:
                raise ValueError(f"{model_id} takes no input image. Choose another model.")
            continue
        item = finder(items)
        if item is None:
            raise ValueError(f"{model_id} takes no input {kind}. Choose another model or leave the {kind} out.")
        put_files(item, upload_files(client, uploads), parameters, items)

    if aspect_ratio:
        item = ratio_param(items)
        choice = match_option(item, aspect_ratio) if item else None
        if item and choice is not None:
            parameters[str(item["id"])] = choice
        else:
            notes.append(f"{model_id} has no {aspect_ratio} aspect ratio, so it used its own default.")

    if voice:
        item = voice_param(items)
        choice = match_option(item, voice) if item else None
        if item and choice is not None:
            parameters[str(item["id"])] = choice
        elif item:
            values = [str(o.get("value")) for o in item.get("options") or [] if isinstance(o, dict)]
            raise ValueError(f"{model_id} has no voice called {voice}. Its voices: {', '.join(values[:40])}.")
        else:
            notes.append(f"{model_id} has no voice setting, so the voice was left out.")

    for setting in settings:
        if setting.value in (None, ""):
            continue
        item = find(items, *setting.ids)
        if item is None:
            notes.append(f"{model_id} has no {setting.label} setting, so it was left out.")
            continue
        value = setting.value
        if setting.numeric:
            number = float(value)
            value = str(int(number)) if number.is_integer() else str(number)
        choice = match_option(item, value)
        if choice is None:
            values = [str(o.get("value")) for o in item.get("options") or [] if isinstance(o, dict)]
            notes.append(
                f"{model_id} takes these {setting.label} values: {', '.join(values[:20])}. It used its default."
            )
            continue
        parameters.setdefault(str(item["id"]), choice)

    return fill_required(items, parameters), notes
