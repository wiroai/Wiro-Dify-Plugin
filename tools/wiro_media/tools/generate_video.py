from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities import ParameterOption
from dify_plugin.entities.tool import ToolInvokeMessage

from wiroapi.client import WiroError
from wiroapi.generate import build_parameters
from wiroapi.tooling import as_list, client_for, model_options, parse_json_object, run_and_deliver

DEFAULT_MODEL = "bytedance/seedance-v1-pro-fast"
# Dify stops a plugin call after 600 s by default, so the wait ends earlier.
WAIT_SECONDS = 480


class GenerateVideoTool(Tool):
    def _fetch_parameter_options(self, parameter: str) -> list[ParameterOption]:
        if parameter != "model":
            return []
        return model_options(client_for(self), ["text-to-video", "image-to-video"])

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        prompt = str(tool_parameters.get("prompt") or "").strip()
        image = as_list(tool_parameters.get("image"))
        if not prompt and not image:
            raise ValueError("Write a prompt, add a start image, or both.")
        model_id = str(tool_parameters.get("model") or DEFAULT_MODEL).strip()
        try:
            client = client_for(self)
            parameters, notes = build_parameters(
                client,
                model_id,
                text=prompt or None,
                files=image[:1],
                aspect_ratio=tool_parameters.get("aspect_ratio") or None,
                extra=parse_json_object(tool_parameters.get("extra_parameters"), "Extra parameters"),
            )
            for note in notes:
                yield self.create_text_message(note + "\n")
            yield from run_and_deliver(self, client, model_id, parameters, WAIT_SECONDS)
        except WiroError as exc:
            raise ValueError(str(exc)) from None
