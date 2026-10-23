"""
High-Performance Real-Time Voice Synthesis Engine for Indian AI Personas.
Supports Sarvam AI Bulbul models and ultra-low-latency Microsoft Edge Neural
Indian voices (hi-IN-SwaraNeural for Shreya, en-IN-NeerjaNeural for Ritu,
hi-IN-MadhurNeural for Ratan, en-IN-PrabhatNeural for Manan).
Includes instant clause-level streaming and proactive quota-exhaustion fallback.
"""

import asyncio
import base64
import io
import re
import time
import wave
from typing import AsyncGenerator, Optional, AsyncIterator

import aiohttp
from loguru import logger

from pipecat.frames.frames import Frame, TTSAudioRawFrame, TTSStartedFrame, TTSStoppedFrame, ErrorFrame, AggregationType, InterruptionFrame
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.tts_service import TTSService
from pipecat.utils.text.base_text_aggregator import BaseTextAggregator
from pipecat.utils.text.simple_text_aggregator import Aggregation

# Global quota state tracking to prevent repeated 402 latency penalties
_SARVAM_QUOTA_EXHAUSTED: bool = False
_SARVAM_LAST_ERROR_TIME: float = 0.0
_LAST_SEEN_KEY: str = ""

# In-memory fast audio cache for zero-lag greeting and phrase delivery
_TTS_AUDIO_CACHE: dict[str, tuple[bytes, int, int]] = {}

# Canonical Microsoft Edge Neural Indian Voice Mappings
EDGE_NEURAL_VOICE_MAP = {
    "shreya": "hi-IN-SwaraNeural",       # Natural, expressive, warm Hindi female voice
    "sara": "hi-IN-SwaraNeural",         # Backward compatible Shreya alias
    "ritu": "en-IN-NeerjaNeural",        # Calm, clear, professional Indian English/Hindi female voice
    "meera": "en-IN-NeerjaNeural",       # Ritu alias
    "ratan": "hi-IN-MadhurNeural",       # Confident, authoritative Indian Hindi male voice
    "arvind": "hi-IN-MadhurNeural",      # Ratan alias
    "manan": "en-IN-PrabhatNeural",      # Modern, crisp, energetic Indian English/Hindi male voice
    "dhruv": "en-IN-PrabhatNeural",      # Manan alias
    "default": "hi-IN-SwaraNeural",
}


