from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities import ParameterOption
from dify_plugin.entities.tool import ToolInvokeMessage

from wiroapi.client import WiroError
from wiroapi.generate import Setting, build_parameters
from wiroapi.tooling import as_list, client_for, model_options, parse_json_object, run_and_deliver

DEFAULT_MODEL = "pruna/p-video-avatar"
WAIT_SECONDS = 480
SCRIPT_IDS = ("voiceScript", "script", "text", "speechText")
PROMPT_IDS = ("prompt", "videoPrompt")


class LipsyncTool(Tool):
    def _fetch_parameter_options(self, parameter: str) -> list[ParameterOption]:
        if parameter != "model":
            return []
        return model_options(client_for(self), ["talking-head"])

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        image = as_list(tool_parameters.get("image"))
        audio = as_list(tool_parameters.get("audio"))
        script = str(tool_parameters.get("script") or "").strip()
        if not image:
            raise ValueError("Add a picture of the face that should speak.")
        if not audio and not script:
            raise ValueError("Add the speech audio, or a script for models that read text aloud.")
        model_id = str(tool_parameters.get("model") or DEFAULT_MODEL).strip()
        try:
            client = client_for(self)
            parameters, notes = build_parameters(
                client,
                model_id,
                files=image[:1],
                audio=audio[:1] or None,
                settings=[
                    Setting(SCRIPT_IDS, script, "script"),
                    Setting(PROMPT_IDS, str(tool_parameters.get("prompt") or "").strip(), "prompt"),
                ],
                extra=parse_json_object(tool_parameters.get("extra_parameters"), "Extra parameters"),
            )
            yield from run_and_deliver(self, client, model_id, parameters, WAIT_SECONDS, notes)
        except WiroError as exc:
            raise ValueError(str(exc)) from None
