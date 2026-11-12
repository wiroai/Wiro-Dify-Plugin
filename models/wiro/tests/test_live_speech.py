"""Live tests for text to speech and speech to text on Wiro AI (a few cents in total)."""

import io

import pytest
from dify_plugin.entities.model import ModelPropertyKey
from dify_plugin.errors.model import CredentialsValidateFailedError
from test_speech import load

from models.speech2text.speech2text import WiroSpeech2TextModel
from models.tts.tts import WiroText2SpeechModel

STATE: dict = {}


@pytest.fixture(scope="module")
def tts():
    return WiroText2SpeechModel(model_schemas=load("tts"))


@pytest.fixture(scope="module")
def stt():
    return WiroSpeech2TextModel(model_schemas=load("speech2text"))


def test_text_to_speech(tts, credentials):
    audio = b"".join(
        tts.invoke(
            model="elevenlabs/eleven-v4",
            tenant_id="test",
            credentials=dict(credentials),
            content_text="Hello from Wiro AI.",
            voice="alice",
        )
    )
    assert audio[:3] == b"ID3" or audio[:2] == b"\xff\xfb"
    STATE["speech"] = audio


def test_speech_to_text_round_trip(stt, credentials):
    audio = STATE.get("speech")
    if not audio:
        pytest.skip("needs the audio from test_text_to_speech")
    text = stt.invoke(model="elevenlabs/speech-to-text", credentials=dict(credentials), file=io.BytesIO(audio))
    assert "hello" in text.lower()


def test_whisper_fills_its_required_settings(stt, credentials):
    audio = STATE.get("speech")
    if not audio:
        pytest.skip("needs the audio from test_text_to_speech")
    text = stt.invoke(model="openai/whisper-large-v3", credentials=dict(credentials), file=io.BytesIO(audio))
    assert "hello" in text.lower()
    assert " / " not in text and not text[:1].isdigit(), "segment times should be gone"


def test_voice_model_added_by_id(tts, credentials):
    tts.validate_credentials("elevenlabs/eleven-v4-turbo", dict(credentials))
    schema = tts.get_customizable_model_schema("elevenlabs/eleven-v4-turbo", dict(credentials))
    assert len(schema.model_properties[ModelPropertyKey.VOICES]) > 5
    with pytest.raises(CredentialsValidateFailedError):
        tts.validate_credentials("openai/gpt-image-2", dict(credentials))
