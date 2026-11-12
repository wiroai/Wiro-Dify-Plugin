from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from typing import IO

from dify_plugin.entities.model import AIModelEntity, FetchFrom
from dify_plugin.errors.model import CredentialsValidateFailedError, InvokeBadRequestError
from dify_plugin.interfaces.model.speech2text_model import Speech2TextModel

from models._wiro_run import (
    MAX_TEXT_BYTES,
    RunClient,
    WiroRunError,
    audio_param,
    fill_required,
    param_items,
    plain_transcript,
    put_file,
    stt_schema,
)

TASK_TIMEOUT_SECONDS = 300

# Leading bytes of the audio formats Dify records or uploads.
SIGNATURES = [
    (b"ID3", "mp3", "audio/mpeg"),
    (b"\xff\xfb", "mp3", "audio/mpeg"),
    (b"\xff\xf3", "mp3", "audio/mpeg"),
    (b"\xff\xf2", "mp3", "audio/mpeg"),
    (b"RIFF", "wav", "audio/wav"),
    (b"\x1a\x45\xdf\xa3", "webm", "audio/webm"),
    (b"OggS", "ogg", "audio/ogg"),
    (b"fLaC", "flac", "audio/flac"),
]


def sniff_audio(data: bytes) -> tuple[str, str]:
    for prefix, extension, mime in SIGNATURES:
        if data.startswith(prefix):
            return extension, mime
    if data[4:8] == b"ftyp":
        return "m4a", "audio/mp4"
    return "mp3", "audio/mpeg"


class WiroSpeech2TextModel(Speech2TextModel):
    """Speech to text on Wiro AI's transcription models (ElevenLabs, Whisper, Qwen3 ASR and others)."""

    def _invoke(self, model: str, credentials: dict, file: IO[bytes], user: str | None = None) -> str:
        del user
        try:
            data = file.read()
            if not data:
                raise InvokeBadRequestError("The audio file is empty.")
            client = RunClient(credentials)
            items = param_items(client.model_detail(model))
            audio_item = audio_param(items)
            if not audio_item:
                raise InvokeBadRequestError(f"{model} takes no audio file.")
            extension, mime = sniff_audio(data)
            url = client.upload(f"dify-speech-{uuid.uuid4().hex[:12]}.{extension}", data, mime)
            parameters: dict = {}
            put_file(items, audio_item, url, parameters)
            task = client.run(model, fill_required(items, parameters), TASK_TIMEOUT_SECONDS)
            return self._transcript(client, task, model)
        except WiroRunError as exc:
            raise InvokeBadRequestError(str(exc)) from exc

    @staticmethod
    def _transcript(client: RunClient, task: dict, model: str) -> str:
        outputs = task.get("outputs") or []
        for output in outputs:
            if output.get("contenttype") == "raw":
                return plain_transcript(str(task.get("debugoutput") or ""))
        for output in outputs:
            kind = str(output.get("contenttype") or "")
            name = str(output.get("name") or "")
            if output.get("url") and (kind.startswith("text/") or name.endswith((".txt", ".srt", ".vtt"))):
                return plain_transcript(client.download(str(output["url"]), MAX_TEXT_BYTES).decode("utf-8", "replace"))
        for output in outputs:
            if output.get("url") and str(output.get("contenttype") or "").endswith("json"):
                body = json.loads(client.download(str(output["url"]), MAX_TEXT_BYTES))
                if isinstance(body, dict) and isinstance(body.get("text"), str):
                    return body["text"].strip()
        raise WiroRunError(f"{model} returned no transcript.")

    def validate_credentials(self, model: str, credentials: Mapping) -> None:
        """For a transcription model added by ID. Spends nothing: it reads the account and the catalog."""
        try:
            client = RunClient(credentials)
            client.check_credentials()
            if stt_schema(model, client.model_detail(model)) is None:
                raise CredentialsValidateFailedError(f"{model} takes no audio file.")
        except WiroRunError as exc:
            raise CredentialsValidateFailedError(str(exc)) from exc

    def get_customizable_model_schema(self, model: str, credentials: Mapping) -> AIModelEntity | None:
        try:
            schema = stt_schema(model, RunClient(credentials).model_detail(model))
        except WiroRunError:
            return None
        if schema is None:
            return None
        schema["fetch_from"] = FetchFrom.CUSTOMIZABLE_MODEL.value
        return AIModelEntity.model_validate(schema)

    @property
    def _invoke_error_mapping(self) -> dict:
        return {InvokeBadRequestError: [WiroRunError]}
