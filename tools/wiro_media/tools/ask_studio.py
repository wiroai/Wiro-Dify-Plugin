from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities import I18nObject, ParameterOption
from dify_plugin.entities.tool import ToolInvokeMessage

from wiroapi.client import StillRunning, WiroError
from wiroapi.tooling import as_list, client_for, deliver_reply, file_parts, still_running_reply, wait_value

DEFAULT_SESSION = "dify"


class AskStudioTool(Tool):
    def _fetch_parameter_options(self, parameter: str) -> list[ParameterOption]:
        if parameter != "chat_model":
            return []
        status = client_for(self)._post("/Studio/Status", {})
        models = ((status.get("tokenRates") or {}).get("models")) or {}
        return [
            ParameterOption(value=slug, label=I18nObject(en_US=str(info.get("label") or slug)))
            for slug, info in models.items()
            if isinstance(info, dict) and info.get("selectable")
        ]

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        message = str(tool_parameters.get("message") or "").strip()
        files = as_list(tool_parameters.get("files"))
        if not message and not files:
            raise ValueError("Tell Studio what to make, or attach files.")
        session = str(tool_parameters.get("session") or DEFAULT_SESSION).strip()
        wait = wait_value(tool_parameters.get("wait_seconds"), 480)
        try:
            client = client_for(self)
            sent = client.studio_send(
                message, session, file_parts(files) if files else None, tool_parameters.get("chat_model") or None
            )
            token, guid = str(sent.get("agenttoken") or ""), sent.get("messageguid")
            record: dict[str, Any] = {"session": session, "message_id": guid}
            try:
                reply = client.wait_reply(lambda: client.studio_detail(token, session), wait)
            except StillRunning:
                hint = (
                    f"Studio is still working on this. The results will appear in the Studio session "
                    f"{session} on wiro.ai, and a later message to the same session continues it."
                )
                yield from still_running_reply(self, record, hint)
                return
            text = str(reply.get("response") or "")
            runs = [
                task
                for task in client.studio_tasks(50)
                if any(o.get("url") and o["url"] in text for o in task.get("outputs") or [])
            ]
            chat_cost = float(reply.get("tokencost") or 0) / 100
            run_cost = sum(float(task.get("totalcost") or 0) for task in runs)
            record.update(
                {
                    "chat_cost_usd": round(chat_cost, 6),
                    "model_runs": [
                        {
                            "model": f"{(t.get('model') or {}).get('slugowner')}/{(t.get('model') or {}).get('slugproject')}",
                            "cost_usd": t.get("totalcost"),
                        }
                        for t in runs
                    ],
                    "cost_usd": round(chat_cost + run_cost, 6),
                    "tokens": reply.get("totaltokens"),
                }
            )
            yield from deliver_reply(self, client, reply, "Studio", record)
        except WiroError as exc:
            raise ValueError(str(exc)) from None
