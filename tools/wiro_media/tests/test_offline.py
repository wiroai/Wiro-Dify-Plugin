"""Offline tests for parameter mapping, summaries and result handling. No network."""

import hashlib
import hmac
import subprocess
from pathlib import Path

import pytest

from conftest import load_class
from wiroapi.client import WiroClient, WiroError, split_model_id
from wiroapi.describe import price_text
from wiroapi.params import default_value, fill_required, image_param, put_files, ratio_param
from wiroapi.tooling import deliver, parse_json_object, still_running

GPT_IMAGE_ITEMS = [
    {
        "id": "inputImage",
        "type": "combinefileinput",
        "required": False,
        "defaultvalue": "https://cdn.wiro.ai/sample.jpg",
        "maxinputlength": 16,
    },
    {"id": "prompt", "type": "textarea", "required": True, "defaultvalue": "a sample prompt"},
    {"id": "inputImageMask", "type": "combinefileinput", "required": False, "defaultvalue": ""},
    {
        "id": "resolution",
        "type": "select",
        "required": True,
        "defaultvalue": "1k",
        "options": [{"value": "1k"}, {"value": "2k"}],
    },
    {
        "id": "ratio",
        "type": "select",
        "required": True,
        "defaultvalue": "1:1",
        "options": [{"value": "1:1"}, {"value": "16:9"}],
    },
    {"id": "samples", "type": "number", "required": True, "defaultvalue": "1"},
    {"id": "background", "type": "select", "required": False, "defaultvalue": "auto"},
]


def test_required_defaults_are_filled_but_samples_are_not():
    filled = fill_required(GPT_IMAGE_ITEMS, {"prompt": "a red boat"})
    assert filled == {"prompt": "a red boat", "resolution": "1k", "ratio": "1:1", "samples": "1"}


def test_missing_prompt_is_named():
    with pytest.raises(ValueError, match="prompt"):
        fill_required(GPT_IMAGE_ITEMS, {})


def test_image_and_ratio_fields_are_found():
    assert image_param(GPT_IMAGE_ITEMS)["id"] == "inputImage"
    assert ratio_param(GPT_IMAGE_ITEMS)["id"] == "ratio"
    items = [{"id": "inputImageLast", "type": "combinefileinput"}, {"id": "startImage", "type": "fileinput"}]
    assert image_param(items)["id"] == "startImage"


def test_files_go_where_each_field_type_takes_them():
    parameters = {}
    put_files({"id": "inputImage", "type": "combinefileinput"}, ["u1", "u2"], parameters)
    put_files({"id": "inputAudio", "type": "fileinput"}, ["u3"], parameters)
    put_files({"id": "inputDocumentMultiple", "type": "multifileinput"}, ["u4", "u5"], parameters)
    assert parameters == {"inputImage": ["u1", "u2"], "inputAudio": "u3", "inputDocumentUrlMultiple": "u4,u5"}
    with pytest.raises(ValueError):
        put_files({"id": "inputAudio", "type": "fileinput"}, ["a", "b"], {})


def test_file_limit_comes_from_maxinputlength():
    urls = [f"u{n}" for n in range(17)]
    with pytest.raises(ValueError, match="at most 16 files"):
        put_files(GPT_IMAGE_ITEMS[0], urls, {})
    parameters = {}
    put_files({"id": "inputImage", "type": "combinefileinput", "maxinput" + "lenght": 16}, urls, parameters)
    assert parameters == {"inputImage": urls}  # the old name is not read, so it sets no cap


def test_no_misspelled_maxinputlength():
    # Wiro's catalog names the file limit maxinputlength; no tracked file may bring back the old misspelling.
    root = Path(__file__).resolve().parents[3]
    needle = ("maxinput" + "lenght").encode()
    names = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, text=True, check=True).stdout
    paths = [root / name for name in names.split("\0") if name]
    found = [str(path.relative_to(root)) for path in paths if path.is_file() and needle in path.read_bytes().lower()]
    assert not found, f"the misspelled file limit name is back in {found}"


