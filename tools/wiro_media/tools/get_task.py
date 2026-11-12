from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from wiroapi.client import TERMINAL_STATUSES, WORKFLOW_FINAL, StillRunning, TaskStillRunning, WiroError
from wiroapi.tooling import client_for, deliver, deliver_workflow, still_running, still_running_reply

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
                try:
                    task = client.task(token=reference)
                except WiroError as task_error:
                    yield from self._workflow_run(client, reference, wait_seconds, task_error)
                    return
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

    def _workflow_run(self, client, token: str, wait_seconds: float, task_error: WiroError) -> Generator:
        """The reference is not a task: try it as a workflow run token."""
        try:
            body = client.workflow_run(token)
        except WiroError:
            raise task_error from None
        run = body.get("workflowrun") or {}
        if not run:
            raise task_error
        slug = str(run.get("workflowslug") or "workflow")
        if run.get("status") not in WORKFLOW_FINAL and wait_seconds > 0:
            try:
                body = client.wait_workflow(token, wait_seconds)
            except StillRunning:
                pass
        if (body.get("workflowrun") or {}).get("status") not in WORKFLOW_FINAL:
            record = {"workflow": slug, "run_token": token}
            yield from still_running_reply(
                self, record, f"Workflow {slug} is still running. Ask again in a few minutes."
            )
            return
        yield from deliver_workflow(self, client, body, slug)