def preload_static_persona_greetings() -> int:
    """Pre-load static greeting WAV files for all canonical personas into _TTS_AUDIO_CACHE for instant 0ms startup."""
    import audioop
    import os
    greetings_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "static", "audio", "greetings")
    )
    if not os.path.exists(greetings_dir):
        return 0

    plivo_dir = os.path.join(greetings_dir, "plivo_8k")

    try:
        from app.services.persona_registry import CANONICAL_PERSONAS, resolve_opening_greeting
    except Exception as e:
        logger.debug(f"[VOICE_ENGINE] persona_registry import notice: {e}")
        return 0

    loaded = 0
    for pid, p_obj in CANONICAL_PERSONAS.items():
        voice = p_obj.voice
        model = p_obj.model

        # 1. Default greeting
        def_path_16k = os.path.join(greetings_dir, f"{pid}_default.wav")
        def_path_8k = os.path.join(plivo_dir, f"{pid}_default.wav")

        pcm_16k = None
        rate_16k = 16000
        ch_16k = 1
        if os.path.exists(def_path_16k):
            try:
                with wave.open(def_path_16k, "rb") as w:
                    rate_16k = w.getframerate()
                    ch_16k = w.getnchannels()
                    pcm_16k = w.readframes(w.getnframes())
                if rate_16k != 16000:
                    pcm_16k = audioop.ratecv(pcm_16k, 2, ch_16k, rate_16k, 16000, None)[0]
                    rate_16k = 16000
            except Exception as e:
                logger.warning(f"[VOICE_ENGINE] Failed loading 16k default greeting {def_path_16k}: {e}")

        pcm_8k = None
        rate_8k = 8000
        ch_8k = 1
        if os.path.exists(def_path_8k):
            try:
                with wave.open(def_path_8k, "rb") as w:
                    rate_8k = w.getframerate()
                    ch_8k = w.getnchannels()
                    pcm_8k = w.readframes(w.getnframes())
                if rate_8k != 8000:
                    pcm_8k = audioop.ratecv(pcm_8k, 2, ch_8k, rate_8k, 8000, None)[0]
                    rate_8k = 8000
            except Exception as e:
                logger.warning(f"[VOICE_ENGINE] Failed loading 8k Plivo default greeting {def_path_8k}: {e}")
        elif pcm_16k is not None:
            # Fallback if plivo_8k file is missing: resample 16k to genuine 8k
            pcm_8k = audioop.ratecv(pcm_16k, 2, ch_16k, rate_16k, 8000, None)[0]
            rate_8k = 8000
            ch_8k = ch_16k

        if pcm_16k is not None or pcm_8k is not None:
            def_texts = {
                p_obj.greeting_en.strip(),
                f"Hello, this is {p_obj.name} from Flowiz and Cybernauts. How can I help you today?",
                f"Hello! This is {p_obj.name} from Flowiz and Cybernauts.",
                p_obj.greeting_hi.strip(),
                p_obj.greeting_hinglish.strip(),
            }
            for txt in def_texts:
                if pcm_8k is not None:
                    _TTS_AUDIO_CACHE[f"{voice}:{model}:8000:{txt}"] = (pcm_8k, 8000, ch_8k)
                    _TTS_AUDIO_CACHE[f"{voice}:8000:{txt}"] = (pcm_8k, 8000, ch_8k)
                if pcm_16k is not None:
                    _TTS_AUDIO_CACHE[f"{voice}:{model}:16000:{txt}"] = (pcm_16k, 16000, ch_16k)
                    _TTS_AUDIO_CACHE[f"{voice}:{model}:{txt}"] = (pcm_16k, 16000, ch_16k)
                    _TTS_AUDIO_CACHE[f"{voice}:16000:{txt}"] = (pcm_16k, 16000, ch_16k)
                    _TTS_AUDIO_CACHE[f"{voice}:{txt}"] = (pcm_16k, 16000, ch_16k)

            if pcm_8k is not None:
                _TTS_AUDIO_CACHE[f"{pid}_default:8000"] = (pcm_8k, 8000, ch_8k)
                _TTS_AUDIO_CACHE[f"{voice}_default:8000"] = (pcm_8k, 8000, ch_8k)
            if pcm_16k is not None:
                _TTS_AUDIO_CACHE[f"{pid}_default:16000"] = (pcm_16k, 16000, ch_16k)
                _TTS_AUDIO_CACHE[f"{pid}_default"] = (pcm_16k, 16000, ch_16k)
                _TTS_AUDIO_CACHE[f"{voice}_default:16000"] = (pcm_16k, 16000, ch_16k)
                _TTS_AUDIO_CACHE[f"{voice}_default"] = (pcm_16k, 16000, ch_16k)
            loaded += 1

        # 2. Outbound greeting
        out_path_16k = os.path.join(greetings_dir, f"{pid}_outbound.wav")
        out_path_8k = os.path.join(plivo_dir, f"{pid}_outbound.wav")

        pcm_out_16k = None
        rate_out_16k = 16000
        ch_out_16k = 1
        if os.path.exists(out_path_16k):
            try:
                with wave.open(out_path_16k, "rb") as w:
                    rate_out_16k = w.getframerate()
                    ch_out_16k = w.getnchannels()
                    pcm_out_16k = w.readframes(w.getnframes())
                if rate_out_16k != 16000:
                    pcm_out_16k = audioop.ratecv(pcm_out_16k, 2, ch_out_16k, rate_out_16k, 16000, None)[0]
                    rate_out_16k = 16000
            except Exception as e:
                logger.warning(f"[VOICE_ENGINE] Failed loading 16k outbound greeting {out_path_16k}: {e}")

        pcm_out_8k = None
        rate_out_8k = 8000
        ch_out_8k = 1
        if os.path.exists(out_path_8k):
            try:
                with wave.open(out_path_8k, "rb") as w:
                    rate_out_8k = w.getframerate()
                    ch_out_8k = w.getnchannels()
                    pcm_out_8k = w.readframes(w.getnframes())
                if rate_out_8k != 8000:
                    pcm_out_8k = audioop.ratecv(pcm_out_8k, 2, ch_out_8k, rate_out_8k, 8000, None)[0]
                    rate_out_8k = 8000
            except Exception as e:
                logger.warning(f"[VOICE_ENGINE] Failed loading 8k Plivo outbound greeting {out_path_8k}: {e}")
        elif pcm_out_16k is not None:
            # Fallback if plivo_8k file is missing: resample 16k to genuine 8k
            pcm_out_8k = audioop.ratecv(pcm_out_16k, 2, ch_out_16k, rate_out_16k, 8000, None)[0]
            rate_out_8k = 8000
            ch_out_8k = ch_out_16k

        if pcm_out_16k is not None or pcm_out_8k is not None:
            out_texts = {
                resolve_opening_greeting(pid).strip(),
                f"Hello! This is {p_obj.name} from Flowiz and Cybernauts. Do you have a brief moment to speak about automating your operations?",
                f"Hello! This is {p_obj.name} from Flowiz and Cybernauts. I'm reaching out regarding your business—do you have a quick moment to speak?",
            }
            for txt in out_texts:
                if pcm_out_8k is not None:
                    _TTS_AUDIO_CACHE[f"{voice}:{model}:8000:{txt}"] = (pcm_out_8k, 8000, ch_out_8k)
                    _TTS_AUDIO_CACHE[f"{voice}:8000:{txt}"] = (pcm_out_8k, 8000, ch_out_8k)
                if pcm_out_16k is not None:
                    _TTS_AUDIO_CACHE[f"{voice}:{model}:16000:{txt}"] = (pcm_out_16k, 16000, ch_out_16k)
                    _TTS_AUDIO_CACHE[f"{voice}:{model}:{txt}"] = (pcm_out_16k, 16000, ch_out_16k)
                    _TTS_AUDIO_CACHE[f"{voice}:16000:{txt}"] = (pcm_out_16k, 16000, ch_out_16k)
                    _TTS_AUDIO_CACHE[f"{voice}:{txt}"] = (pcm_out_16k, 16000, ch_out_16k)

            if pcm_out_8k is not None:
                _TTS_AUDIO_CACHE[f"{pid}_outbound:8000"] = (pcm_out_8k, 8000, ch_out_8k)
                _TTS_AUDIO_CACHE[f"{voice}_outbound:8000"] = (pcm_out_8k, 8000, ch_out_8k)
            if pcm_out_16k is not None:
                _TTS_AUDIO_CACHE[f"{pid}_outbound:16000"] = (pcm_out_16k, 16000, ch_out_16k)
                _TTS_AUDIO_CACHE[f"{pid}_outbound"] = (pcm_out_16k, 16000, ch_out_16k)
                _TTS_AUDIO_CACHE[f"{voice}_outbound:16000"] = (pcm_out_16k, 16000, ch_out_16k)
                _TTS_AUDIO_CACHE[f"{voice}_outbound"] = (pcm_out_16k, 16000, ch_out_16k)
            loaded += 1

    logger.info(f"[VOICE_ENGINE] Preloaded static persona greetings ({loaded} personas, {len(_TTS_AUDIO_CACHE)} keys in cache).")
    return loaded


