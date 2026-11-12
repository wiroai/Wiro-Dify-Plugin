"""Steps every Wiro AI tool shares: build the client, upload inputs, run, wait and hand back files.

The SDK takes one Tool subclass per source file, so the tools keep their own
classes and call these functions.
"""

from __future__ import annotations

import json
import mimetypes
import re
import uuid
from collections.abc import Callable, Generator, Iterable
from decimal import Decimal, InvalidOperation
from typing import Any

from dify_plugin.entities import I18nObject, ParameterOption

from wiroapi.client import TaskStillRunning, WiroClient, WiroError

# Dify keeps plugin files up to 50 MB by default (PLUGIN_MAX_FILE_SIZE).
MAX_ATTACH_BYTES = 50 * 1024 * 1024
MAX_INPUT_FILES = 16
DEFAULT_WAIT_SECONDS = 240
# Dify stops a plugin call after 600 s by default, so no wait goes past this.
MAX_WAIT_SECONDS = 540

# Name parts kept out of the model pickers. Such models still run through Run Any Model.
PICKER_SKIP_NAME_PARTS = ("uncensored", "obliterated", "heretic")

TEXT_SUFFIXES = (".txt", ".srt", ".vtt", ".md", ".json")
WIRO_URL = re.compile(r"https://[A-Za-z0-9.-]*wiro\.ai/[^\s)\]>\"']+")
EXTRA_MIME = {".glb": "model/gltf-binary", ".gltf": "model/gltf+json", ".obj": "model/obj", ".ply": "application/ply"}


def client_for(tool: Any) -> WiroClient:
    return WiroClient(tool.runtime.credentials)


def wait_value(raw: Any, default: float, maximum: float = MAX_WAIT_SECONDS, minimum: float = 0) -> float:
    if raw in (None, ""):
        return default
    return min(maximum, max(minimum, float(raw)))


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


def file_parts(files: list) -> list[tuple[str, bytes, str]]:
    """Read Dify files as (name, bytes, mime) for uploads and attachments."""
    if len(files) > MAX_INPUT_FILES:
        raise ValueError(f"Send at most {MAX_INPUT_FILES} files at once.")
    parts = []
    for index, item in enumerate(files):
        extension = (item.extension or "").lstrip(".") or (
            mimetypes.guess_extension(item.mime_type or "") or ""
        ).lstrip(".")
        name = item.filename or f"input-{index + 1}.{extension or 'bin'}"
        parts.append((name, item.blob, item.mime_type or mimetypes.guess_type(name)[0] or "application/octet-stream"))
    return parts


def upload_files(client: WiroClient, files: list) -> list[str]:
    """Copy Dify files to Wiro AI storage, so the model can fetch them from a public URL.

    Each upload gets a unique name: the project folder keeps one file per name.
    """
    return [
        client.upload(f"dify-{uuid.uuid4().hex[:10]}-{safe_name(name)}", data, mime)
        for name, data, mime in file_parts(files)
    ]


def safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-") or "output"


def money(value: Any) -> str | None:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return "$" + format(amount.normalize(), "f") if amount else "$0"


def guess_mime(name: str, declared: str | None = None) -> str:
    if declared and declared != "application/octet-stream":
        return declared
    suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return EXTRA_MIME.get(suffix) or mimetypes.guess_type(name)[0] or "application/octet-stream"


def send_files(tool: Any, client: WiroClient, outputs: Iterable[dict], prefix: str) -> Generator:
    """Attach output files to the Dify result. Yields messages; returns (file rows, texts read from text files)."""
    rows: list[dict] = []
    texts: list[str] = []
    for index, output in enumerate(outputs):
        url = output.get("url")
        if not url or output.get("contenttype") == "raw":
            continue
        name = str(output.get("name") or f"{safe_name(prefix)}-{index + 1}")
        mime = guess_mime(name, output.get("contenttype"))
        rows.append({"name": name, "url": url, "mime_type": mime, "size": output.get("size")})
        if not client.is_output_url(url):
            yield tool.create_link_message(url)
            continue
        data = client.download(url, MAX_ATTACH_BYTES)
        if data is None:
            yield tool.create_link_message(url)
            continue
        if mime.startswith("text/") or name.lower().endswith(TEXT_SUFFIXES):
            texts.append(data.decode("utf-8", "replace").strip())
        yield tool.create_blob_message(blob=data, meta={"mime_type": mime, "filename": name})
    return rows, texts


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
    notes: list[str] | None = None,
    clean_text: Callable[[str], str] | None = None,
) -> Generator:
    taskid, token = client.run(model_id, parameters)
    try:
        task = client.wait(token, wait_seconds)
    except TaskStillRunning as running:
        task = {**running.task, "id": running.task.get("id") or taskid, "socketaccesstoken": token}
        yield from still_running(tool, task, model_id)
        return
    yield from deliver(tool, client, task, model_id, notes, clean_text)


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


