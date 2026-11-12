from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities import ParameterOption
from dify_plugin.entities.tool import ToolInvokeMessage

from wiroapi.client import WiroError
from wiroapi.generate import build_parameters
from wiroapi.tooling import as_list, client_for, model_options, parse_json_object, run_and_deliver

DEFAULT_MODEL = "google/nano-banana-2"
WAIT_SECONDS = 240


class EditImageTool(Tool):
    def _fetch_parameter_options(self, parameter: str) -> list[ParameterOption]:
        if parameter != "model":
            return []
        return model_options(client_for(self), ["image-editing"])

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        images = as_list(tool_parameters.get("images"))
        prompt = str(tool_parameters.get("prompt") or "").strip()
        if not images:
            raise ValueError("Add the image to edit.")
        if not prompt:
            raise ValueError("Describe the change to make.")
        model_id = str(tool_parameters.get("model") or DEFAULT_MODEL).strip()
        try:
            client = client_for(self)
            parameters, notes = build_parameters(
                client,
                model_id,
                text=prompt,
                files=images,
                aspect_ratio=tool_parameters.get("aspect_ratio") or None,
                extra=parse_json_object(tool_parameters.get("extra_parameters"), "Extra parameters"),
            )
            yield from run_and_deliver(self, client, model_id, parameters, WAIT_SECONDS, notes)
        except WiroError as exc:
            raise ValueError(str(exc)) from None