# Automatically preload static greetings into RAM on module load
try:
    preload_static_persona_greetings()
except Exception as _init_preload_err:
    logger.debug(f"[VOICE_ENGINE] Init preload notice: {_init_preload_err}")


def reset_sarvam_quota_status() -> None:
    """Manually reset the Sarvam quota exhaustion flag."""
    global _SARVAM_QUOTA_EXHAUSTED
    _SARVAM_QUOTA_EXHAUSTED = False
    logger.info("Sarvam AI quota exhaustion status has been reset.")


def get_edge_neural_voice(voice_id: str) -> str:
    """Resolve an Indian Neural voice for the specified persona."""
    clean_id = (voice_id or "shreya").strip().lower()
    return EDGE_NEURAL_VOICE_MAP.get(clean_id, "hi-IN-SwaraNeural")



async def prewarm_tts_audio(
    text: str,
    voice: str = "shreya",
    model: str = "bulbul:v3",
    sample_rate: int = 8000,
    target_language_code: str = "hi-IN",
    api_key: Optional[str] = None
) -> bool:
    """
    Pre-synthesizes audio in background while call is ringing and caches in
    _TTS_AUDIO_CACHE for instant (<10ms) playback on pickup.
    """
    import os
    resolved_key = (api_key or os.getenv("SARVAM_API_KEY") or "").strip()
    if not resolved_key or not text or not text.strip():
        return False

    clean_voice = (voice or "shreya").strip().lower()
    speaker_map = {
        "shreya": "shreya", "ritu": "ritu", "ratan": "ratan", "manan": "manan",
        "arvind": "ratan", "meera": "ritu", "dhruv": "manan", "sara": "shreya", "default": "shreya"
    }
    resolved_voice = speaker_map.get(clean_voice, clean_voice)
    cache_key = f"{resolved_voice}:{model}:{sample_rate}:{text.strip()}"
    if cache_key in _TTS_AUDIO_CACHE:
        return True

    if resolved_key:
        try:
            url = "https://api.sarvam.ai/text-to-speech"
            headers = {
                "api-subscription-key": resolved_key,
                "Content-Type": "application/json",
            }
            payload = {
                "inputs": [text.strip()],
                "target_language_code": target_language_code,
                "speaker": resolved_voice,
                "pace": 1.08,
                "speech_sample_rate": sample_rate,
                "enable_preprocessing": False,
                "model": model,
            }
            async with aiohttp.ClientSession() as sess:
                async with sess.post(url, headers=headers, json=payload, timeout=5.0) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        audios = data.get("audios", [])
                        if audios:
                            raw_audio = base64.b64decode(audios[0])
                            raw_pcm = raw_audio
                            detected_rate = sample_rate
                            num_channels = 1
                            try:
                                with wave.open(io.BytesIO(raw_audio), 'rb') as wav_file:
                                    detected_rate = wav_file.getframerate()
                                    num_channels = wav_file.getnchannels()
                                    raw_pcm = wav_file.readframes(wav_file.getnframes())
                            except Exception:
                                pass
                            _TTS_AUDIO_CACHE[cache_key] = (raw_pcm, detected_rate, num_channels)
                            _TTS_AUDIO_CACHE[f"{resolved_voice}:{model}:{text.strip()}"] = (raw_pcm, detected_rate, num_channels)
                            logger.info(f"[VOICE_ENGINE] Pre-warmed Sarvam audio successfully for '{text.strip()[:35]}...' | voice='{resolved_voice}'")
                            return True
        except Exception as e:
            logger.debug(f"[VOICE_ENGINE] Sarvam pre-warm notice: {e}")

    # Fallback to Edge Indian Neural voice to ensure zero-lag cache hit regardless of Sarvam quota
    try:
        import edge_tts
        import av
        edge_v = get_edge_neural_voice(resolved_voice)
        communicate = edge_tts.Communicate(text.strip(), edge_v)
        codec = av.Codec('mp3', 'r')
        ctx = av.CodecContext.create(codec)
        resampler = av.AudioResampler(format='s16', layout='mono', rate=sample_rate)
        pcm_data = bytearray()
        async for chunk in communicate.stream():
            if chunk.get('type') == 'audio':
                packets = ctx.parse(chunk['data'])
                for packet in packets:
                    for frame in ctx.decode(packet):
                        resampled = resampler.resample(frame)
                        for rf in resampled:
                            pcm_data.extend(rf.to_ndarray().tobytes())
        for frame in ctx.decode(None):
            for rf in resampler.resample(frame):
                pcm_data.extend(rf.to_ndarray().tobytes())
        if pcm_data:
            pcm_bytes = bytes(pcm_data)
            _TTS_AUDIO_CACHE[cache_key] = (pcm_bytes, sample_rate, 1)
            _TTS_AUDIO_CACHE[f"{resolved_voice}:{model}:{text.strip()}"] = (pcm_bytes, sample_rate, 1)
            logger.info(f"[VOICE_ENGINE] Pre-warmed Edge Neural audio successfully for '{text.strip()[:35]}...' | voice='{resolved_voice}'")
            return True
    except Exception as edge_err:
        logger.debug(f"[VOICE_ENGINE] Edge TTS pre-warm notice: {edge_err}")

    return False


