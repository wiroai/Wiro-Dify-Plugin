"""Offline tests: schema building, credentials and message conversion. No network."""

import base64

import pytest
import yaml
from dify_plugin.entities.model import AIModelEntity, ModelFeature, ModelPropertyKey
from dify_plugin.entities.model.message import (
    DocumentPromptMessageContent,
    ImagePromptMessageContent,
    TextPromptMessageContent,
    UserPromptMessage,
)
from dify_plugin.errors.model import InvokeAuthorizationError

from conftest import PLUGIN_ROOT, load_schemas
from models._wiro import WiroGatewayError, bearer_token, fallback_schema, model_schema, per_million

ENTRY = {
    "id": "openai/gpt-5-4-mini",
    "context_length": 400000,
    "max_tokens": 65536,
    "pricing": {"prompt": "0.00000075", "completion": "0.0000045"},
    "supported_parameters": [
        "max_completion_tokens",
        "max_tokens",
        "reasoning_effort",
        "response_format",
        "structured_outputs",
        "tool_choice",
        "tools",
    ],
    "capabilities": {
        "endpoints": ["anthropic", "chat", "responses"],
        "input_modalities": ["text", "image", "document"],
        "function_tools": True,
        "structured_outputs": True,
        "structured_output_modes": ["json_object", "json_schema"],
        "generation_controls": ["max_output_tokens", "reasoning_effort", "verbosity"],
    },
}


def test_bearer_token_forms():
    assert bearer_token({"api_key": " k1 "}) == "k1"
    assert bearer_token({"api_key": "k1", "api_secret": "s1"}) == "k1:s1"
    assert bearer_token({"api_key": "k1:s1", "api_secret": "s2"}) == "k1:s1"
    with pytest.raises(WiroGatewayError):
        bearer_token({"api_key": ""})


def test_per_million():
    assert per_million("0.00000075") == "0.75"
    assert per_million("0.0000045") == "4.5"
    assert per_million("0.00000005") == "0.05"
    assert per_million(None) is None


def test_model_schema_from_catalog_entry():
    schema = AIModelEntity.model_validate(model_schema(ENTRY))
    assert schema.model == "openai/gpt-5-4-mini"
    assert schema.model_properties[ModelPropertyKey.CONTEXT_SIZE] == 400000
    features = set(schema.features or [])
    assert {
        ModelFeature.TOOL_CALL,
        ModelFeature.MULTI_TOOL_CALL,
        ModelFeature.STREAM_TOOL_CALL,
        ModelFeature.VISION,
        ModelFeature.DOCUMENT,
        ModelFeature.STRUCTURED_OUTPUT,
    } <= features
    rules = {rule.name: rule for rule in schema.parameter_rules}
    assert rules["max_tokens"].max == 65536
    assert rules["max_tokens"].default == 8192
    assert rules["reasoning_effort"].options == ["low", "medium", "high"]
    assert rules["verbosity"].options == ["low", "medium", "high"]
    assert rules["response_format"].options == ["text", "json_object", "json_schema"]
    assert "json_schema" in rules
    assert "temperature" not in rules
    assert schema.pricing is not None
    assert str(schema.pricing.input) == "0.75"


def test_text_only_model_has_no_vision():
    entry = {
        "id": "qwen/qwen2-5-7b-instruct",
        "context_length": 32768,
        "max_tokens": 2048,
        "pricing": None,
        "supported_parameters": ["temperature", "top_p", "top_k", "seed", "response_format"],
        "capabilities": {
            "input_modalities": ["text"],
            "function_tools": True,
            "structured_outputs": True,
            "structured_output_modes": ["json_object"],
        },
    }
    schema = AIModelEntity.model_validate(model_schema(entry))
    features = set(schema.features or [])
    assert ModelFeature.VISION not in features
    assert ModelFeature.STRUCTURED_OUTPUT not in features
    assert ModelFeature.AGENT_THOUGHT not in features
    assert schema.pricing is None
    rules = {rule.name: rule for rule in schema.parameter_rules}
    assert rules["temperature"].max == 2.0
    assert rules["response_format"].options == ["text", "json_object"]
    assert "json_schema" not in rules


def test_fallback_schema_is_valid():
    schema = AIModelEntity.model_validate(fallback_schema("acme/new-model"))
    assert schema.model_properties[ModelPropertyKey.CONTEXT_SIZE] == 128000


def test_every_packaged_model_file_loads():
    schemas = load_schemas()
    assert len(schemas) >= 20
    position = yaml.safe_load((PLUGIN_ROOT / "models" / "llm" / "_position.yaml").read_text())
    assert sorted(position) == sorted(schema.model for schema in schemas)
    for schema in schemas:
        assert "/" in schema.model
        assert schema.model_properties[ModelPropertyKey.CONTEXT_SIZE] > 0


def test_documents_become_file_parts(llm):
    pdf = base64.b64encode(b"%PDF-1.4 test").decode()
    message = UserPromptMessage(
        content=[
            TextPromptMessageContent(data="Read this"),
            ImagePromptMessageContent(format="png", mime_type="image/png", base64_data="aGk="),
            DocumentPromptMessageContent(format="pdf", mime_type="application/pdf", base64_data=pdf, filename="a.pdf"),
        ]
    )
    converted = llm._convert_prompt_message_to_dict(message, {"function_calling_type": "tool_call"})
    assert converted["role"] == "user"
    kinds = [part["type"] for part in converted["content"]]
    assert kinds == ["text", "image_url", "file"]
    assert converted["content"][2]["file"] == {
        "filename": "a.pdf",
        "file_data": f"data:application/pdf;base64,{pdf}",
    }


def test_missing_key_is_an_auth_error(llm):
    with pytest.raises(InvokeAuthorizationError):
        llm._gateway_credentials({"api_key": ""})


def test_gateway_credentials_never_keep_the_secret_field(llm):
    prepared = llm._gateway_credentials({"api_key": "k", "api_secret": "s"})
    assert prepared["api_key"] == "k:s"
    assert "api_secret" not in prepared
    assert prepared["endpoint_url"] == "https://llm.wiro.ai/v1"
