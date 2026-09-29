"""
Pillar 2 — Plivo Telephony WebSocket Transport Factory
Builds a FastAPI WebSocket transport utilizing Pipecat's native PlivoFrameSerializer.
Handles 8kHz mu-law audio conversion, bidirectional streaming, and graceful auto-hangup.
"""

from typing import Any, Optional
from fastapi import WebSocket
from loguru import logger

PLIVO_SAMPLE_RATE = 8000


def build_plivo_transport(
    websocket: WebSocket,
    stream_id: str,
    vad_analyzer: Any = None,
    call_id: Optional[str] = None,
    auth_id: Optional[str] = None,
    auth_token: Optional[str] = None,
    **kwargs: Any,
):
    """
    Exposed factory for the main app to build the Plivo WebSocket transport via Pillar 2.

    Args:
        websocket: Active FastAPI WebSocket connection from Plivo.
        stream_id: Unique stream identifier provided by Plivo.
        vad_analyzer: Configured Silero VAD analyzer instance.
        call_id: Optional Plivo Call UUID for automatic call hangup.
        auth_id: Optional Plivo Auth ID for REST API operations.
        auth_token: Optional Plivo Auth Token for REST API operations.
    """
    # Accommodate callers that pass call_id as 3rd positional argument
    if vad_analyzer is not None and isinstance(vad_analyzer, str) and not hasattr(vad_analyzer, "analyze"):
        actual_call_id = vad_analyzer
        actual_auth_id = call_id
        actual_auth_token = auth_id
        actual_vad = kwargs.get("vad_analyzer", None)
    else:
        actual_call_id = call_id
        actual_auth_id = auth_id
        actual_auth_token = auth_token
        actual_vad = vad_analyzer if vad_analyzer is not None else kwargs.get("vad_analyzer", None)

    from pipecat.transports.websocket.fastapi import FastAPIWebsocketTransport, FastAPIWebsocketParams
    from pipecat.serializers.plivo import PlivoFrameSerializer

    serializer = PlivoFrameSerializer(
        stream_id=stream_id,
        call_id=actual_call_id,
        auth_id=actual_auth_id,
        auth_token=actual_auth_token,
        params=PlivoFrameSerializer.InputParams(
            plivo_sample_rate=PLIVO_SAMPLE_RATE,
            sample_rate=PLIVO_SAMPLE_RATE,
            auto_hang_up=bool(actual_auth_id and actual_auth_token and actual_call_id),
        ),
    )

    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=PLIVO_SAMPLE_RATE,
            audio_out_sample_rate=PLIVO_SAMPLE_RATE,
            add_wav_header=False,
            vad_enabled=True,
            vad_analyzer=actual_vad,
            serializer=serializer,
        ),
    )

    logger.info(f"Plivo transport constructed | stream_id={stream_id} | call_id={actual_call_id}")
    return transport
