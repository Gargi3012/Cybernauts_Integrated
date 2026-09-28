from fastapi import WebSocket

PLIVO_SAMPLE_RATE = 8000

def build_plivo_transport(
    websocket: WebSocket,
    stream_id: str,
    call_id: str | None = None,
    auth_id: str | None = None,
    auth_token: str | None = None,
    vad_analyzer = None,
):
    """Exposed factory for the main app to build the Plivo WebSocket transport via Pillar 2."""
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
            auto_hang_up=False,
        ),
    )
    return FastAPIWebsocketTransport(
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
