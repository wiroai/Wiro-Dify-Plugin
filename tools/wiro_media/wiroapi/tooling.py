"""Steps every Wiro AI tool shares: build the client, upload inputs, run, wait and hand back files.

The SDK takes one Tool subclass per source file, so the tools keep their own
classes and call these functions.
"""

from __future__ import annotations

import json
import mimetypes
import re
from collections.abc import Generator, Iterable
from decimal import Decimal, InvalidOperation
from typing import Any

from dify_plugin.entities import I18nObject, ParameterOption

from wiroapi.client import TaskStillRunning, WiroClient, WiroError

# Dify keeps plugin files up to 50 MB by default (PLUGIN_MAX_FILE_SIZE).
MAX_ATTACH_BYTES = 50 * 1024 * 1024
MAX_INPUT_FILES = 16
DEFAULT_WAIT_SECONDS = 240

# Name parts kept out of the model pickers. Such models still run through Run Any Model.
PICKER_SKIP_NAME_PARTS = ("uncensored", "obliterated", "heretic")


def client_for(tool: Any) -> WiroClient:
    return WiroClient(tool.runtime.credentials)


def model_options(client: WiroClient, categories: Iterable[str], skip_realtime: bool = False) -> list[ParameterOption]:
    """Live model list for a dynamic-select field, most used first."""
    found: dict[str, int] = {}
    for category in categories:
        for model in client.list_models(category=category, limit=200):
            owner = model.get("cleanslugowner") or model.get("slugowner")
            project = model.get("cleanslugproject") or model.get("slugproject")
            if not owner or not project:
                continue
            if skip_realtime and any("realtime" in str(c) for c in model.get("categories") or []):
                continue
            model_id = f"{owner}/{project}"
            if any(part in model_id for part in PICKER_SKIP_NAME_PARTS):
                continue
            found.setdefault(model_id, run_count(model))
    ranked = sorted(found.items(), key=lambda item: (-item[1], item[0]))
    return [ParameterOption(value=model_id, label=I18nObject(en_US=model_id)) for model_id, _ in ranked]


def run_count(model: dict) -> int:
    try:
        return int((model.get("taskstat") or {}).get("runcount") or 0)
    except (TypeError, ValueError):
        return 0


def parse_json_object(text: Any, field: str) -> dict[str, Any]:
    if text in (None, ""):
        return {}
    if isinstance(text, dict):
        return dict(text)
    try:
        value = json.loads(str(text))
    except json.JSONDecodeError as exc:
        raise ValueError(f'{field} must be a JSON object, for example {{"resolution": "2K"}}.') from exc
    if not isinstance(value, dict):
        raise ValueError(f'{field} must be a JSON object, for example {{"resolution": "2K"}}.')
    return value


def as_list(value: Any) -> list:
    if not value:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def upload_files(client: WiroClient, files: list) -> list[str]:
    """Copy Dify files to Wiro AI storage, so the model can fetch them from a public URL."""
    if len(files) > MAX_INPUT_FILES:
        raise ValueError(f"Send at most {MAX_INPUT_FILES} files at once.")
    urls = []
    for index, item in enumerate(files):
        data = item.blob
        extension = (item.extension or "").lstrip(".") or (
            mimetypes.guess_extension(item.mime_type or "") or ""
        ).lstrip(".")
        name = item.filename or f"input-{index + 1}.{extension or 'bin'}"
        urls.append(client.upload(name, data, item.mime_type))
    return urls


def safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-") or "output"


def money(value: Any) -> str | None:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return "$" + format(amount.normalize(), "f") if amount else "$0"


def task_record(task: dict, model_id: str) -> dict:
    return {
        "task_id": str(task.get("id") or ""),
        "task_token": str(task.get("socketaccesstoken") or ""),
        "model": model_id,
        "status": task.get("status"),
        "cost_usd": task.get("totalcost"),
        "elapsed_seconds": task.get("elapsedseconds"),
    }


def run_and_deliver(
    tool: Any,
    client: WiroClient,
    model_id: str,
    parameters: dict[str, Any],
    wait_seconds: float = DEFAULT_WAIT_SECONDS,
) -> Generator:
    taskid, token = client.run(model_id, parameters)
    try:
        task = client.wait(token, wait_seconds)
    except TaskStillRunning as running:
        task = {**running.task, "id": running.task.get("id") or taskid, "socketaccesstoken": token}
        yield from still_running(tool, task, model_id)
        return
    yield from deliver(tool, client, task, model_id)


def still_running(tool: Any, task: dict, model_id: str) -> Generator:
    record = task_record(task, model_id)
    record["status"] = "running"
    yield tool.create_json_message(record)
    yield tool.create_text_message(
        f"{model_id} is still working on task {record['task_id']}. It keeps running on Wiro AI. "
        f"Use Get Task Result with the task token {record['task_token']} to collect the files when it is done."
    )


def model_text(task: dict) -> str:
    """Text answer of an LLM run: debugoutput holds the merged text when an output is raw content."""
    if any(output.get("contenttype") == "raw" for output in task.get("outputs") or []):
        return str(task.get("debugoutput") or "").strip()
    return ""


def deliver(tool: Any, client: WiroClient, task: dict, model_id: str) -> Generator:
    status = task.get("status")
    if status == "task_cancel":
        raise ValueError(f"Task {task.get('id')} was cancelled before it finished.")
    if str(task.get("pexit")) != "0":
        reason = str(task.get("debugerror") or "").strip()[:500] or "the model reported an error"
        raise ValueError(f"{model_id} could not finish task {task.get('id')}: {reason}")

    record = task_record(task, model_id)
    files: list[dict] = []
    for index, output in enumerate(task.get("outputs") or []):
        url = output.get("url")
        if not url or output.get("contenttype") == "raw":
            continue
        name = output.get("name") or f"{safe_name(model_id)}-{index + 1}"
        mime = output.get("contenttype") or mimetypes.guess_type(name)[0] or "application/octet-stream"
        files.append({"name": name, "url": url, "mime_type": mime, "size": output.get("size")})
        data = client.download(url, MAX_ATTACH_BYTES) if client.is_output_url(url) else None
        if data is None:
            yield tool.create_link_message(url)
            continue
        yield tool.create_blob_message(blob=data, meta={"mime_type": mime, "filename": name})

    text = model_text(task)
    record["files"] = files
    if text:
        record["text"] = text
    cost = money(task.get("totalcost"))

    if text:
        yield tool.create_text_message(text)
    else:
        count = len(files)
        seconds = task.get("elapsedseconds")
        took = f" in {float(seconds):.0f} s" if seconds not in (None, "") else ""
        summary = f"{model_id} made {count} file{'s' if count != 1 else ''}{took}"
        summary += f" for {cost}." if cost else "."
        lines = [summary] + [item["url"] for item in files]
        yield tool.create_text_message("\n".join(lines))
    yield tool.create_json_message(record)


def explain(error: Exception) -> str:
    return str(error) or error.__class__.__name__


__all__ = [
    "DEFAULT_WAIT_SECONDS",
    "WiroError",
    "as_list",
    "client_for",
    "deliver",
    "explain",
    "model_options",
    "parse_json_object",
    "run_and_deliver",
    "task_record",
    "upload_files",
]
