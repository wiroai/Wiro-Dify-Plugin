from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities import I18nObject, ParameterOption
from dify_plugin.entities.tool import ToolInvokeMessage

from wiroapi.client import StillRunning, WiroError
from wiroapi.tooling import as_list, client_for, deliver_reply, file_parts, still_running_reply, wait_value

DEFAULT_SESSION = "dify"
AGENT_STATUS = {
    0: "stopped",
    1: "stopping",
    2: "starting",
    3: "starting",
    4: "running",
    5: "upgrading",
    6: "setup needed",
}


class MessageAgentTool(Tool):
    def _fetch_parameter_options(self, parameter: str) -> list[ParameterOption]:
        if parameter != "agent":
            return []
        options = []
        for row in client_for(self).my_agents():
            title = str(row.get("title") or (row.get("agent") or {}).get("title") or row.get("guid"))
            state = AGENT_STATUS.get(int(row.get("status") or 0), "unknown")
            options.append(ParameterOption(value=str(row.get("guid")), label=I18nObject(en_US=f"{title} ({state})")))
        return options

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        agent = str(tool_parameters.get("agent") or "").strip()
        message = str(tool_parameters.get("message") or "").strip()
        files = as_list(tool_parameters.get("files"))
        if not agent:
            raise ValueError("Choose the Wiro AI agent to message.")
        if not message and not files:
            raise ValueError("Write the message, or attach files.")
        session = str(tool_parameters.get("session") or DEFAULT_SESSION).strip()
        wait = wait_value(tool_parameters.get("wait_seconds"), 300)
        try:
            client = client_for(self)
            sent = client.agent_send(agent, message, session, file_parts(files) if files else None)
            token = str(sent.get("agenttoken") or "")
            record: dict[str, Any] = {"agent": agent, "session": session, "message_id": sent.get("messageguid")}
            try:
                reply = client.wait_reply(lambda: client.agent_detail(token, session), wait)
            except StillRunning:
                hint = (
                    f"The agent is still working on this in session {session}. Its answer will appear in that session."
                )
                yield from still_running_reply(self, record, hint)
                return
            record["tokens"] = reply.get("totaltokens")
            yield from deliver_reply(self, client, reply, "The agent", record)
        except WiroError as exc:
            raise ValueError(str(exc)) from None
