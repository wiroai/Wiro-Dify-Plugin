from __future__ import annotations

import json
from collections.abc import Generator, Mapping
from typing import Any

import requests
from dify_plugin import OAICompatLargeLanguageModel
from dify_plugin.entities.model import AIModelEntity, FetchFrom
from dify_plugin.entities.model.llm import LLMMode, LLMResult
from dify_plugin.entities.model.message import (
    DocumentPromptMessageContent,
    ImagePromptMessageContent,
    PromptMessage,
    PromptMessageContentType,
    PromptMessageTool,
    TextPromptMessageContent,
    UserPromptMessage,
)
from dify_plugin.errors.model import (
    CredentialsValidateFailedError,
    InvokeAuthorizationError,
    InvokeBadRequestError,
    InvokeError,
)

from models._wiro import (
    GATEWAY_URL,
    MODEL_ID_RE,
    MODELS_PAGE,
    USER_AGENT,
    WiroGatewayError,
    bearer_token,
    check_key,
    fallback_schema,
    fetch_model,
    model_schema,
)


class WiroLargeLanguageModel(OAICompatLargeLanguageModel):
    """Chat models on the Wiro AI gateway, which speaks the OpenAI Chat Completions protocol."""

    def _gateway_credentials(self, credentials: Mapping[str, Any]) -> dict:
        try:
            token = bearer_token(credentials)
        except WiroGatewayError as exc:
            raise InvokeAuthorizationError(str(exc)) from exc
        prepared = dict(credentials)
        prepared.pop("api_secret", None)
        prepared.update(
            {
                "api_key": token,
                "endpoint_url": GATEWAY_URL,
                "mode": LLMMode.CHAT.value,
                "function_calling_type": "tool_call",
                "stream_function_calling": "supported",
                "extra_headers": {"User-Agent": USER_AGENT},
            }
        )
        return prepared

    def _invoke(
        self,
        model: str,
        credentials: dict,
        prompt_messages: list[PromptMessage],
        model_parameters: dict,
        tools: list[PromptMessageTool] | None = None,
        stop: list[str] | None = None,
        stream: bool = True,
        user: str | None = None,
    ) -> LLMResult | Generator:
        parameters = dict(model_parameters)
        if stream:
            # The gateway sends real token counts in a last chunk when asked to.
            parameters["stream_options"] = {"include_usage": True}
        return super()._invoke(
            model,
            self._gateway_credentials(credentials),
            prompt_messages,
            parameters,
            tools,
            stop,
            stream,
            user,
        )

    def get_num_tokens(
        self,
        model: str,
        credentials: dict,
        prompt_messages: list[PromptMessage],
        tools: list[PromptMessageTool] | None = None,
    ) -> int:
        return super().get_num_tokens(model, self._gateway_credentials(credentials), prompt_messages, tools)

    def validate_credentials(self, model: str, credentials: dict) -> None:
        """Called for a model added by hand. Spends nothing: it only reads the catalog."""
        if not MODEL_ID_RE.match(model or ""):
            raise CredentialsValidateFailedError(
                "Use the full model ID in owner/model form, for example openai/gpt-5-4-mini."
            )
        try:
            check_key(credentials)
            entry = fetch_model(model, credentials)
        except WiroGatewayError as exc:
            raise CredentialsValidateFailedError(str(exc)) from exc
        if entry is None:
            raise CredentialsValidateFailedError(
                f"The Wiro AI gateway does not list {model}. Copy a model ID from {MODELS_PAGE}."
            )

    def get_customizable_model_schema(self, model: str, credentials: Mapping) -> AIModelEntity | None:
        """Read context size, output limit and features of a hand-added model from the catalog."""
        try:
            entry = fetch_model(model, credentials)
        except WiroGatewayError:
            entry = None
        schema = model_schema(entry) if entry else fallback_schema(model)
        schema["fetch_from"] = FetchFrom.CUSTOMIZABLE_MODEL.value
        return AIModelEntity.model_validate(schema)

    def _convert_prompt_message_to_dict(self, message: PromptMessage, credentials: dict | None = None) -> dict:
        """Send PDF and text documents as OpenAI file parts; the base class leaves them out."""
        if not isinstance(message, UserPromptMessage) or not isinstance(message.content, list):
            return super()._convert_prompt_message_to_dict(message, credentials)
        parts: list[dict] = []
        for content in message.content:
            if isinstance(content, TextPromptMessageContent) or content.type == PromptMessageContentType.TEXT:
                parts.append({"type": "text", "text": content.data})
            elif isinstance(content, ImagePromptMessageContent):
                parts.append({"type": "image_url", "image_url": {"url": content.data, "detail": content.detail.value}})
            elif isinstance(content, DocumentPromptMessageContent):
                parts.append(self._document_part(content))
            else:
                raise InvokeBadRequestError(
                    f"Wiro AI chat models do not take {content.type.value} input. Send text, images or documents."
                )
        converted: dict[str, Any] = {"role": "user", "content": parts}
        if message.name:
            converted["name"] = message.name
        return converted

    @staticmethod
    def _document_part(content: DocumentPromptMessageContent) -> dict:
        filename = content.filename or f"document.{content.format or 'pdf'}"
        if content.base64_data:
            file_data = f"data:{content.mime_type};base64,{content.base64_data}"
        else:
            file_data = content.url
        return {"type": "file", "file": {"filename": filename, "file_data": file_data}}

    def _handle_generate_response(
        self,
        model: str,
        credentials: dict,
        response: requests.Response,
        prompt_messages: list[PromptMessage],
    ) -> LLMResult:
        # A request that runs past 60 seconds gets its 200 headers early, so a late
        # failure arrives as an error object inside a 200 body.
        try:
            body = response.json()
        except ValueError as exc:
            raise InvokeError(f"Wiro AI sent a response that is not JSON: {response.text[:300]}") from exc
        if isinstance(body, dict) and body.get("error") and not body.get("choices"):
            error = body["error"] if isinstance(body["error"], dict) else {"message": str(body["error"])}
            raise InvokeError(f"Wiro AI: {error.get('message') or json.dumps(error)[:300]}")
        # requests keeps the body, so the base class can parse it again.
        return super()._handle_generate_response(model, credentials, response, prompt_messages)
