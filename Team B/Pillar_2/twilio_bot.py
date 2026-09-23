from fastapi import WebSocket

TWILIO_SAMPLE_RATE = 8000

def build_twilio_transport(websocket: WebSocket, stream_sid: str, vad_analyzer):
    """Exposed factory for the main app to build the Twilio WebSocket transport via Pillar 2."""
    from pipecat.transports.websocket.fastapi import FastAPIWebsocketTransport, FastAPIWebsocketParams
    from pipecat.serializers.twilio import TwilioFrameSerializer

    serializer = TwilioFrameSerializer(
        stream_sid=stream_sid,
        params=TwilioFrameSerializer.InputParams(
            twilio_sample_rate=TWILIO_SAMPLE_RATE,
            sample_rate=TWILIO_SAMPLE_RATE,
            auto_hang_up=False,
        ),
    )
    return FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=TWILIO_SAMPLE_RATE,
            audio_out_sample_rate=TWILIO_SAMPLE_RATE,
            add_wav_header=False,
            vad_enabled=True,
            vad_analyzer=vad_analyzer,
            serializer=serializer,
        ),
    )