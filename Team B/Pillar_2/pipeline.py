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
            endpointing=500,   # ms before Deepgram finalises a transcript; 300 was too aggressive
                               # for digit-by-digit phone entry causing premature finalization
        ),
    )

def build_vad_analyzer() -> SileroVADAnalyzer:
    """Exposed factory for the main app to build the VAD analyzer via Pillar 2.
    
    Timing notes:
      start_secs: how long speech must persist before VAD fires speech-start.
        0.1s = responsive; lower = more false positives from noise.
      stop_secs: silence duration after which VAD declares end-of-turn.
        1.0s = allows natural pauses between digits during phone entry.
        Was 0.6s which was cutting turns short mid-digit-sequence.
      confidence: minimum VAD confidence score (0–1).
      min_volume: minimum audio volume to consider as speech.
    """
    return SileroVADAnalyzer(
        params=VADParams(
            confidence=0.7,
            start_secs=0.1,
            stop_secs=1.0,
            min_volume=0.05,
        )
    )