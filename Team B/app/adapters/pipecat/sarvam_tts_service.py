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

from pipecat.frames.frames import Frame, TTSAudioRawFrame, TTSStartedFrame, TTSStoppedFrame, ErrorFrame, AggregationType
from pipecat.services.tts_service import TTSService
from pipecat.utils.text.base_text_aggregator import BaseTextAggregator
from pipecat.utils.text.simple_text_aggregator import Aggregation

# Global quota state tracking to prevent repeated 402 latency penalties
_SARVAM_QUOTA_EXHAUSTED: bool = False
_SARVAM_LAST_ERROR_TIME: float = 0.0
_LAST_SEEN_KEY: str = ""

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


def reset_sarvam_quota_status() -> None:
    """Manually reset the Sarvam quota exhaustion flag."""
    global _SARVAM_QUOTA_EXHAUSTED
    _SARVAM_QUOTA_EXHAUSTED = False
    logger.info("Sarvam AI quota exhaustion status has been reset.")


def get_edge_neural_voice(voice_id: str) -> str:
    """Resolve an Indian Neural voice for the specified persona."""
    clean_id = (voice_id or "shreya").strip().lower()
    return EDGE_NEURAL_VOICE_MAP.get(clean_id, "hi-IN-SwaraNeural")


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

        clauses = [c.strip() for c in re.split(r'(?<=[.?!,;])\s+', text.strip()) if c.strip()]
        if not clauses:
            clauses = [text.strip()]

        req_sample_rate = self.sample_rate if self.sample_rate in (8000, 16000, 22050) else 16000

        try:
            yield TTSStartedFrame()

            # Determine whether to attempt Sarvam or stream directly via Neural Indian Voice Engine
            should_try_sarvam = bool(self.api_key and not _SARVAM_QUOTA_EXHAUSTED)

            for clause in clauses:
                emitted_for_clause = False

                if should_try_sarvam:
                    try:
                        session = await self._get_session()
                        headers = {
                            "api-subscription-key": self.api_key,
                            "Content-Type": "application/json",
                        }
                        payload = {
                            "inputs": [clause],
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

                        async with session.post(self.url, headers=headers, json=payload, timeout=6.0) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                audios = data.get("audios", [])
                                if audios:
                                    raw_audio = base64.b64decode(audios[0])
                                    raw_pcm = raw_audio
                                    detected_rate = req_sample_rate
                                    num_channels = 1
                                    try:
                                        with wave.open(io.BytesIO(raw_audio), 'rb') as wav_file:
                                            detected_rate = wav_file.getframerate()
                                            num_channels = wav_file.getnchannels()
                                            raw_pcm = wav_file.readframes(wav_file.getnframes())
                                    except Exception:
                                        pass

                                    chunk_size = 1280
                                    for i in range(0, len(raw_pcm), chunk_size):
                                        chunk = raw_pcm[i : i + chunk_size]
                                        yield TTSAudioRawFrame(
                                            audio=chunk,
                                            sample_rate=detected_rate,
                                            num_channels=num_channels,
                                        )
                                    emitted_for_clause = True
                            else:
                                err_body = await resp.text()
                                if resp.status == 402 or "insufficient_quota" in err_body.lower() or "credits" in err_body.lower():
                                    _SARVAM_QUOTA_EXHAUSTED = True
                                    _SARVAM_LAST_ERROR_TIME = time.time()
                                    logger.warning(
                                        f"[VOICE_ENGINE] Sarvam quota exhausted (HTTP 402). "
                                        f"Instantly switching to high-fidelity Neural Indian Voice engine: "
                                        f"persona='{self.voice}' -> model='{self.edge_voice}'"
                                    )
                                else:
                                    logger.warning(
                                        f"[VOICE_ENGINE] Sarvam API returned status {resp.status}. "
                                        f"Routing to Neural Indian Voice engine."
                                    )
                                should_try_sarvam = False

                    except Exception as s_err:
                        logger.warning(f"[VOICE_ENGINE] Sarvam request error: {s_err}. Routing to Neural Indian Voice engine.")
                        should_try_sarvam = False

                # If Sarvam was not attempted, failed, or quota exhausted, stream via Edge Neural Voice
                if not emitted_for_clause:
                    async for pcm_chunk in self._stream_edge_neural_pcm(clause, req_sample_rate):
                        yield TTSAudioRawFrame(
                            audio=pcm_chunk,
                            sample_rate=req_sample_rate,
                            num_channels=1,
                        )

            yield TTSStoppedFrame()

        except Exception as e:
            logger.error(f"SarvamTTSService execution error: {e}")
            yield ErrorFrame(error=f"Voice synthesis failed: {e}")