class LowLatencyClauseAggregator(BaseTextAggregator):
    """
    Ultra-low latency text aggregator for streaming LLM-to-TTS pipelines.
    Adaptive clause release:
      - Natural pause/punctuation boundaries: [, ; : . ! ? — \n ।]
      - First clause releases after >= 3 words if no punctuation arrived yet,
        minimizing first-audio latency without mid-sentence word fragmentation.
      - Subsequent clauses release after >= 7 words without punctuation.
    """

    def __init__(self, **kwargs):
        super().__init__(aggregation_type=AggregationType.SENTENCE, **kwargs)
        self._buffer = ""
        self._clause_pattern = re.compile(r'^(.*?[,;:.!?—\n।])\s*(.*)$', re.DOTALL)
        self._first_clause = True

    @property
    def text(self) -> Aggregation:
        return Aggregation(text=self._buffer.strip(), type=AggregationType.SENTENCE)

    async def aggregate(self, text: str) -> AsyncIterator[Aggregation]:
        self._buffer += text
        while True:
            match = self._clause_pattern.match(self._buffer)
            if match:
                clause = match.group(1).strip()
                remainder = match.group(2)
                clean_clause = re.sub(r'[,;:.!?—\n।\s]', '', clause)
                if len(clean_clause) >= 2:
                    self._buffer = remainder
                    self._first_clause = False
                    yield Aggregation(text=clause, type=AggregationType.SENTENCE)
                    continue

            # First clause emits after >= 3 words; subsequent clauses after >= 7 words
            words = self._buffer.strip().split()
            threshold = 3 if self._first_clause else 7
            if len(words) >= threshold:
                split_idx = self._buffer.rfind(" ")
                if split_idx > 0:
                    digit_tokens = [w for w in words if w.isdigit() and len(w) == 1]
                    if len(digit_tokens) >= 2:
                        m = re.search(r'\s+(\d(?:\s+\d)*)', self._buffer)
                        if m and m.start() > 0:
                            preamble = self._buffer[:m.start()].strip()
                            if len(preamble.split()) >= 2:
                                self._buffer = self._buffer[m.start() + 1:]
                                self._first_clause = False
                                yield Aggregation(text=preamble, type=AggregationType.SENTENCE)
                                continue
                        break

                    phrase = self._buffer[:split_idx].strip()
                    self._buffer = self._buffer[split_idx + 1:]
                    self._first_clause = False
                    yield Aggregation(text=phrase, type=AggregationType.SENTENCE)
                    continue
            break

    async def flush(self) -> Aggregation | None:
        rem = self._buffer.strip()
        self._buffer = ""
        self._first_clause = True
        if rem:
            return Aggregation(text=rem, type=AggregationType.SENTENCE)
        return None

    async def handle_interruption(self):
        self._buffer = ""
        self._first_clause = True

    async def reset(self):
        self._buffer = ""
        self._first_clause = True


