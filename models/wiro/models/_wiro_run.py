"""Speech models on the Wiro AI Run API (https://api.wiro.ai/v1).

Text to speech and speech to text run as Wiro AI tasks: the plugin starts a
run, follows its task until it ends and reads the output file. The model list
and each model's voices come from the public catalog (Tool/List, Tool/Detail).
"""

from __future__ import annotations

import hashlib
import hmac
import re
import threading
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

import requests

API_URL = "https://api.wiro.ai/v1"
USER_AGENT = "wiro-dify-plugin/0.2.0 (+https://github.com/wiroai/Wiro-Dify-Plugin)"

REQUEST_TIMEOUT = (10, 60)
TRANSFER_TIMEOUT = (10, 300)
CATALOG_CACHE_SECONDS = 600
TERMINAL_STATUSES = {"task_postprocess_end", "task_cancel"}
FILE_TYPES = {"fileinput", "multifileinput", "multifileinputdrop", "combinefileinput", "fileexplorer"}
SAMPLE_IDS = {"prompt", "messages", "tools", "tool_choice", "previousTaskToken", "toolOutputs", "response_format"}
MAX_TEXT_BYTES = 2 * 1024 * 1024
MAX_AUDIO_BYTES = 100 * 1024 * 1024

# Languages Dify offers for text to speech. Wiro AI's voice models are multilingual.
TTS_LANGUAGES = [
    "en-US", "zh-Hans", "zh-Hant", "ja-JP", "ko-KR", "de-DE", "fr-FR", "es-ES", "it-IT", "pt-BR",
    "ru-RU", "tr-TR", "uk-UA", "vi-VN", "th-TH", "id-ID", "pl-PL", "ro-RO", "hi-IN", "fa-IR",
    "sl-SI", "ar-TN",
]  # fmt: skip
STT_EXTENSIONS = "mp3,mp4,mpeg,mpga,m4a,wav,webm"


class WiroRunError(Exception):
    """A Run API call failed. The message is safe to show to the user."""


def _error_text(body: Any) -> str:
    if isinstance(body, dict):
        messages = [str(e.get("message")) for e in body.get("errors") or [] if isinstance(e, dict) and e.get("message")]
        if messages:
            return "; ".join(messages)
    return "no details"


