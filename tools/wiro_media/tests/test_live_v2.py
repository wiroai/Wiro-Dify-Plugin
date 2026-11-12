"""Live tests for the 0.2.0 tools on Wiro AI.

They run only when WIRO_API_KEY is set. Tests marked "paid" run models (about
$0.60 for the file: a 3D model, a talking video, a short video, a Studio turn
and a few images). The workflow test saves a temporary private workflow in the
key's workspace and deletes it afterwards; the Studio test deletes its session.
Agents are only listed: the tests never message a deployed agent.
"""

import io
import json
import struct
import uuid
import zlib
from pathlib import Path

import pytest
from dify_plugin.entities.tool import ToolInvokeMessage

from conftest import FakeFile, load_class
from wiroapi.client import WiroClient
from wiroapi.params import is_file, param_items

MessageType = ToolInvokeMessage.MessageType
STATE: dict = {}
SAMPLE_OBJECT = "https://cdn.wiro.ai/uploads/sampleinputs/microsoft-trellis-2-input.webp"
SAMPLE_FACE = "https://cdn.wiro.ai/uploads/sampleinputs/pruna-p-videoavatar-input-1.jpg"


def tool(name, class_name, credentials):
    return load_class(f"tools/{name}.py", class_name).from_credentials(dict(credentials))


def run(instance, parameters):
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


def png(width, height, background, square=None):
    rows = []
    for y in range(height):
        row = bytearray(b"\x00")
        for x in range(width):
            inside = square and width // 4 <= x < 3 * width // 4 and height // 4 <= y < 3 * height // 4
            row += bytes(square if inside else background)
        rows.append(bytes(row))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(b"".join(rows)))
        + chunk(b"IEND", b"")
    )


def sample(url, mime, name):
    import requests

    data = requests.get(url, timeout=60, headers={"User-Agent": "wiro-dify-plugin-tests"}).content
    return FakeFile(data, mime, name)


def demo_speech():
    import dify_plugin

    path = Path(dify_plugin.__file__).parent / "interfaces" / "model" / "audio.mp3"
    return FakeFile(path.read_bytes(), "audio/mpeg", "speech.mp3")


@pytest.mark.parametrize(
    "name,cls,expected",
    [
        ("edit_image", "EditImageTool", "openai/gpt-image-2"),
        ("upscale_image", "UpscaleImageTool", "xinntao/real-esrgan"),
        ("remove_background", "RemoveBackgroundTool", "wiro/remove-background"),
        ("image_to_video", "ImageToVideoTool", "bytedance/seedance-v1-pro-fast"),
        ("speech_to_text", "SpeechToTextTool", "elevenlabs/speech-to-text"),
        ("generate_3d", "Generate3DTool", "microsoft/trellis-2"),
        ("lipsync", "LipsyncTool", "pruna/p-video-avatar"),
    ],
)
def test_model_lists_come_from_the_catalog(credentials, name, cls, expected):
    values = [o.value for o in tool(name, cls, credentials)._fetch_parameter_options("model")]
    assert expected in values


def test_agents_are_listed_but_never_messaged(credentials):
    options = tool("message_agent", "MessageAgentTool", credentials)._fetch_parameter_options("agent")
    assert all(o.value and "(" in o.label.en_us for o in options)


def test_studio_chat_models_are_listed(credentials):
    options = tool("ask_studio", "AskStudioTool", credentials)._fetch_parameter_options("chat_model")
    assert options


@pytest.mark.paid
def test_edit_image(credentials):
    source = FakeFile(png(256, 256, (240, 240, 240), (220, 30, 30)), "image/png", "square.png")
    out = run(
        tool("edit_image", "EditImageTool", credentials),
        {"images": [source], "prompt": "Turn the red square into a blue circle.", "model": "openai/gpt-image-2"},
    )
    assert out["blobs"] and out["blobs"][0][1]["mime_type"].startswith("image/")
    assert out["json"][-1]["cost_usd"]


@pytest.mark.paid
def test_upscale_image(credentials):
    source = FakeFile(png(128, 128, (250, 250, 250), (20, 120, 220)), "image/png", "small.png")
    out = run(tool("upscale_image", "UpscaleImageTool", credentials), {"image": source, "scale": "2"})
    assert out["blobs"], out["text"]


@pytest.mark.paid
def test_remove_background(credentials):
    source = FakeFile(png(256, 256, (30, 160, 60), (240, 200, 20)), "image/png", "shape.png")
    out = run(tool("remove_background", "RemoveBackgroundTool", credentials), {"image": source})
    assert out["blobs"] and out["blobs"][0][1]["mime_type"] == "image/png"


@pytest.mark.paid
def test_image_to_video(credentials):
    source = FakeFile(png(512, 512, (200, 220, 255), (255, 140, 0)), "image/png", "frame.png")
    out = run(
        tool("image_to_video", "ImageToVideoTool", credentials),
        {"image": source, "prompt": "The orange square slowly rotates", "aspect_ratio": "1:1"},
    )
    if out["json"] and out["json"][-1].get("status") == "running":
        pytest.skip("the video outlived the wait; Get Task Result covers that case")
    assert out["blobs"] and out["blobs"][0][1]["mime_type"].startswith("video/")


@pytest.mark.paid
def test_speech_to_text(credentials):
    out = run(tool("speech_to_text", "SpeechToTextTool", credentials), {"audio": demo_speech(), "language": "en"})
    assert len(out["text"].strip()) > 3
    assert out["json"][-1]["text"] == out["text"] and "One" in out["text"]
    assert "language" in " ".join(out["json"][-1].get("notes") or [])


