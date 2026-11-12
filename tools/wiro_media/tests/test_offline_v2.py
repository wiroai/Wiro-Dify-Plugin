"""Offline tests for the 0.2.0 tools: field mapping, workflow results, Studio replies, tool definitions."""

from pathlib import Path

import pytest
import yaml

from conftest import PLUGIN_ROOT, FakeFile, load_class
from wiroapi.generate import Setting, build_parameters
from wiroapi.params import match_option, media_param, put_files
from wiroapi.tooling import (
    deliver,
    deliver_reply,
    deliver_workflow,
    plain_transcript,
    reply_files,
    send_files,
    workflow_results,
)

TOOL_CLASSES = {
    "generate_image": "GenerateImageTool",
    "edit_image": "EditImageTool",
    "upscale_image": "UpscaleImageTool",
    "remove_background": "RemoveBackgroundTool",
    "generate_video": "GenerateVideoTool",
    "image_to_video": "ImageToVideoTool",
    "lipsync": "LipsyncTool",
    "text_to_speech": "TextToSpeechTool",
    "speech_to_text": "SpeechToTextTool",
    "generate_music": "GenerateMusicTool",
    "generate_3d": "Generate3DTool",
    "run_model": "RunModelTool",
    "run_workflow": "RunWorkflowTool",
    "ask_studio": "AskStudioTool",
    "message_agent": "MessageAgentTool",
    "get_task": "GetTaskTool",
    "search_models": "SearchModelsTool",
    "get_model": "GetModelTool",
}

AVATAR = {
    "parameters": [
        {
            "items": [
                {"id": "inputImage", "type": "combinefileinput", "required": True},
                {"id": "voiceScript", "type": "textarea", "required": False},
                {"id": "inputAudio", "type": "combinefileinput", "required": False},
                {
                    "id": "resolution",
                    "type": "select",
                    "required": True,
                    "defaultvalue": "720p",
                    "options": [{"value": "720p"}, {"value": "1080p"}],
                },
            ]
        }
    ]
}
ESRGAN = {
    "parameters": [
        {
            "items": [
                {"id": "inputImage", "type": "combinefileinput", "required": True},
                {"id": "outscale", "type": "float", "required": False, "defaultvalue": "4"},
                {
                    "id": "modelName",
                    "type": "select",
                    "required": True,
                    "defaultvalue": "RealESRGAN_x4plus",
                    "options": [{"value": "RealESRGAN_x4plus"}],
                },
            ]
        }
    ]
}


class FakeClient:
    def __init__(self, detail=None, payloads=None):
        self.detail = detail or {}
        self.payloads = payloads or {}
        self.uploaded = []

    def model_detail(self, model_id):
        return self.detail

    def upload(self, name, data, mime):
        self.uploaded.append(name)
        return f"https://cdn1.wiro.ai/up/{len(self.uploaded)}"

    def is_output_url(self, url):
        return url.startswith("https://cdn1.wiro.ai/")

    def download(self, url, max_bytes):
        return self.payloads.get(url, b"data")


class Recorder:
    def create_text_message(self, text):
        return ("text", text)

    def create_json_message(self, data):
        return ("json", data)

    def create_link_message(self, url):
        return ("link", url)

    def create_blob_message(self, blob, meta):
        return ("blob", meta)


def test_every_tool_is_listed_and_loads():
    provider = yaml.safe_load((PLUGIN_ROOT / "provider" / "wiro_media.yaml").read_text())
    listed = [Path(p).stem for p in provider["tools"]]
    assert sorted(listed) == sorted(TOOL_CLASSES)
    for name, cls in TOOL_CLASSES.items():
        assert load_class(f"tools/{name}.py", cls)
        spec = yaml.safe_load((PLUGIN_ROOT / "tools" / f"{name}.yaml").read_text())
        assert spec["identity"]["name"] == name
        assert spec["extra"]["python"]["source"] == f"tools/{name}.py"
        for param in spec["parameters"]:
            assert param["label"]["en_US"] and param["human_description"]["en_US"]
            if param["form"] == "llm":
                assert param.get("llm_description"), f"{name}.{param['name']} needs llm_description"


def test_lipsync_maps_face_script_and_defaults():
    client = FakeClient(AVATAR)
    face = FakeFile(b"img", "image/jpeg", "face.jpg")
    parameters, notes = build_parameters(
        client,
        "pruna/p-video-avatar",
        files=[face],
        settings=[
            Setting(("voiceScript", "script"), "Hello there", "script"),
            Setting(("prompt",), "studio", "prompt"),
        ],
    )
    assert parameters["inputImage"] == ["https://cdn1.wiro.ai/up/1"]
    assert parameters["voiceScript"] == "Hello there"
    assert parameters["resolution"] == "720p"
    assert any("prompt" in note for note in notes)
    assert client.uploaded[0].startswith("dify-") and client.uploaded[0].endswith("face.jpg")


def test_upscale_scale_is_written_as_a_number():
    parameters, _ = build_parameters(
        FakeClient(ESRGAN),
        "xinntao/real-esrgan",
        files=[FakeFile(b"img", "image/png", "a.png")],
        settings=[Setting(("outscale", "scale"), 2.0, "scale", numeric=True)],
    )
    assert parameters["outscale"] == "2"
    assert parameters["modelName"] == "RealESRGAN_x4plus"


