from __future__ import annotations

from collections.abc import Generator, Mapping

from dify_plugin.entities.model import AIModelEntity, FetchFrom
from dify_plugin.errors.model import CredentialsValidateFailedError, InvokeBadRequestError
from dify_plugin.interfaces.model.tts_model import TTSModel

from models._wiro_run import (
    MAX_AUDIO_BYTES,
    RunClient,
    WiroRunError,
    fill_required,
    param_items,
    text_param,
    tts_schema,
    voice_param,
)

# Long text is read in parts; each part is one Wiro AI task.
TASK_TIMEOUT_SECONDS = 240


class WiroText2SpeechModel(TTSModel):
    """Text to speech on Wiro AI's voice models (ElevenLabs, Gemini TTS, Kokoro and others)."""

    def _invoke(
        self,
        model: str,
        tenant_id: str,
        credentials: dict,
        content_text: str,
        voice: str,
        user: str | None = None,
    ) -> Generator[bytes, None, None]:
        del tenant_id, user
        try:
            client = RunClient(credentials)
            items = param_items(client.model_detail(model))
            text_item, voice_item = text_param(items), voice_param(items)
            if not text_item:
                raise InvokeBadRequestError(f"{model} takes no text to read.")
            limit = self._get_model_word_limit(model, credentials) or 3000
            voice = voice or self._get_model_default_voice(model, credentials)
            for part in self._split_text_into_sentences(content_text, max_length=limit):
                if not part.strip():
                    continue
                parameters = {str(text_item["id"]): part}
                if voice_item and voice:
                    parameters[str(voice_item["id"])] = str(voice)
                task = client.run(model, fill_required(items, parameters), TASK_TIMEOUT_SECONDS)
                yield self._audio(client, task, model)
        except WiroRunError as exc:
            raise InvokeBadRequestError(str(exc)) from exc

    @staticmethod
    def _audio(client: RunClient, task: dict, model: str) -> bytes:
        for output in task.get("outputs") or []:
            kind = str(output.get("contenttype") or "")
            if output.get("url") and (kind.startswith("audio/") or kind == "application/octet-stream"):
                return client.download(str(output["url"]), MAX_AUDIO_BYTES)
        raise WiroRunError(f"{model} returned no audio file.")

    def validate_credentials(self, model: str, credentials: Mapping) -> None:
        """For a voice model added by ID. Spends nothing: it reads the account and the catalog."""
        try:
            client = RunClient(credentials)
            client.check_credentials()
            if tts_schema(model, client.model_detail(model)) is None:
                raise CredentialsValidateFailedError(f"{model} is not a text to speech model with voices.")
        except WiroRunError as exc:
            raise CredentialsValidateFailedError(str(exc)) from exc

    def get_customizable_model_schema(self, model: str, credentials: Mapping) -> AIModelEntity | None:
        try:
            schema = tts_schema(model, RunClient(credentials).model_detail(model))
        except WiroRunError:
            return None
        if schema is None:
            return None
        schema["fetch_from"] = FetchFrom.CUSTOMIZABLE_MODEL.value
        return AIModelEntity.model_validate(schema)

    @property
    def _invoke_error_mapping(self) -> dict:
        return {InvokeBadRequestError: [WiroRunError]}
