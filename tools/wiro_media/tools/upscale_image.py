from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities import ParameterOption
from dify_plugin.entities.tool import ToolInvokeMessage

from wiroapi.client import WiroError
from wiroapi.generate import Setting, build_parameters
from wiroapi.tooling import as_list, client_for, model_options, parse_json_object, run_and_deliver

DEFAULT_MODEL = "xinntao/real-esrgan"
WAIT_SECONDS = 300
SCALE_IDS = ("outscale", "scale", "upscale", "upscaleFactor", "scaleFactor")


class UpscaleImageTool(Tool):
    def _fetch_parameter_options(self, parameter: str) -> list[ParameterOption]:
        if parameter != "model":
            return []
        return model_options(client_for(self), ["upscale"])

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        image = as_list(tool_parameters.get("image"))
        if not image:
            raise ValueError("Add the image to upscale.")
        model_id = str(tool_parameters.get("model") or DEFAULT_MODEL).strip()
        try:
            client = client_for(self)
            parameters, notes = build_parameters(
                client,
                model_id,
                files=image[:1],
                settings=[Setting(SCALE_IDS, tool_parameters.get("scale"), "scale", numeric=True)],
                extra=parse_json_object(tool_parameters.get("extra_parameters"), "Extra parameters"),
            )
            yield from run_and_deliver(self, client, model_id, parameters, WAIT_SECONDS, notes)
        except WiroError as exc:
            raise ValueError(str(exc)) from None
