"""Map the generation tools' simple inputs onto a Wiro AI model's own parameters."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from wiroapi.client import WiroClient
from wiroapi.params import (
    fill_required,
    image_param,
    option_values,
    param_items,
    prompt_param,
    put_files,
    ratio_param,
    voice_param,
)
from wiroapi.tooling import upload_files


def build_parameters(
    client: WiroClient,
    model_id: str,
    *,
    text: str | None = None,
    text_finder: Callable[[list[dict]], dict | None] = prompt_param,
    files: list | None = None,
    aspect_ratio: str | None = None,
    voice: str | None = None,
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

    if files:
        item = image_param(items)
        if item is None:
            raise ValueError(f"{model_id} takes no input image. Choose another model or leave the image out.")
        put_files(item, upload_files(client, files), parameters)

    if aspect_ratio:
        item = ratio_param(items)
        options = option_values(item) if item else []
        if item and (not options or aspect_ratio in options):
            parameters[str(item["id"])] = aspect_ratio
        else:
            notes.append(f"{model_id} has no {aspect_ratio} aspect ratio, so it used its own default.")

    if voice:
        item = voice_param(items)
        options = option_values(item) if item else []
        if item and (not options or voice in options):
            parameters[str(item["id"])] = voice
        elif item:
            raise ValueError(f"{model_id} has no voice called {voice}. Its voices: {', '.join(options[:40])}.")
        else:
            notes.append(f"{model_id} has no voice setting, so the voice was left out.")

    return fill_required(items, parameters), notes