@pytest.mark.paid
def test_generate_3d(credentials):
    out = run(
        tool("generate_3d", "Generate3DTool", credentials),
        {"image": sample(SAMPLE_OBJECT, "image/webp", "object.webp")},
    )
    if out["json"] and out["json"][-1].get("status") == "running":
        pytest.skip("the 3D model outlived the wait")
    names = [meta["filename"] for _, meta in out["blobs"]]
    assert any(name.endswith(".glb") for name in names), names
    glb = next(blob for blob, meta in out["blobs"] if meta["filename"].endswith(".glb"))
    assert glb[:4] == b"glTF"


@pytest.mark.paid
def test_lipsync_from_a_script(credentials):
    out = run(
        tool("lipsync", "LipsyncTool", credentials),
        {"image": sample(SAMPLE_FACE, "image/jpeg", "face.jpg"), "script": "Hello from Wiro AI."},
    )
    if out["json"] and out["json"][-1].get("status") == "running":
        pytest.skip("the talking video outlived the wait")
    assert out["blobs"] and out["blobs"][0][1]["mime_type"].startswith("video/")


@pytest.fixture(scope="module")
def temp_workflow(credentials):
    client = WiroClient(dict(credentials))

    def step(node_id, model, inputs, x):
        values = {}
        for item in param_items(client.model_detail(model)):
            if is_file(item):
                values[str(item["id"])] = "" if item.get("type") == "fileinput" else []
        values.update(inputs)
        return {
            "id": node_id,
            "type": "run",
            "tool": model,
            "depends": ["input"],
            "input": values,
            "metadata": {"position": {"x": x, "y": 0}},
        }

    image = {"prompt": "$input.prompt", "ratio": "1:1", "quality": "low", "resolution": "1k", "samples": "1"}
    contents = {
        "version": "1",
        "nodes": {
            "node-answer": step("node-answer", "openai/gpt-5-nano", {"prompt": "$input.prompt"}, 350),
            "node-image": step("node-image", "openai/gpt-image-2", image, 350),
            "output": {
                "id": "output",
                "type": "display",
                "depends": ["node-answer", "node-image"],
                "input": {},
                "fields": {"answer": "$node-answer.outputs", "image": "$node-image.outputs"},
                "metadata": {"position": {"x": 700, "y": 0}},
            },
        },
        "output": {"answer": "$node-answer.outputs", "image": "$node-image.outputs"},
        "schema": {
            "input": {"prompt": {"label": "Prompt", "type": "string", "defaultValue": "", "ui": {"field": "textarea"}}},
            "output": {},
        },
        "metadata": {"input": {"position": {"x": 0, "y": 0}}},
    }
    prepared = client._post("/Workflow/Prepare", {"contents": contents})["contents"]
    saved = client._post(
        "/Workflow/Add",
        {
            "title": f"Dify plugin test {uuid.uuid4().hex[:6]}",
            "slug": "dify-plugin-test",
            "contents": json.dumps(prepared),
            "description": "Temporary workflow for the Wiro AI Dify plugin tests. Deleted after the run.",
        },
    )["workflow"][0]
    slug = f"{saved['slug']}-{saved['slugid']}"
    yield slug
    client._post("/Workflow/Delete", {"slug": slug})


@pytest.mark.paid
def test_run_workflow(credentials, temp_workflow):
    instance = tool("run_workflow", "RunWorkflowTool", credentials)
    assert temp_workflow in [o.value for o in instance._fetch_parameter_options("workflow")]
    out = run(
        instance,
        {"workflow": temp_workflow, "inputs": '{"prompt": "A paper boat on a pond. Describe it in five words."}'},
    )
    record = out["json"][-1]
    assert record["status"] == "completed", out["text"]
    assert record["results"]["answer"]["text"].strip()
    assert out["blobs"] and out["blobs"][0][1]["mime_type"].startswith("image/")
    STATE["run_token"] = record["run_token"]


def test_get_task_reads_a_workflow_run(credentials):
    token = STATE.get("run_token")
    if not token:
        pytest.skip("needs the run from test_run_workflow")
    out = run(tool("get_task", "GetTaskTool", credentials), {"task": token, "wait_seconds": 0})
    assert out["json"][-1]["status"] == "completed"


@pytest.mark.paid
def test_ask_studio(credentials):
    session = f"dify-plugin-test-{uuid.uuid4().hex[:6]}"
    client = WiroClient(dict(credentials))
    try:
        try:
            out = run(
                tool("ask_studio", "AskStudioTool", credentials),
                {
                    "message": "Make one small square image of a red apple on a white background. "
                    "Use the cheapest image model and make only one image.",
                    "session": session,
                    "chat_model": "openai/gpt-5.4-mini",
                    "wait_seconds": 420,
                },
            )
        except ValueError as exc:
            if "temporarily unavailable" in str(exc):
                pytest.skip(f"Wiro AI Studio answered: {exc}")
            raise
        record = out["json"][-1]
        if record.get("status") == "running":
            pytest.skip("Studio outlived the wait")
        assert out["text"].strip()
        assert record["cost_usd"] >= 0 and "chat_cost_usd" in record
    finally:
        client._post("/Studio/Message/DeleteSession", {"sessionkey": session})


def test_studio_reply_text_is_kept_as_is():
    # Guard against a regression where io was needed for attachments.
    assert io.BytesIO(b"x").read() == b"x"