def test_missing_media_field_is_explained():
    with pytest.raises(ValueError, match="takes no input audio"):
        build_parameters(FakeClient(ESRGAN), "xinntao/real-esrgan", audio=[FakeFile(b"a", "audio/mpeg", "a.mp3")])


def test_media_fields_and_options():
    items = [
        {"id": "inputAudio", "type": "fileinput"},
        {"id": "inputAudioUrl", "type": "text"},
        {"id": "language", "type": "select", "options": [{"value": "en", "text": "English"}]},
    ]
    assert media_param(items, "audio")["id"] == "inputAudio"
    parameters = {}
    put_files(items[0], ["https://cdn1.wiro.ai/a.mp3"], parameters, items)
    assert parameters == {"inputAudioUrl": "https://cdn1.wiro.ai/a.mp3"}
    assert match_option(items[2], "english") == "en"
    assert match_option(items[2], "EN") == "en"
    assert match_option(items[2], "french") is None
    assert match_option({"id": "free"}, "anything") == "anything"


RUN = {
    "workflowrun": {
        "workflowtoken": "tok",
        "status": "completed",
        "totalcost": "0.006",
        "chargedcost": "0.006",
        "elapsedseconds": 20,
        "contents": {
            "nodes": {"output": {"fields": {"image": "$node-image.outputs", "answer": "$node-llm.outputs"}}},
            "output": {"image": "$node-image.outputs", "answer": "$node-llm.outputs"},
        },
    },
    "workflowrunnodes": [
        {
            "nodeId": "node-image",
            "status": "completed",
            "outputs": [{"url": "https://cdn1.wiro.ai/run/img.png", "name": "img.png", "contenttype": "image/png"}],
        },
        {
            "nodeId": "node-llm",
            "status": "completed",
            "outputs": [{"contenttype": "raw", "content": {"answer": ["A red ", "boat."]}}],
        },
    ],
}


def test_workflow_results_and_delivery():
    results = {r["name"]: r for r in workflow_results(RUN)}
    assert results["answer"]["text"] == "A red boat."
    assert results["image"]["files"][0]["name"] == "img.png"
    messages = list(deliver_workflow(Recorder(), FakeClient(), RUN, "test-flow-abc12"))
    kinds = [m[0] for m in messages]
    assert kinds.count("blob") == 1 and kinds[-1] == "json"
    record = messages[-1][1]
    assert record["cost_usd"] == "0.006" and record["results"]["answer"]["text"] == "A red boat."


def test_failed_workflow_names_the_step():
    failed = {
        "workflowrun": {"status": "failed", "contents": {}},
        "workflowrunnodes": [{"nodeId": "node-x", "tool": "a/b", "status": "failed", "error": "bad prompt"}],
    }
    with pytest.raises(ValueError, match="bad prompt"):
        list(deliver_workflow(Recorder(), FakeClient(), failed, "flow"))


def test_studio_reply_files_and_errors():
    text = "Here it is.\nhttps://cdn1.wiro.ai/abc/apple.png\nhttps://example.com/not-ours.png"
    assert [f["name"] for f in reply_files(text)] == ["apple.png"]
    messages = list(deliver_reply(Recorder(), FakeClient(), {"status": "agent_end", "response": text}, "Studio", {}))
    assert ("blob", {"mime_type": "image/png", "filename": "apple.png"}) in messages
    with pytest.raises(ValueError, match="could not answer"):
        list(deliver_reply(Recorder(), FakeClient(), {"status": "agent_error", "response": "down"}, "Studio", {}))


def test_text_outputs_become_text():
    outputs = [{"url": "https://cdn1.wiro.ai/t/out.txt", "name": "out.txt", "contenttype": "text/plain"}]
    client = FakeClient(payloads={"https://cdn1.wiro.ai/t/out.txt": b"Hello world\n"})
    gen = send_files(Recorder(), client, outputs, "stt")
    messages = []
    try:
        while True:
            messages.append(next(gen))
    except StopIteration as stop:
        rows, texts = stop.value
    assert texts == ["Hello world"] and rows[0]["mime_type"] == "text/plain"
    assert messages[0][0] == "blob"


def test_transcript_text_is_cleaned_and_the_file_kept():
    url = "https://cdn1.wiro.ai/t/speech2text_results.txt"
    outputs = [{"url": url, "name": "speech2text_results.txt", "contenttype": "text/plain"}]
    task = {"id": "7", "pexit": "0", "status": "task_postprocess_end", "outputs": outputs, "totalcost": "0.0001"}
    client = FakeClient(payloads={url: b"00:00.3 - 00:01.1 /  One.\n00:01.9 - 00:02.6 /  Two.\n"})
    messages = list(deliver(Recorder(), client, task, "openai/whisper-large-v3", clean_text=plain_transcript))
    assert ("text", "One. Two.") in messages
    assert messages[-1][1]["text"] == "One. Two."
    assert [kind for kind, _ in messages].count("blob") == 1