def deliver(
    tool: Any,
    client: WiroClient,
    task: dict,
    model_id: str,
    notes: list[str] | None = None,
    clean_text: Callable[[str], str] | None = None,
) -> Generator:
    """Hand back files and text. Notes go to the JSON record, and under a file summary, never into a text answer.

    clean_text tidies the text answer only; the model's own files are handed back unchanged."""
    status = task.get("status")
    if status == "task_cancel":
        raise ValueError(f"Task {task.get('id')} was cancelled before it finished.")
    if str(task.get("pexit")) != "0":
        reason = str(task.get("debugerror") or "").strip()[:500] or "the model reported an error"
        raise ValueError(f"{model_id} could not finish task {task.get('id')}: {reason}")

    record = task_record(task, model_id)
    files, file_texts = yield from send_files(tool, client, task.get("outputs") or [], model_id)
    text = model_text(task) or "\n\n".join(t for t in file_texts if t)
    if text and clean_text:
        text = clean_text(text)
    record["files"] = files
    if text:
        record["text"] = text
    if notes:
        record["notes"] = notes
    cost = money(task.get("totalcost"))

    if text:
        yield tool.create_text_message(text)
    else:
        count = len(files)
        seconds = task.get("elapsedseconds")
        took = f" in {float(seconds):.0f} s" if seconds not in (None, "") else ""
        summary = f"{model_id} made {count} file{'s' if count != 1 else ''}{took}"
        summary += f" for {cost}." if cost else "."
        lines = [summary] + [item["url"] for item in files] + [f"Note: {note}" for note in notes or []]
        yield tool.create_text_message("\n".join(lines))
    yield tool.create_json_message(record)


# -- transcripts ----------------------------------------------------------------

_CLOCK = r"\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?"
_SEGMENT = re.compile(rf"^\s*\[?{_CLOCK}\s*(?:-->|-)\s*{_CLOCK}\]?\s*(?:/|\|)?\s*")
_LABELLED = re.compile(r"^\s*language:[^\n]*\n\s*text:\s*", re.IGNORECASE)


def plain_transcript(text: str) -> str:
    """The spoken words only, without segment times (Whisper, SRT, VTT) or a "Language: ... Text:" header."""
    text = _LABELLED.sub("", str(text or "").strip(), count=1)
    lines = [line.strip() for line in text.splitlines()]
    if not any(_SEGMENT.match(line) for line in lines):
        return text.strip()
    words = []
    for index, line in enumerate(lines):
        following = next((rest for rest in lines[index + 1 :] if rest), "")
        if not line or line.upper() == "WEBVTT" or (line.isdigit() and _SEGMENT.match(following)):
            continue
        words.append(_SEGMENT.sub("", line).strip())
    return " ".join(word for word in words if word)


# -- workflow runs ------------------------------------------------------------


def _llm_answer(outputs: Any) -> str | None:
    if isinstance(outputs, list):
        for output in outputs:
            if isinstance(output, dict) and output.get("contenttype") == "raw":
                content = output.get("content") or {}
                answer = content.get("answer") or content.get("raw")
                return "".join(answer) if isinstance(answer, list) else str(answer or "")
    return None


