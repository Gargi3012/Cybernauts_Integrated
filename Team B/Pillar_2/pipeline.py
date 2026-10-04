from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.services.deepgram.stt import DeepgramSTTService

def create_deepgram_stt(api_key: str, model: str = "nova-2-phonecall", language: str = "multi", sample_rate: int = 16000) -> DeepgramSTTService:
    """Exposed factory for the main app to build the Deepgram service via Pillar 2."""
    return DeepgramSTTService(
        api_key=api_key,
        sample_rate=sample_rate,
        settings=DeepgramSTTService.Settings(
            model=model,
            language=language,
            smart_format=True,
            interim_results=True,
            endpointing=400,   # ms before Deepgram finalises a transcript (calibrated from 500ms to 400ms)
        ),
    )

def build_vad_analyzer() -> SileroVADAnalyzer:
    """Exposed factory for the main app to build the VAD analyzer via Pillar 2.
    
    Timing notes:
      start_secs: how long speech must persist before VAD fires speech-start (0.2s filters transient clicks/breaths).
      stop_secs: silence duration after which VAD declares end-of-turn (calibrated to 0.4s for low latency without cutting words).
      confidence: minimum VAD confidence score (0–1).
      min_volume: minimum audio volume to consider as speech.
    """
    return SileroVADAnalyzer(
        params=VADParams(
            confidence=0.75,
            start_secs=0.2,
            stop_secs=0.4,
            min_volume=0.08,
        )
    )