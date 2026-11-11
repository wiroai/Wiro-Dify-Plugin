"""Live tests against the Wiro AI gateway.

They run only when WIRO_API_KEY is set and use cheap models with short prompts.
"""

import base64
import json
import struct
import zlib

import pytest
from dify_plugin.entities.model import ModelFeature, ModelPropertyKey
from dify_plugin.entities.model.message import (
    AssistantPromptMessage,
    DocumentPromptMessageContent,
    ImagePromptMessageContent,
    PromptMessageTool,
    SystemPromptMessage,
    TextPromptMessageContent,
    ToolPromptMessage,
    UserPromptMessage,
)
from dify_plugin.errors.model import CredentialsValidateFailedError

from provider_loader import new_provider

CHEAP = "openai/gpt-5-nano"
FAST = {"reasoning_effort": "low", "max_tokens": 1200}


def collect(chunks):
    text, tool_calls, usage = "", [], None
    for chunk in chunks:
        message = chunk.delta.message
        if isinstance(message.content, str):
            text += message.content
        if message.tool_calls:
            tool_calls.extend(message.tool_calls)
        if chunk.delta.usage:
            usage = chunk.delta.usage
    return text, tool_calls, usage


def red_png() -> str:
    width = height = 256
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    return base64.b64encode(png).decode()


def tiny_pdf(text: str) -> str:
    content = f"BT /F1 18 Tf 50 700 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return base64.b64encode(out).decode()


def test_provider_accepts_the_key(credentials):
    provider = new_provider()
    provider.validate_provider_credentials(credentials)


def test_provider_rejects_a_wrong_key():
    provider = new_provider()
    with pytest.raises(CredentialsValidateFailedError, match="did not accept"):
        provider.validate_provider_credentials({"api_key": "0" * 32})


def test_blocking_answer(llm, credentials):
    chunks = llm.invoke(
        CHEAP,
        credentials,
        [SystemPromptMessage(content="Answer in one word."), UserPromptMessage(content="Reply with the word PONG.")],
        dict(FAST),
        stream=False,
    )
    text, _, usage = collect(chunks)
    assert "PONG" in text.upper()
    assert usage is not None and usage.prompt_tokens > 0


def test_streamed_answer_reports_usage(llm, credentials):
    chunks = llm.invoke(CHEAP, credentials, [UserPromptMessage(content="Say hello in French, one word.")], dict(FAST))
    text, _, usage = collect(chunks)
    assert text.strip()
    assert usage is not None and usage.completion_tokens > 0


def test_tool_call_round_trip(llm, credentials):
    tool = PromptMessageTool(
        name="get_weather",
        description="Return the current weather for a city",
        parameters={"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
    )
    question = UserPromptMessage(content="What is the weather in Paris right now? Use the tool.")
    _, calls, _ = collect(llm.invoke(CHEAP, credentials, [question], dict(FAST), tools=[tool]))
    assert calls and calls[0].function.name == "get_weather"
    assert "paris" in json.loads(calls[0].function.arguments)["city"].lower()

    follow_up = [
        question,
        AssistantPromptMessage(content="", tool_calls=calls[:1]),
        ToolPromptMessage(content='{"temperature_c": 12, "condition": "rain"}', tool_call_id=calls[0].id),
    ]
    text, _, _ = collect(llm.invoke(CHEAP, credentials, follow_up, dict(FAST), tools=[tool]))
    assert "12" in text


def test_json_schema_output(llm, credentials):
    schema = {
        "name": "llm_response",
        "schema": {
            "type": "object",
            "properties": {"city": {"type": "string"}, "country": {"type": "string"}},
            "required": ["city", "country"],
            "additionalProperties": False,
        },
    }
    parameters = dict(FAST, response_format="json_schema", json_schema=json.dumps(schema))
    text, _, _ = collect(
        llm.invoke(CHEAP, credentials, [UserPromptMessage(content="Name the capital of Japan.")], parameters)
    )
    data = json.loads(text)
    assert data["city"].lower() == "tokyo"
    assert "japan" in data["country"].lower()


def test_pdf_document_input(llm, credentials):
    message = UserPromptMessage(
        content=[
            TextPromptMessageContent(data="What is the secret word in this PDF? Answer with the word only."),
            DocumentPromptMessageContent(
                format="pdf",
                mime_type="application/pdf",
                base64_data=tiny_pdf("The secret word is PAPAYA."),
                filename="note.pdf",
            ),
        ]
    )
    text, _, _ = collect(llm.invoke(CHEAP, credentials, [message], dict(FAST)))
    assert "PAPAYA" in text.upper()


def test_image_input(llm, credentials):
    message = UserPromptMessage(
        content=[
            TextPromptMessageContent(data="What color fills this image? Answer with one word."),
            ImagePromptMessageContent(format="png", mime_type="image/png", base64_data=red_png()),
        ]
    )
    text, _, _ = collect(llm.invoke(CHEAP, credentials, [message], dict(FAST)))
    assert "red" in text.lower()


def test_anthropic_model_through_the_gateway(llm, credentials):
    text, _, _ = collect(
        llm.invoke(
            "claude/sonnet-5",
            credentials,
            [UserPromptMessage(content="Reply with the word PONG and nothing else.")],
            {"max_tokens": 50},
        )
    )
    assert "PONG" in text.upper()


def test_hand_added_model_reads_its_limits(llm, credentials):
    llm.validate_credentials("openai/gpt-5-4-mini", credentials)
    schema = llm.get_customizable_model_schema("openai/gpt-5-4-mini", credentials)
    assert schema.model_properties[ModelPropertyKey.CONTEXT_SIZE] >= 100000
    assert ModelFeature.VISION in (schema.features or [])


def test_hand_added_model_must_exist(llm, credentials):
    with pytest.raises(CredentialsValidateFailedError, match="does not list"):
        llm.validate_credentials("acme/not-a-real-model", credentials)
    with pytest.raises(CredentialsValidateFailedError, match="owner/model"):
        llm.validate_credentials("gpt-5-nano", credentials)
