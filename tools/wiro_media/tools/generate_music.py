from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities import ParameterOption
from dify_plugin.entities.tool import ToolInvokeMessage

from wiroapi.client import WiroError
from wiroapi.generate import build_parameters
from wiroapi.params import find, option_values, param_items
from wiroapi.tooling import client_for, model_options, parse_json_object, run_and_deliver

DEFAULT_MODEL = "elevenlabs/text-to-music-v2"
WAIT_SECONDS = 240


class GenerateMusicTool(Tool):
    def _fetch_parameter_options(self, parameter: str) -> list[ParameterOption]:
        if parameter != "model":
            return []
        return model_options(client_for(self), ["text-to-music"])

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        prompt = str(tool_parameters.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("Describe the music or sound you want.")
        model_id = str(tool_parameters.get("model") or DEFAULT_MODEL).strip()
        try:
            client = client_for(self)
            extra = parse_json_object(tool_parameters.get("extra_parameters"), "Extra parameters")
            notes = []
            duration = tool_parameters.get("duration")
            if duration not in (None, ""):
                seconds = str(int(float(duration)))
                item = find(param_items(client.model_detail(model_id)), "duration", "seconds", "length")
                options = option_values(item) if item else []
                if item and (not options or seconds in options):
                    extra.setdefault(str(item["id"]), seconds)
                elif item:
                    notes.append(f"{model_id} takes these durations: {', '.join(options)} s. It used its default.")
                else:
                    notes.append(f"{model_id} has no duration setting, so the duration was left out.")
            parameters, more_notes = build_parameters(client, model_id, text=prompt, extra=extra)
            for note in notes + more_notes:
                yield self.create_text_message(note + "\n")
            yield from run_and_deliver(self, client, model_id, parameters, WAIT_SECONDS)
        except WiroError as exc:
            raise ValueError(str(exc)) from None
