from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from wiroapi.client import WiroError
from wiroapi.describe import model_card, parameter_rows
from wiroapi.tooling import client_for


class GetModelTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        model_id = str(tool_parameters.get("model") or "").strip()
        if not model_id:
            raise ValueError("Give a model ID in owner/model form. Search Models finds them.")
        try:
            detail = client_for(self).model_detail(model_id)
        except WiroError as exc:
            raise ValueError(str(exc)) from None
        card = model_card(detail)
        rows = parameter_rows(detail)
        lines = [f"{card['model']}: {card['title']}", card["description"], f"Price: {card['price']}", "", "Parameters:"]
        for row in rows:
            flags = "required" if row["required"] else "optional"
            extra = []
            if row.get("default") is not None:
                extra.append(f"default {row['default']}")
            if row.get("options"):
                extra.append("options " + ", ".join(row["options"][:20]))
            if row.get("note"):
                extra.append(row["note"])
            lines.append(f"- {row['id']} ({row['type']}, {flags}){': ' + '; '.join(extra) if extra else ''}")
        yield self.create_text_message("\n".join(line for line in lines if line is not None))
        yield self.create_json_message({**card, "parameters": rows})