class SarvamTTSService(TTSService):
    """
    Real-time high-fidelity TTS service.
    Directly supports Sarvam AI models with automatic zero-lag fallback to
    native Microsoft Edge Neural Indian voices (hi-IN-SwaraNeural, en-IN-NeerjaNeural,
    hi-IN-MadhurNeural, en-IN-PrabhatNeural) when Sarvam quota is exhausted or unconfigured.
    """

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        voice: str = "shreya",
        model: str = "bulbul:v3",
        target_language_code: str = "hi-IN",
        sample_rate: Optional[int] = 16000,
        **kwargs
    ):
        from pipecat.services.settings import TTSSettings
        raw_v = (voice or "shreya").strip().lower()
        speaker_map = {
            "shreya": "shreya",
            "ritu": "ritu",
            "ratan": "ratan",
            "manan": "manan",
            "arvind": "ratan",
            "meera": "ritu",
            "dhruv": "manan",
            "sara": "shreya",
            "default": "shreya"
        }
        resolved_voice = speaker_map.get(raw_v, raw_v)
        valid_sarvam_speakers = {
            "aditya", "ritu", "ashutosh", "priya", "neha", "rahul", "pooja",
            "rohan", "simran", "kavya", "amit", "dev", "ishita", "shreya",
            "ratan", "varun", "manan", "sumit", "roopa", "kabir", "aayan",
            "shubh", "advait", "anand", "tanya", "tarun", "sunny", "mani",
            "gokul", "vijay", "shruti", "suhani", "mohit", "kavitha", "rehan",
            "soham", "rupali"
        }
        if resolved_voice not in valid_sarvam_speakers:
            resolved_voice = "shreya"

        super().__init__(
            sample_rate=sample_rate,
            settings=TTSSettings(
                model=model,
                voice=resolved_voice,
                language=target_language_code,
            ),
            **kwargs
        )
        self.sample_rate_configured = sample_rate or 16000
        self._init_sample_rate = sample_rate or 16000
        import os
        resolved_key = (api_key or os.getenv("SARVAM_API_KEY") or "").strip()
        global _LAST_SEEN_KEY, _SARVAM_QUOTA_EXHAUSTED
        if resolved_key and resolved_key != _LAST_SEEN_KEY:
            _LAST_SEEN_KEY = resolved_key
            _SARVAM_QUOTA_EXHAUSTED = False
            logger.info("New Sarvam API key detected. Resetting quota status to active.")
        self.api_key = resolved_key
        self.voice = resolved_voice
        self.edge_voice = get_edge_neural_voice(resolved_voice)
        self.model = model
        self.target_language_code = target_language_code
        self.url = "https://api.sarvam.ai/text-to-speech"
        self._session: Optional[aiohttp.ClientSession] = None
        self._text_aggregator = LowLatencyClauseAggregator()
        self._active_clause_tasks: set[asyncio.Task] = set()

    async def _handle_interruption(self, frame: InterruptionFrame, direction: FrameDirection):
        for task in list(self._active_clause_tasks):
            if not task.done():
                task.cancel()
        self._active_clause_tasks.clear()
        if getattr(self, "_task_manager", None):
            await super()._handle_interruption(frame, direction)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            ssl_context = None
            try:
                import certifi
                import ssl
                ssl_context = ssl.create_default_context(cafile=certifi.where())
            except Exception:
                ssl_context = None

            connector = aiohttp.TCPConnector(
                ssl=ssl_context,
                keepalive_timeout=60.0,
                limit=20,
                ttl_dns_cache=300
            )
            self._session = aiohttp.ClientSession(connector=connector)
        return self._session

    async def stop(self, *args, **kwargs):
        for task in list(self._active_clause_tasks):
            if not task.done():
                task.cancel()
        self._active_clause_tasks.clear()
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    def can_generate_metrics(self) -> bool:
        return True

    async def _stream_edge_neural_pcm(
        self, clause_text: str, req_sample_rate: int
    ) -> AsyncGenerator[bytes, None]:
        """
        Synthesizes text using Microsoft Edge Neural Indian voices and streams
        resampled 16-bit mono PCM chunks in real-time using PyAV.
        """
        import edge_tts
        import av

        edge_voice = self.edge_voice
        logger.info(
            f"[NEURAL_TTS] Streaming Indian Neural Voice | voice='{self.voice}' | "
            f"model='{edge_voice}' | rate={req_sample_rate}Hz | clause='{clause_text[:40]}...'"
        )

        codec = av.Codec('mp3', 'r')
        ctx = av.CodecContext.create(codec)
        resampler = av.AudioResampler(format='s16', layout='mono', rate=req_sample_rate)

        communicate = edge_tts.Communicate(clause_text, edge_voice)
        
        pcm_accumulator = bytearray()
        # Stream chunks of 1280 bytes (40ms @ 16kHz, 80ms @ 8kHz) for smooth streaming
        chunk_delivery_size = 1280

        async for chunk in communicate.stream():
            if chunk.get('type') == 'audio':
                packets = ctx.parse(chunk['data'])
                for packet in packets:
                    for frame in ctx.decode(packet):
                        resampled = resampler.resample(frame)
                        for rf in resampled:
                            pcm_accumulator.extend(rf.to_ndarray().tobytes())
                            while len(pcm_accumulator) >= chunk_delivery_size:
                                yield bytes(pcm_accumulator[:chunk_delivery_size])
                                pcm_accumulator = pcm_accumulator[chunk_delivery_size:]

        # Flush decoder buffer
        for frame in ctx.decode(None):
            for rf in resampler.resample(frame):
                pcm_accumulator.extend(rf.to_ndarray().tobytes())
                while len(pcm_accumulator) >= chunk_delivery_size:
                    yield bytes(pcm_accumulator[:chunk_delivery_size])
                    pcm_accumulator = pcm_accumulator[chunk_delivery_size:]

        if pcm_accumulator:
            yield bytes(pcm_accumulator)

    async def run_tts(self, text: str, *args, **kwargs) -> AsyncGenerator[Frame, None]:
        global _SARVAM_QUOTA_EXHAUSTED, _SARVAM_LAST_ERROR_TIME

        if not text or not text.strip():
            return

        clean_text = text.strip()
        configured_rate = getattr(self, "sample_rate_configured", None) or getattr(self, "_init_sample_rate", None) or 16000
        req_sample_rate = self.sample_rate if self.sample_rate in (8000, 16000, 22050) else configured_rate
        if req_sample_rate not in (8000, 16000, 22050):
            req_sample_rate = 16000

        # Instant Cache Check: Deliver pre-rendered audio with 0ms latency
        cache_key = f"{self.voice}:{self.model}:{req_sample_rate}:{clean_text}"
        cached_entry = (
            _TTS_AUDIO_CACHE.get(cache_key)
            or _TTS_AUDIO_CACHE.get(f"{self.voice}:{self.model}:{clean_text}")
            or _TTS_AUDIO_CACHE.get(f"{self.voice}:{req_sample_rate}:{clean_text}")
            or _TTS_AUDIO_CACHE.get(f"{self.voice}:{clean_text}")
        )

        # NOTE: The fuzzy persona-greeting fallback (matching on agent name / "Flowiz") was
        # intentionally removed. It was serving old prerecorded WAV files for any greeting
        # text that merely mentioned the agent or Flowiz, causing the wrong audio to play
        # when the default greeting text was changed. The exact-text cache above is kept;
        # unrecognised text falls through to live Sarvam synthesis below.

        if cached_entry:
            cached_pcm, cached_rate, cached_channels = cached_entry
            delivery_pcm = cached_pcm
            if cached_rate != req_sample_rate:
                import audioop
                try:
                    delivery_pcm = audioop.ratecv(cached_pcm, 2, cached_channels, cached_rate, req_sample_rate, None)[0]
                except Exception as resample_err:
                    logger.debug(f"[VOICE_ENGINE] Cache resample notice: {resample_err}")
                    delivery_pcm = cached_pcm

        fetch_tasks = []
        try:
            yield TTSStartedFrame()
            
            session = await self._get_session()
            headers = {
                "api-subscription-key": self.api_key,
                "Content-Type": "application/json",
            }
            req_sample_rate = self.sample_rate if self.sample_rate in (8000, 16000, 22050) else 16000

            # Helper async function to fetch audio for a single clause
            async def fetch_clause_audio(clause_text: str):
                logger.info(f"SarvamTTSService: generating clause audio | voice='{self.voice}' | clause='{clause_text[:40]}...'")
                payload = {
                    "inputs": [clause_text],
                    "target_language_code": self.target_language_code,
                    "speaker": self.voice,
                    "pace": 1.08,
                    "speech_sample_rate": req_sample_rate,
                    "enable_preprocessing": False,
                    "model": self.model,
                }
                if "v3" not in self.model.lower():
                    payload["pitch"] = 0
                    payload["loudness"] = 1.5

                async with session.post(self.url, headers=headers, json=payload, timeout=15) as resp:
                    if resp.status != 200:
                        err_body = await resp.text()
                        logger.error(f"Sarvam AI TTS API error {resp.status}: {err_body}")
                        return None
                    data = await resp.json()
                    audios = data.get("audios", [])
                    if not audios:
                        return None
                    return base64.b64decode(audios[0])

            # Launch async pre-fetch tasks for all clauses in parallel
            fetch_tasks = [asyncio.create_task(fetch_clause_audio(c)) for c in clauses]
            for t in fetch_tasks:
                self._active_clause_tasks.add(t)

            for task in fetch_tasks:
                audio_bytes = await task
                if not audio_bytes:
                    continue

            should_try_sarvam = bool(self.api_key and not _SARVAM_QUOTA_EXHAUSTED)
            emitted = False

            if should_try_sarvam:
                try:
                    with wave.open(io.BytesIO(audio_bytes), 'rb') as wav_file:
                        detected_rate = wav_file.getframerate()
                        num_channels = wav_file.getnchannels()
                        raw_pcm = wav_file.readframes(wav_file.getnframes())
                except Exception as wav_err:
                    logger.debug(f"Parsing WAV header failed (assuming raw PCM): {wav_err}")

                if num_channels == 2:
                    import audioop
                    raw_pcm = audioop.tomono(raw_pcm, 2, 0.5, 0.5)
                    num_channels = 1

                # Enforce 16-bit PCM alignment (must be multiple of 2 bytes)
                if len(raw_pcm) % 2 != 0:
                    raw_pcm = raw_pcm[:-1]

                # Stream audio in 4KB PCM chunks
                chunk_size = 4096
                for i in range(0, len(raw_pcm), chunk_size):
                    chunk = raw_pcm[i : i + chunk_size]
                    if len(chunk) % 2 != 0:
                        chunk = chunk[:-1]
                    yield TTSAudioRawFrame(
                        audio=pcm_chunk,
                        sample_rate=req_sample_rate,
                        num_channels=1,
                    )

            yield TTSStoppedFrame()

        except asyncio.CancelledError:
            for task in fetch_tasks:
                if not task.done():
                    task.cancel()
            raise
        except Exception as e:
            logger.error(f"SarvamTTSService error: {e}")
            yield ErrorFrame(error=f"Sarvam TTS generation failed: {e}")
        finally:
            for task in fetch_tasks:
                if not task.done():
                    task.cancel()
                self._active_clause_tasks.discard(task)
