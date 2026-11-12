import json
from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities import I18nObject, ParameterOption
from dify_plugin.entities.tool import ToolInvokeMessage

from wiroapi.client import StillRunning, WiroError
from wiroapi.tooling import (
    as_list,
    client_for,
    deliver_workflow,
    parse_json_object,
    still_running_reply,
    upload_files,
    wait_value,
)

FILE_FIELDS = {"image", "audio", "video", "pdf", "file"}


def schema_inputs(detail: dict) -> dict:
    contents = detail.get("contents") or {}
    if isinstance(contents, str):
        contents = json.loads(contents or "{}")
    return (contents.get("schema") or {}).get("input") or {}


def file_fields(schema: dict) -> list[str]:
    return [key for key, spec in schema.items() if str(((spec or {}).get("ui") or {}).get("field")) in FILE_FIELDS]


class RunWorkflowTool(Tool):
    def _fetch_parameter_options(self, parameter: str) -> list[ParameterOption]:
        if parameter != "workflow":
            return []
        options = []
        for row in client_for(self).list_workflows():
            slug = f"{row.get('slug')}-{row.get('slugid')}"
            title = str(row.get("title") or slug)
            options.append(ParameterOption(value=slug, label=I18nObject(en_US=f"{title} ({slug})")))
        return options

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        slug = str(tool_parameters.get("workflow") or "").strip()
        if not slug:
            raise ValueError("Choose the Wiro AI workflow to run.")
        inputs = parse_json_object(tool_parameters.get("inputs"), "Inputs")
        files = as_list(tool_parameters.get("files"))
        wait = wait_value(tool_parameters.get("wait_seconds"), 480)
        try:
            client = client_for(self)
            detail = client.workflow_detail(slug)
            schema = schema_inputs(detail)
            if files:
                field = str(tool_parameters.get("file_input") or "").strip() or next(iter(file_fields(schema)), "")
                if field not in schema:
                    raise ValueError(
                        f"{slug} has no file input called {field or '(none)'}. Its inputs: {', '.join(schema)}."
                    )
                urls = upload_files(client, files)
                inputs[field] = urls[0] if len(urls) == 1 else urls
            unknown = [key for key in inputs if schema and key not in schema]
            if unknown:
                raise ValueError(f"{slug} has no input called {', '.join(unknown)}. Its inputs: {', '.join(schema)}.")
            missing = [key for key in detail.get("requiredinputs") or [] if inputs.get(key) in (None, "", [])]
            if missing:
                raise ValueError(f"{slug} needs a value for: {', '.join(missing)}.")
            token = client.run_workflow(slug, inputs)
            try:
                body = client.wait_workflow(token, wait)
            except StillRunning:
                record = {"workflow": slug, "run_token": token}
                hint = (
                    f"Workflow {slug} is still running on Wiro AI. Use Get Task Result with the run token "
                    f"{token} to collect its results."
                )
                yield from still_running_reply(self, record, hint)
                return
            yield from deliver_workflow(self, client, body, slug)
        except WiroError as exc:
            raise ValueError(str(exc)) from None
