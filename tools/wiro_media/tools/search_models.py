from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from wiroapi.client import WiroError
from wiroapi.describe import model_card
from wiroapi.tooling import client_for


class SearchModelsTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        query = str(tool_parameters.get("query") or "").strip() or None
        category = str(tool_parameters.get("category") or "").strip()
        category = None if category in ("", "any") else category
        limit = tool_parameters.get("limit")
        limit = min(50, max(1, int(float(limit)))) if limit not in (None, "") else 10
        try:
            models = client_for(self).list_models(category=category, search=query, limit=limit)
        except WiroError as exc:
            raise ValueError(str(exc)) from None
        cards = [model_card(model) for model in models[:limit]]
        if not cards:
            yield self.create_text_message("No Wiro AI model matched. Try a shorter search or another category.")
        else:
            lines = [
                f"{card['model']}: {card['title']} ({', '.join(card['categories'][:4])}) {card['price']}"
                for card in cards
            ]
            yield self.create_text_message("\n".join(lines))
        yield self.create_json_message({"models": cards})
