import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from pipecat.serializers.plivo import PlivoFrameSerializer
from pipecat.frames.frames import AudioRawFrame, InterruptionFrame

from app.main import app, validate_plivo_request
from app.config import PLIVO_AUTH_ID, PLIVO_AUTH_TOKEN, PLIVO_PHONE_NUMBER, SERVER_BASE_URL
from app.adapters.pipecat.transport import PlivoTransportAdapter


@pytest.fixture
def client():
    # Set APP_STATE is_ready to True for tests
    from app.main import APP_STATE
    APP_STATE["is_ready"] = True
    return TestClient(app)


def test_plivo_config_loading():
    """Verify that Plivo configuration variables are properly accessible."""
    assert PLIVO_AUTH_ID != ""
    assert PLIVO_AUTH_TOKEN != ""
    assert PLIVO_PHONE_NUMBER != ""
    assert SERVER_BASE_URL != ""
    assert SERVER_BASE_URL.startswith("http")


@pytest.mark.asyncio
async def test_plivo_serializer_play_audio():
    """Verify that PlivoFrameSerializer serializes AudioRawFrame into Plivo playAudio event."""
    serializer = PlivoFrameSerializer(
        stream_id="test-stream-123",
        params=PlivoFrameSerializer.InputParams(plivo_sample_rate=8000, sample_rate=8000, auto_hang_up=False)
    )
    # 8000Hz 16-bit PCM silent audio (160 samples = 20ms)
    pcm_audio = b"\x00\x00" * 160
    frame = AudioRawFrame(audio=pcm_audio, sample_rate=8000, num_channels=1)

    serialized = await serializer.serialize(frame)
    assert serialized is not None
    import json
    data = json.loads(serialized)
    assert data["event"] == "playAudio"
    assert data["streamId"] == "test-stream-123"
    assert data["media"]["contentType"] == "audio/x-mulaw"
    assert data["media"]["sampleRate"] == 8000
    assert "payload" in data["media"]


@pytest.mark.asyncio
async def test_plivo_serializer_clear_audio_on_interruption():
    """Verify that PlivoFrameSerializer converts InterruptionFrame into Plivo clearAudio event."""
    serializer = PlivoFrameSerializer(
        stream_id="test-stream-123",
        params=PlivoFrameSerializer.InputParams(plivo_sample_rate=8000, sample_rate=8000, auto_hang_up=False)
    )
    frame = InterruptionFrame()
    serialized = await serializer.serialize(frame)
    assert serialized is not None
    import json
    data = json.loads(serialized)
    assert data == {"event": "clearAudio", "streamId": "test-stream-123"}


@pytest.mark.asyncio
async def test_plivo_serializer_deserialize_media():
    """Verify that PlivoFrameSerializer deserializes incoming Plivo media packets."""
    import base64
    from pipecat.frames.frames import StartFrame
    serializer = PlivoFrameSerializer(
        stream_id="test-stream-123",
        params=PlivoFrameSerializer.InputParams(plivo_sample_rate=8000, sample_rate=8000, auto_hang_up=False)
    )
    await serializer.setup(StartFrame(audio_in_sample_rate=8000))
    # Dummy mulaw byte payload
    mulaw_payload = base64.b64encode(b"\xff" * 160).decode("utf-8")
    media_event = {
        "event": "media",
        "media": {
            "payload": mulaw_payload
        }
    }
    import json
    deserialized = await serializer.deserialize(json.dumps(media_event))
    assert deserialized is not None
    from pipecat.frames.frames import InputAudioRawFrame
    assert isinstance(deserialized, InputAudioRawFrame)
    assert deserialized.sample_rate == 8000
    assert len(deserialized.audio) > 0


def test_plivo_webhook_returns_valid_xml(client):
    """Verify that /plivo/inbound-call returns valid XML with <Stream> element."""
    response = client.post(
        "/plivo/inbound-call",
        data={
            "From": "+919876543210",
            "To": PLIVO_PHONE_NUMBER,
            "CallUUID": "call-uuid-12345",
            "Direction": "inbound"
        }
    )
    assert response.status_code == 200
    assert "application/xml" in response.headers["content-type"]
    text = response.text
    assert "<Response>" in text
    assert "<Stream" in text
    assert "bidirectional=\"true\"" in text
    assert "contentType=\"audio/x-mulaw;rate=8000\"" in text
    assert "/ws/plivo" in text
    assert "</Stream>" in text
    assert "</Response>" in text


def test_inbound_call_dispatches_to_plivo_when_configured(client):
    """Verify that /inbound-call dispatches to Plivo XML when TRANSPORT_MODE=plivo."""
    with patch("app.main.TRANSPORT_MODE", "plivo"):
        response = client.post(
            "/inbound-call",
            data={
                "From": "+919876543210",
                "To": PLIVO_PHONE_NUMBER,
                "CallUUID": "call-uuid-12345",
                "Direction": "inbound"
            }
        )
        assert response.status_code == 200
        assert "application/xml" in response.headers["content-type"]
        assert "/ws/plivo" in response.text
