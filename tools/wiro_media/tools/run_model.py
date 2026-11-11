from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from wiroapi.client import WiroError
from wiroapi.params import fill_required, find, image_param, is_file, param_items, put_files
from wiroapi.tooling import as_list, client_for, parse_json_object, run_and_deliver, upload_files

MIN_WAIT, DEFAULT_WAIT, MAX_WAIT = 10, 240, 540


class RunModelTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        model_id = str(tool_parameters.get("model") or "").strip()
        if not model_id:
            raise ValueError("Give a model ID in owner/model form. Search Models finds them.")
        wait = tool_parameters.get("wait_seconds")
        wait_seconds = min(MAX_WAIT, max(MIN_WAIT, int(float(wait)))) if wait not in (None, "") else DEFAULT_WAIT
        try:
            client = client_for(self)
            items = param_items(client.model_detail(model_id))
            parameters = parse_json_object(tool_parameters.get("parameters"), "Parameters")
            files = as_list(tool_parameters.get("files"))
            if files:
                name = str(tool_parameters.get("file_parameter") or "").strip()
                target = find(items, name) if name else image_param(items) or next(filter(is_file, items), None)
                if target is None or not is_file(target):
                    wanted = f"a file field called {name}" if name else "a file field"
                    raise ValueError(f"{model_id} has no {wanted}. Get Model Parameters lists its fields.")
                put_files(target, upload_files(client, files), parameters)
            parameters = fill_required(items, parameters)
            yield from run_and_deliver(self, client, model_id, parameters, wait_seconds)
        except WiroError as exc:
            raise ValueError(str(exc)) from None
