"""Live tests against the Wiro AI Run API.

They run only when WIRO_API_KEY is set. Catalog calls are free; tests marked
"paid" run cheap models (about $0.10 for the whole file). Skip them with
-m "not paid".
"""

import struct
import zlib

import pytest
from dify_plugin.entities.tool import ToolInvokeMessage
from dify_plugin.errors.tool import ToolProviderCredentialValidationError

from conftest import FakeFile, load_class

MessageType = ToolInvokeMessage.MessageType
STATE: dict = {}


def tool(name: str, class_name: str, credentials):
    return load_class(f"tools/{name}.py", class_name).from_credentials(dict(credentials))


def run(instance, parameters: dict) -> dict:
    out = {"text": "", "json": [], "blobs": [], "links": []}
    for message in instance._invoke(parameters):
        if message.type == MessageType.TEXT:
            out["text"] += message.message.text
        elif message.type == MessageType.JSON:
            out["json"].append(message.message.json_object)
        elif message.type == MessageType.BLOB:
            out["blobs"].append((message.message.blob, message.meta))
        elif message.type == MessageType.LINK:
            out["links"].append(message.message.text)
    return out


def png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def test_provider_accepts_the_key(credentials):
    provider = load_class("provider/wiro_media.py", "WiroMediaProvider")
    provider()._validate_credentials(dict(credentials))


def test_provider_rejects_a_wrong_key():
    provider = load_class("provider/wiro_media.py", "WiroMediaProvider")
    with pytest.raises(ToolProviderCredentialValidationError, match="did not accept"):
        provider()._validate_credentials({"api_key": "0" * 32})


def test_model_list_comes_from_the_catalog(credentials):
    options = tool("generate_image", "GenerateImageTool", credentials)._fetch_parameter_options("model")
    values = [option.value for option in options]
    assert "google/nano-banana-2" in values and "openai/gpt-image-2" in values
    speech = tool("text_to_speech", "TextToSpeechTool", credentials)._fetch_parameter_options("model")
    assert "elevenlabs/eleven-v4" in [option.value for option in speech]


def test_search_models(credentials):
    out = run(
        tool("search_models", "SearchModelsTool", credentials),
        {"query": "nano banana", "category": "text-to-image", "limit": 5},
    )
    models = out["json"][0]["models"]
    assert models and all("/" in item["model"] for item in models)
    assert "google/" in out["text"]


def test_get_model_parameters(credentials):
    out = run(tool("get_model", "GetModelTool", credentials), {"model": "openai/gpt-image-2"})
    rows = {row["id"]: row for row in out["json"][0]["parameters"]}
    assert rows["prompt"]["required"] is True and "default" not in rows["prompt"]
    assert "16:9" in rows["ratio"]["options"]
    assert out["json"][0]["page"] == "https://wiro.ai/models/openai/gpt-image-2"


@pytest.mark.paid
def test_generate_image(credentials):
    out = run(
        tool("generate_image", "GenerateImageTool", credentials),
        {
            "prompt": "A small red paper boat on a calm blue lake, flat illustration",
            "model": "openai/gpt-image-2",
            "aspect_ratio": "16:9",
        },
    )
    assert out["blobs"], out["text"]
    blob, meta = out["blobs"][0]
    assert meta["mime_type"].startswith("image/") and blob[:4] == b"\x89PNG"
    record = out["json"][-1]
    assert record["status"] == "task_postprocess_end" and record["files"][0]["url"].startswith("https://")
    STATE["image_task"] = record["task_token"]


@pytest.mark.paid
def test_edit_image(credentials):
    source = FakeFile(png(256, 256, (220, 30, 30)), "image/png", "red.png")
    out = run(
        tool("generate_image", "GenerateImageTool", credentials),
        {
            "prompt": "Put a small white circle in the middle of this red square.",
            "model": "openai/gpt-image-2",
            "images": [source],
        },
    )
    assert out["blobs"], out["text"]


def test_get_task_collects_files(credentials):
    token = STATE.get("image_task")
    if not token:
        pytest.skip("needs the image from test_generate_image")
    out = run(tool("get_task", "GetTaskTool", credentials), {"task": token, "wait_seconds": 0})
    assert out["blobs"] and out["json"][-1]["model"] == "openai/gpt-image-2"


@pytest.mark.paid
def test_text_to_speech(credentials):
    out = run(
        tool("text_to_speech", "TextToSpeechTool", credentials),
        {"text": "Hello from Wiro AI.", "model": "elevenlabs/eleven-v4", "voice": "alice"},
    )
    assert out["blobs"], out["text"]
    assert out["blobs"][0][1]["mime_type"].startswith("audio/")


@pytest.mark.paid
def test_generate_music(credentials):
    out = run(
        tool("generate_music", "GenerateMusicTool", credentials),
        {"prompt": "Calm lo-fi beat with soft piano", "duration": 10, "model": "elevenlabs/text-to-music-v2"},
    )
    assert out["blobs"], out["text"]
    assert out["blobs"][0][1]["mime_type"].startswith("audio/")


@pytest.mark.paid
def test_run_any_model_returns_llm_text(credentials):
    out = run(
        tool("run_model", "RunModelTool", credentials),
        {
            "model": "openai/gpt-5-nano",
            "parameters": '{"prompt": "Reply with the word PONG and nothing else."}',
            "wait_seconds": 120,
        },
    )
    assert "PONG" in out["text"].upper()
    assert out["json"][-1]["text"]


@pytest.mark.paid
def test_generate_video(credentials):
    out = run(
        tool("generate_video", "GenerateVideoTool", credentials),
        {
            "prompt": "A paper boat drifting slowly on a calm lake at sunrise",
            "model": "bytedance/seedance-v1-pro-fast",
            "aspect_ratio": "16:9",
        },
    )
    if out["json"] and out["json"][-1].get("status") == "running":
        pytest.skip("the video took longer than the wait; Get Task Result covers this case")
    assert out["blobs"], out["text"]
    assert out["blobs"][0][1]["mime_type"].startswith("video/")
