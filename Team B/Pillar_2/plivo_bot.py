"""
Pillar 2 — Plivo Telephony WebSocket Transport Factory
Builds a FastAPI WebSocket transport utilizing Pipecat's native PlivoFrameSerializer.
Handles 8kHz mu-law audio conversion, bidirectional streaming, and graceful auto-hangup.
"""

from typing import Optional
from fastapi import WebSocket
from loguru import logger

PLIVO_SAMPLE_RATE = 8000


def build_plivo_transport(
    websocket: WebSocket,
    stream_id: str,
    vad_analyzer,
    call_id: Optional[str] = None,
    auth_id: Optional[str] = None,
    auth_token: Optional[str] = None,
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
    from pipecat.transports.websocket.fastapi import FastAPIWebsocketTransport, FastAPIWebsocketParams
    from pipecat.serializers.plivo import PlivoFrameSerializer

    serializer = PlivoFrameSerializer(
        stream_id=stream_id,
        call_id=call_id,
        auth_id=auth_id,
        auth_token=auth_token,
        params=PlivoFrameSerializer.InputParams(
            plivo_sample_rate=PLIVO_SAMPLE_RATE,
            sample_rate=PLIVO_SAMPLE_RATE,
            auto_hang_up=bool(auth_id and auth_token and call_id),
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
            vad_analyzer=vad_analyzer,
            serializer=serializer,
        ),
    )

    logger.info(f"Plivo transport constructed | stream_id={stream_id} | call_id={call_id}")
    return transport
