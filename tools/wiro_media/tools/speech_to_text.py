from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities import ParameterOption
from dify_plugin.entities.tool import ToolInvokeMessage

from wiroapi.client import WiroError
from wiroapi.generate import Setting, build_parameters
from wiroapi.tooling import as_list, client_for, model_options, parse_json_object, plain_transcript, run_and_deliver

DEFAULT_MODEL = "elevenlabs/speech-to-text"
WAIT_SECONDS = 300
LANGUAGE_IDS = ("language", "languageCode", "lang")


class SpeechToTextTool(Tool):
    def _fetch_parameter_options(self, parameter: str) -> list[ParameterOption]:
        if parameter != "model":
            return []
        return model_options(client_for(self), ["speech-to-text"], skip_realtime=True)

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        audio = as_list(tool_parameters.get("audio"))
        if not audio:
            raise ValueError("Add the audio or video file to transcribe.")
        model_id = str(tool_parameters.get("model") or DEFAULT_MODEL).strip()
        media = audio[:1]
        is_video = str(getattr(media[0], "mime_type", "") or "").startswith("video/")
        try:
            client = client_for(self)
            parameters, notes = build_parameters(
                client,
                model_id,
                audio=None if is_video else media,
                video=media if is_video else None,
                settings=[Setting(LANGUAGE_IDS, tool_parameters.get("language"), "language")],
                extra=parse_json_object(tool_parameters.get("extra_parameters"), "Extra parameters"),
            )
            yield from run_and_deliver(self, client, model_id, parameters, WAIT_SECONDS, notes, plain_transcript)
        except WiroError as exc:
            raise ValueError(str(exc)) from None