def test_checkbox_default():
    assert default_value({"type": "checkbox", "value": ""}) == "false"
    assert default_value({"type": "checkbox", "value": "--flag"}) == "true"
    assert default_value({"type": "select", "defaultvalue": "", "value": "x"}) == "x"


def test_price_text():
    assert price_text('[{"inputs": {}, "price": 0.035, "priceMethod": "per-output-file"}]') == "$0.035 per output file"
    assert (
        price_text([{"price": 0.05, "priceMethod": "per-run"}, {"price": 0.11, "priceMethod": "per-run"}])
        == "from $0.05 per run"
    )
    assert price_text([{"price": 8e-05, "priceMethod": "per-input-character"}]).startswith("usage-based")
    assert price_text([{"price": 0.02, "priceMethod": "per-input-video-second"}]).startswith("usage-based")
    assert price_text(None) == "price on the model page"


def test_json_object_input():
    assert parse_json_object('{"a": 1}', "Extra") == {"a": 1}
    assert parse_json_object("", "Extra") == {}
    with pytest.raises(ValueError):
        parse_json_object("[1, 2]", "Extra")


def test_model_ids():
    assert split_model_id("google/nano-banana-2") == ("google", "nano-banana-2")
    with pytest.raises(WiroError):
        split_model_id("nano-banana-2")


def test_signature_headers():
    client = WiroClient({"api_key": "key", "api_secret": "secret"})
    headers = client._headers()
    expected = hmac.new(b"key", ("secret" + headers["x-nonce"]).encode(), hashlib.sha256).hexdigest()
    assert headers["x-signature"] == expected
    assert "x-signature" not in WiroClient({"api_key": "key"})._headers()


def test_only_wiro_hosts_are_downloaded():
    client = WiroClient({"api_key": "key"})
    assert client.is_output_url("https://cdn1.wiro.ai/a/b.png")
    assert not client.is_output_url("http://cdn1.wiro.ai/a/b.png")
    assert not client.is_output_url("https://example.com/b.png")
    assert not client.is_output_url("https://wiro.ai.example.com/b.png")


class Recorder:
    """Collects what a tool yields, without a Dify session."""

    def create_text_message(self, text):
        return ("text", text)

    def create_json_message(self, data):
        return ("json", data)

    def create_link_message(self, url):
        return ("link", url)

    def create_blob_message(self, blob, meta):
        return ("blob", meta)


def test_failed_run_raises_with_the_reason():
    task = {"id": "7", "status": "task_postprocess_end", "pexit": "1", "debugerror": "bad input"}
    with pytest.raises(ValueError, match="bad input"):
        list(deliver(Recorder(), WiroClient({"api_key": "k"}), task, "a/b"))


def test_llm_text_is_returned_as_text():
    task = {
        "id": "8",
        "status": "task_postprocess_end",
        "pexit": "0",
        "totalcost": "0.0001",
        "outputs": [{"contenttype": "raw", "content": {"raw": "Hi"}}],
        "debugoutput": "Hi there",
    }
    messages = list(deliver(Recorder(), WiroClient({"api_key": "k"}), task, "openai/gpt-5-nano"))
    assert ("text", "Hi there") in messages
    assert messages[-1][0] == "json" and messages[-1][1]["text"] == "Hi there"


def test_still_running_gives_the_token():
    messages = list(still_running(Recorder(), {"id": "9", "socketaccesstoken": "tok"}, "a/b"))
    assert messages[0][1]["status"] == "running"
    assert "tok" in messages[1][1]


def test_every_tool_file_has_one_tool_class():
    names = {
        "generate_image": "GenerateImageTool",
        "generate_video": "GenerateVideoTool",
        "text_to_speech": "TextToSpeechTool",
        "generate_music": "GenerateMusicTool",
        "run_model": "RunModelTool",
        "get_task": "GetTaskTool",
        "search_models": "SearchModelsTool",
        "get_model": "GetModelTool",
    }
    for file_name, class_name in names.items():
        assert load_class(f"tools/{file_name}.py", class_name)