def workflow_results(body: dict) -> list[dict]:
    """The End node's results: each with name, and files or text."""
    run = body.get("workflowrun") or {}
    contents = run.get("contents") or {}
    if isinstance(contents, str):
        contents = json.loads(contents or "{}")
    fields = (contents.get("nodes") or {}).get("output", {}).get("fields") or contents.get("output") or {}
    nodes = {str(n.get("nodeId")): n for n in body.get("workflowrunnodes") or []}
    saved = ((contents.get("metadata") or {}).get("input") or {}).get("values") or {}
    results = []
    for name, ref in fields.items():
        ref = str(ref)
        if ref.startswith("$input."):
            results.append({"name": name, "text": str(saved.get(ref.split(".", 1)[1], ""))})
            continue
        node_id, _, port = ref.lstrip("$").partition(".")
        outputs = (nodes.get(node_id) or {}).get("outputs")
        answer = _llm_answer(outputs)
        if answer is not None:
            results.append({"name": name, "text": answer})
        elif isinstance(outputs, list):
            results.append({"name": name, "files": [o for o in outputs if isinstance(o, dict) and o.get("url")]})
        elif isinstance(outputs, dict):
            value = outputs.get(port, outputs)
            results.append({"name": name, "text": value if isinstance(value, str) else json.dumps(value)})
        else:
            results.append({"name": name, "text": ""})
    return results


def deliver_workflow(tool: Any, client: WiroClient, body: dict, slug: str) -> Generator:
    run = body.get("workflowrun") or {}
    status = run.get("status")
    if status != "completed":
        problems = [
            f"{n.get('nodeId')} ({n.get('tool')}): {n.get('error') or n.get('cause')}"
            for n in body.get("workflowrunnodes") or []
            if n.get("status") == "failed"
        ]
        detail = "; ".join(problems) or "no step reported why"
        raise ValueError(f"Workflow {slug} ended as {status}: {detail}")

    record: dict[str, Any] = {
        "workflow": slug,
        "run_token": run.get("workflowtoken"),
        "status": status,
        "cost_usd": run.get("chargedcost") if run.get("chargedcost") is not None else run.get("totalcost"),
        "elapsed_seconds": run.get("elapsedseconds"),
        "results": {},
    }
    lines = []
    for result in workflow_results(body):
        if "files" in result:
            rows, texts = yield from send_files(tool, client, result["files"], f"{slug}-{result['name']}")
            record["results"][result["name"]] = {"files": rows}
            lines.append(f"{result['name']}: " + ", ".join(r["url"] for r in rows))
            lines += [t for t in texts if t]
        else:
            record["results"][result["name"]] = {"text": result["text"]}
            lines.append(f"{result['name']}: {result['text']}")
    cost = money(record["cost_usd"])
    head = f"Workflow {slug} finished" + (f" for {cost}." if cost else ".")
    yield tool.create_text_message("\n".join([head, *lines]))
    yield tool.create_json_message(record)


# -- Studio and agent replies -------------------------------------------------


def reply_files(text: str) -> list[dict]:
    urls = list(dict.fromkeys(WIRO_URL.findall(text or "")))
    return [{"url": url, "name": url.rsplit("/", 1)[-1].split("?")[0]} for url in urls]


def deliver_reply(tool: Any, client: WiroClient, reply: dict, who: str, record: dict) -> Generator:
    status = reply.get("status")
    text = str(reply.get("response") or reply.get("debugoutput") or "").strip()
    if status == "agent_cancel":
        raise ValueError(f"The {who} turn was cancelled.")
    if status == "agent_error":
        raise ValueError(f"{who} could not answer: {text or 'no details'}")
    files, _ = yield from send_files(tool, client, reply_files(text), who)
    record.update({"status": status, "reply": text, "files": files, "model": reply.get("model")})
    yield tool.create_text_message(text)
    yield tool.create_json_message(record)


def still_running_reply(tool: Any, record: dict, hint: str) -> Generator:
    record = {**record, "status": "running"}
    yield tool.create_json_message(record)
    yield tool.create_text_message(hint)


def explain(error: Exception) -> str:
    return str(error) or error.__class__.__name__


__all__ = [
    "DEFAULT_WAIT_SECONDS",
    "MAX_WAIT_SECONDS",
    "WiroError",
    "as_list",
    "client_for",
    "deliver",
    "deliver_reply",
    "deliver_workflow",
    "explain",
    "file_parts",
    "model_options",
    "parse_json_object",
    "plain_transcript",
    "run_and_deliver",
    "task_record",
    "upload_files",
    "wait_value",
]