class RunClient:
    def __init__(self, credentials: Mapping[str, Any]) -> None:
        key = str(credentials.get("api_key") or "").strip()
        secret = str(credentials.get("api_secret") or "").strip()
        if ":" in key and not secret:
            key, _, secret = key.partition(":")
        if not key:
            raise WiroRunError("Enter the API key of your Wiro AI project.")
        self.api_key, self.api_secret = key, secret
        self.session = requests.Session()

    def _headers(self) -> dict[str, str]:
        headers = {"x-api-key": self.api_key, "User-Agent": USER_AGENT, "Accept": "application/json"}
        if self.api_secret:
            nonce = str(int(time.time() * 1000))
            digest = hmac.new(self.api_key.encode(), (self.api_secret + nonce).encode(), hashlib.sha256).hexdigest()
            headers.update({"x-nonce": nonce, "x-signature": digest})
        return headers

    @staticmethod
    def _read(response: requests.Response) -> dict:
        try:
            body = response.json()
        except ValueError as exc:
            raise WiroRunError(f"Wiro AI answered with HTTP {response.status_code} and no JSON body.") from exc
        if response.status_code >= 400:
            raise WiroRunError(f"Wiro AI answered with HTTP {response.status_code}: {_error_text(body)}")
        if isinstance(body, dict) and body.get("result") is False:
            raise WiroRunError(_error_text(body))
        return body

    def post(self, path: str, body: Mapping[str, Any]) -> dict:
        try:
            response = self.session.post(
                f"{API_URL}{path}", json=body, headers=self._headers(), timeout=REQUEST_TIMEOUT
            )
        except requests.RequestException as exc:
            raise WiroRunError("Could not reach Wiro AI. Check the network and try again.") from exc
        return self._read(response)

    def check_credentials(self) -> None:
        """Read one task row. It is free and fails on a wrong key or signature."""
        try:
            self.post("/Task/List", {"start": "0", "limit": "1"})
        except WiroRunError as exc:
            raise WiroRunError(
                "Wiro AI did not accept these credentials. Check the API key, and add the API secret "
                "if your project uses signature authentication."
            ) from exc

    _details: dict[str, tuple[float, dict]] = {}
    _details_lock = threading.Lock()

    def model_detail(self, model_id: str) -> dict:
        owner, _, project = model_id.strip().partition("/")
        if not owner or not project:
            raise WiroRunError(f'"{model_id}" is not a model ID. Use owner/model, for example elevenlabs/eleven-v4.')
        now = time.monotonic()
        with self._details_lock:
            cached = self._details.get(model_id)
            if cached and now - cached[0] < CATALOG_CACHE_SECONDS:
                return cached[1]
        tools = self.post("/Tool/Detail", {"slugowner": owner, "slugproject": project}).get("tool") or []
        if not tools:
            raise WiroRunError(f"Wiro AI has no model called {model_id}.")
        with self._details_lock:
            self._details[model_id] = (now, tools[0])
        return tools[0]

    def upload(self, filename: str, data: bytes, mime_type: str) -> str:
        if len(data) > MAX_AUDIO_BYTES:
            raise WiroRunError("The audio file is larger than the 100 MB upload limit.")
        try:
            response = self.session.post(
                f"{API_URL}/File/Upload",
                files={"file": (filename, data, mime_type)},
                headers=self._headers(),
                timeout=TRANSFER_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise WiroRunError("Could not upload the audio to Wiro AI. Check the network and try again.") from exc
        items = self._read(response).get("list") or []
        url = items[0].get("url") if items else None
        if not url:
            raise WiroRunError("Wiro AI accepted the audio but returned no file URL.")
        return str(url)

    def run(self, model_id: str, parameters: Mapping[str, Any], timeout_seconds: float) -> dict:
        owner, _, project = model_id.partition("/")
        token = self.post(f"/Run/{owner}/{project}", parameters).get("socketaccesstoken")
        if not token:
            raise WiroRunError("Wiro AI started the task but returned no task token.")
        started = time.monotonic()
        while True:
            tasks = self.post("/Task/Detail", {"tasktoken": token}).get("tasklist") or []
            task = tasks[0] if tasks else {}
            if task.get("status") in TERMINAL_STATUSES:
                break
            elapsed = time.monotonic() - started
            if elapsed > timeout_seconds:
                raise WiroRunError(f"{model_id} did not finish within {int(timeout_seconds)} seconds.")
            time.sleep(1 if elapsed < 10 else 3 if elapsed < 60 else 6)
        if task.get("status") == "task_cancel":
            raise WiroRunError(f"The {model_id} task was cancelled.")
        if str(task.get("pexit")) != "0":
            reason = str(task.get("debugerror") or "").strip()[:300] or "the model reported an error"
            raise WiroRunError(f"{model_id} could not finish: {reason}")
        return task

    def download(self, url: str, max_bytes: int) -> bytes:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not (host == "wiro.ai" or host.endswith(".wiro.ai")):
            raise WiroRunError("The output file is not on a Wiro AI host.")
        try:
            with self.session.get(url, stream=True, timeout=TRANSFER_TIMEOUT, headers={"User-Agent": USER_AGENT}) as r:
                r.raise_for_status()
                chunks, size = [], 0
                for chunk in r.iter_content(chunk_size=256 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        raise WiroRunError("The output file is larger than expected.")
                    chunks.append(chunk)
                return b"".join(chunks)
        except requests.RequestException as exc:
            raise WiroRunError("Could not download the output file from Wiro AI.") from exc


# -- catalog helpers shared by the models and scripts/generate_models.py ------


def param_items(detail: Mapping[str, Any]) -> list[dict]:
    return [i for g in detail.get("parameters") or [] for i in (g or {}).get("items") or [] if i.get("id")]


def find(items: list[dict], *ids: str) -> dict | None:
    by_id = {str(i["id"]): i for i in items}
    return next((by_id[i] for i in ids if i in by_id), None)


def is_required(item: Mapping[str, Any]) -> bool:
    return item.get("required") is True or str(item.get("required")).lower() == "true"


def is_sample(item: Mapping[str, Any]) -> bool:
    item_id = str(item.get("id"))
    return str(item.get("type")) in FILE_TYPES or "input" in item_id or item_id in SAMPLE_IDS


def default_value(item: Mapping[str, Any]) -> str | None:
    if item.get("type") == "checkbox":
        raw = item["value"] if "value" in item else item.get("defaultvalue")
        off = str(raw if raw is not None else "").strip().lower() in {
            "",
            "false",
            "0",
            "no",
            "off",
            "null",
            "undefined",
        }
        return "false" if (raw is False or off) else "true"
    raw = item.get("defaultvalue")
    if raw in (None, ""):
        raw = item.get("value")
    if raw in (None, "") or isinstance(raw, (list, dict)):
        return None
    return str(raw)


def options(item: Mapping[str, Any] | None) -> list[dict]:
    rows = []
    for option in (item or {}).get("options") or []:
        if isinstance(option, dict) and option.get("value") not in (None, ""):
            rows.append({"value": str(option["value"]), "text": str(option.get("text") or option["value"])})
    return rows


def catalog_choice(item: Mapping[str, Any]) -> str | None:
    """The catalog default, matched to the item's options when it has a list (case aside)."""
    value = default_value(item)
    choices = [o["value"] for o in options(item)]
    if not choices or value in choices:
        return value
    folded = {c.lower(): c for c in choices}
    if value is not None and value.lower() in folded:
        return folded[value.lower()]
    return choices[0]


def fill_required(items: list[dict], parameters: dict[str, Any]) -> dict[str, Any]:
    filled = dict(parameters)
    missing = []
    for item in items:
        item_id = str(item["id"])
        if not is_required(item) or filled.get(item_id) not in (None, "", []):
            continue
        if any(key != item_id and key.startswith(item_id) and filled.get(key) for key in filled):
            continue
        value = None if is_sample(item) else catalog_choice(item)
        if value is None:
            missing.append(item_id)
        else:
            filled[item_id] = value
    if missing:
        raise WiroRunError("The model needs a value for: " + ", ".join(missing) + ".")
    return filled


def text_param(items: list[dict]) -> dict | None:
    return find(items, "prompt", "text") or next((i for i in items if i.get("type") == "textarea"), None)


def voice_param(items: list[dict]) -> dict | None:
    return find(items, "voice", "voiceId", "voice_id", "speaker")


def audio_param(items: list[dict]) -> dict | None:
    exact = find(items, "inputAudio")
    if exact and str(exact.get("type")) in FILE_TYPES:
        return exact
    return next((i for i in items if str(i.get("type")) in FILE_TYPES and "audio" in str(i["id"]).lower()), None)


def put_file(items: list[dict], item: Mapping[str, Any], url: str, parameters: dict[str, Any]) -> None:
    item_id = str(item["id"])
    if str(item.get("type")) == "combinefileinput":
        parameters[item_id] = [url]
    elif find(items, f"{item_id}Url"):
        parameters[f"{item_id}Url"] = url
    else:
        parameters[item_id] = url


def per_thousand(price_per_unit: float) -> str:
    text = f"{price_per_unit * 1000:.6f}".rstrip("0").rstrip(".")
    return text or "0"


def audio_type(items: list[dict]) -> str:
    fmt = find(items, "outputFormat", "format", "audioFormat", "responseFormat")
    value = (default_value(fmt) or "").lower() if fmt else ""
    for kind in ("mp3", "wav", "ogg", "opus", "flac", "aac", "pcm"):
        if value.startswith(kind) or f"_{kind}" in value:
            return "wav" if kind == "pcm" else kind
    return "mp3"  # Wiro AI delivers its voice models' audio as MP3


def tts_schema(model_id: str, detail: Mapping[str, Any]) -> dict | None:
    """Dify schema for a text to speech model, or None when it has no text and voice settings."""
    items = param_items(detail)
    text, voice = text_param(items), voice_param(items)
    voices = options(voice)
    if not text or not voices:
        return None
    default = default_value(voice) or voices[0]["value"]
    if default not in {v["value"] for v in voices}:
        default = voices[0]["value"]
    schema: dict[str, Any] = {
        "model": model_id,
        "label": {"en_US": model_id},
        "model_type": "tts",
        "model_properties": {
            "default_voice": default,
            "voices": [{"mode": v["value"], "name": v["text"], "language": TTS_LANGUAGES} for v in voices],
            "word_limit": 3000,
            "audio_type": audio_type(items),
            "max_workers": 3,
        },
    }
    prices = detail.get("dynamicprice") or []
    if isinstance(prices, list) and len(prices) == 1 and prices[0].get("priceMethod") == "cp-promptlength":
        schema["pricing"] = {
            "input": per_thousand(float(prices[0]["price"])),
            "output": "0",
            "unit": "0.001",
            "currency": "USD",
        }
    return schema


def stt_schema(model_id: str, detail: Mapping[str, Any]) -> dict | None:
    """Dify schema for a speech to text model, or None when it takes no audio file."""
    if not audio_param(param_items(detail)):
        return None
    return {
        "model": model_id,
        "label": {"en_US": model_id},
        "model_type": "speech2text",
        "model_properties": {"file_upload_limit": 100, "supported_file_extensions": STT_EXTENSIONS},
    }


def is_realtime(detail: Mapping[str, Any], model_id: str) -> bool:
    return "realtime" in model_id or any("realtime" in str(c) for c in detail.get("categories") or [])


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
