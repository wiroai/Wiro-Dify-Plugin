"""Offline tests for the text to speech and speech to text models. No network."""

import hashlib
import hmac

import pytest
import yaml
from dify_plugin.entities.model import AIModelEntity, ModelPropertyKey

from conftest import PLUGIN_ROOT
from models._wiro_run import (
    RunClient,
    WiroRunError,
    audio_type,
    catalog_choice,
    fill_required,
    plain_transcript,
    put_file,
    stt_schema,
    tts_schema,
)
from models.speech2text.speech2text import WiroSpeech2TextModel, sniff_audio
from models.tts.tts import WiroText2SpeechModel

ELEVEN = {
    "categories": ["text-to-speech"],
    "dynamicprice": [{"inputs": {}, "price": 8e-05, "priceMethod": "cp-promptlength"}],
    "parameters": [
        {
            "items": [
                {"id": "prompt", "type": "textarea", "required": True, "defaultvalue": "sample"},
                {
                    "id": "voice",
                    "type": "select",
                    "required": True,
                    "defaultvalue": "alice",
                    "options": [{"text": "Adam", "value": "adam"}, {"text": "Alice", "value": "alice"}],
                },
                {"id": "outputFormat", "type": "select", "required": True, "defaultvalue": "mp3_44100_128"},
                {
                    "id": "language",
                    "type": "select",
                    "required": True,
                    "defaultvalue": "Auto",
                    "options": [{"value": "auto"}, {"value": "english"}],
                },
            ]
        }
    ],
}

SCRIBE = {
    "categories": ["speech-to-text"],
    "parameters": [
        {
            "items": [
                {"id": "inputAudio", "type": "fileinput", "required": True},
                {"id": "inputAudioUrl", "type": "text", "required": False},
            ]
        }
    ],
}


def load(kind: str) -> list[AIModelEntity]:
    folder = PLUGIN_ROOT / "models" / kind
    return [
        AIModelEntity.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        for path in sorted(folder.glob("*.yaml"))
        if not path.name.startswith("_")
    ]


def test_tts_schema_from_catalog():
    schema = AIModelEntity.model_validate(tts_schema("elevenlabs/eleven-v4", ELEVEN))
    props = schema.model_properties
    assert props[ModelPropertyKey.DEFAULT_VOICE] == "alice"
    assert [v["mode"] for v in props[ModelPropertyKey.VOICES]] == ["adam", "alice"]
    assert "en-US" in props[ModelPropertyKey.VOICES][0]["language"]
    assert props[ModelPropertyKey.AUDIO_TYPE] == "mp3"
    assert str(schema.pricing.input) == "0.08"


def test_tts_schema_needs_voices():
    no_voice = {"parameters": [{"items": [{"id": "prompt", "type": "textarea"}]}]}
    assert tts_schema("acme/tts", no_voice) is None


def test_stt_schema_and_url_companion():
    assert stt_schema("elevenlabs/speech-to-text", SCRIBE)["model_type"] == "speech2text"
    items = SCRIBE["parameters"][0]["items"]
    parameters = {}
    put_file(items, items[0], "https://cdn1.wiro.ai/a.mp3", parameters)
    assert parameters == {"inputAudioUrl": "https://cdn1.wiro.ai/a.mp3"}
    assert fill_required(items, parameters) == parameters


def test_select_defaults_follow_the_options():
    items = ELEVEN["parameters"][0]["items"]
    assert catalog_choice(items[3]) == "auto"
    filled = fill_required(items, {"prompt": "hi", "voice": "adam"})
    assert filled["language"] == "auto" and filled["outputFormat"] == "mp3_44100_128"
    with pytest.raises(WiroRunError, match="prompt"):
        fill_required(items, {})


def test_audio_type_defaults_to_mp3():
    assert audio_type([]) == "mp3"
    assert audio_type([{"id": "outputFormat", "defaultvalue": "wav_24000"}]) == "wav"


def test_sniff_audio():
    assert sniff_audio(b"ID3\x04rest") == ("mp3", "audio/mpeg")
    assert sniff_audio(b"RIFF....WAVE")[0] == "wav"
    assert sniff_audio(b"\x1a\x45\xdf\xa3data")[0] == "webm"
    assert sniff_audio(b"\x00\x00\x00\x20ftypM4A ")[0] == "m4a"


def test_signature_headers():
    headers = RunClient({"api_key": "key", "api_secret": "secret"})._headers()
    expected = hmac.new(b"key", ("secret" + headers["x-nonce"]).encode(), hashlib.sha256).hexdigest()
    assert headers["x-signature"] == expected
    assert RunClient({"api_key": "key:secret"}).api_secret == "secret"


def test_packaged_speech_models_load():
    for kind, minimum in (("tts", 3), ("speech2text", 3)):
        schemas = load(kind)
        assert len(schemas) >= minimum
        position = yaml.safe_load((PLUGIN_ROOT / "models" / kind / "_position.yaml").read_text())
        assert sorted(position) == sorted(s.model for s in schemas)
    for schema in load("tts"):
        props = schema.model_properties
        modes = [v["mode"] for v in props[ModelPropertyKey.VOICES]]
        assert props[ModelPropertyKey.DEFAULT_VOICE] in modes


class FakeClient:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def download(self, url: str, max_bytes: int) -> bytes:
        return self.payload


def test_audio_and_transcript_are_read_from_outputs():
    task = {"outputs": [{"url": "https://cdn1.wiro.ai/x/0.mp3", "contenttype": "audio/mpeg"}]}
    assert WiroText2SpeechModel._audio(FakeClient(b"ID3"), task, "m") == b"ID3"
    task = {"outputs": [{"url": "https://cdn1.wiro.ai/x/out.txt", "contenttype": "text/plain", "name": "out.txt"}]}
    assert WiroSpeech2TextModel._transcript(FakeClient(b" Hello there \n"), task, "m") == "Hello there"
    raw = {"outputs": [{"contenttype": "raw"}], "debugoutput": "Spoken words"}
    assert WiroSpeech2TextModel._transcript(FakeClient(b""), raw, "m") == "Spoken words"
    with pytest.raises(WiroRunError):
        WiroText2SpeechModel._audio(FakeClient(b""), {"outputs": []}, "m")


def test_transcripts_are_plain_text():
    whisper = "00:00.0 - 00:04.5 /  Hello from Wiro AI.\n00:04.6 - 00:06.0 /  Bye.\n"
    assert plain_transcript(whisper) == "Hello from Wiro AI. Bye."
    assert plain_transcript("Language: English\nText: One, two.\n") == "One, two."
    srt = "1\n00:00:00,300 --> 00:00:01,100\nHello\n\n2\n00:00:01,900 --> 00:00:02,600\n10\n"
    assert plain_transcript(srt) == "Hello 10"
    assert plain_transcript("Just words, 10:30 - 11:00 / later.\n") == "Just words, 10:30 - 11:00 / later."
    task = {"outputs": [{"url": "https://cdn1.wiro.ai/x/out.txt", "contenttype": "text/plain", "name": "out.txt"}]}
    assert WiroSpeech2TextModel._transcript(FakeClient(whisper.encode()), task, "m") == "Hello from Wiro AI. Bye."
