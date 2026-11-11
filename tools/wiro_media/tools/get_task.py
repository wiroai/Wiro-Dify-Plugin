from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from wiroapi.client import TERMINAL_STATUSES, TaskStillRunning, WiroError
from wiroapi.tooling import client_for, deliver, still_running

MAX_WAIT = 480


class GetTaskTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        reference = str(tool_parameters.get("task") or "").strip()
        if not reference:
            raise ValueError("Give the task token or task ID that a Wiro AI tool returned.")
        wait = tool_parameters.get("wait_seconds")
        wait_seconds = min(MAX_WAIT, max(0, int(float(wait)))) if wait not in (None, "") else 60
        try:
            client = client_for(self)
            if reference.isdigit():
                task = client.task(taskid=reference)
            else:
                task = client.task(token=reference)
            model_id = f"{task.get('modelslugowner') or 'wiro'}/{task.get('modelslugproject') or 'model'}"
            if task.get("status") not in TERMINAL_STATUSES and wait_seconds > 0:
                try:
                    task = client.wait(str(task.get("socketaccesstoken") or reference), wait_seconds)
                except TaskStillRunning as running:
                    task = {**task, **running.task}
            if task.get("status") not in TERMINAL_STATUSES:
                yield from still_running(self, task, model_id)
                return
            yield from deliver(self, client, task, model_id)
        except WiroError as exc:
            raise ValueError(str(exc)) from None
