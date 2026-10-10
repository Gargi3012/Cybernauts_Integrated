
"""
Custom Pipecat TTS service for Sarvam AI (supporting Shreya, Meera, etc.).
"""

import asyncio
import base64
import io
import wave
from typing import AsyncGenerator, Optional, AsyncIterator
import re

import aiohttp
from loguru import logger

from pipecat.frames.frames import Frame, TTSAudioRawFrame, TTSStartedFrame, TTSStoppedFrame, ErrorFrame, AggregationType
from pipecat.services.tts_service import TTSService
from pipecat.utils.text.base_text_aggregator import BaseTextAggregator
from pipecat.utils.text.simple_text_aggregator import Aggregation


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
                # Ensure clause contains at least two non-punctuation characters
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
                    # Prevent slicing through an active sequence of spaced phone digits
                    digit_tokens = [w for w in words if w.isdigit() and len(w) == 1]
                    if len(digit_tokens) >= 2:
                        # If there is non-digit preamble before the digits (e.g. 'your number is'),
                        # split before the first digit so the preamble can stream immediately.
                        m = re.search(r'\s+(\d(?:\s+\d)*)', self._buffer)
                        if m and m.start() > 0:
                            preamble = self._buffer[:m.start()].strip()
                            if len(preamble.split()) >= 2:
                                self._buffer = self._buffer[m.start() + 1:]
                                self._first_clause = False
                                yield Aggregation(text=preamble, type=AggregationType.SENTENCE)
                                continue
                        # While accumulating remaining digits, wait for punctuation or flush
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
    """Real-time TTS service using Sarvam AI Bulbul models."""

    def __init__(
        self,
        *,
        api_key: str,
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
        self.api_key = api_key
        self.voice = resolved_voice
        self.model = model
        self.target_language_code = target_language_code
        self.url = "https://api.sarvam.ai/text-to-speech"
        self._session: Optional[aiohttp.ClientSession] = None
        # Replace default sentence-lookahead aggregator with immediate low-latency clause aggregator
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

    async def run_tts(self, text: str, *args, **kwargs) -> AsyncGenerator[Frame, None]:
        if not text or not text.strip():
            return

        if not self.api_key:
            logger.error("SarvamTTSService error: SARVAM_API_KEY is missing.")
            yield ErrorFrame(error="Sarvam API key is missing")
            return

        import re
        clauses = [c.strip() for c in re.split(r'(?<=[.?!,;])\s+', text.strip()) if c.strip()]
        if not clauses:
            clauses = [text.strip()]

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
                        logger.warning(f"Sarvam AI TTS API status {resp.status}: {err_body[:100]}. Triggering high-quality fallback TTS...")
                        try:
                            import os
                            openai_key = os.getenv("OPENAI_API_KEY")
                            if openai_key:
                                from openai import AsyncOpenAI
                                oai_client = AsyncOpenAI(api_key=openai_key)
                                oai_voice_map = {"shreya": "nova", "ritu": "shimmer", "ratan": "onyx", "manan": "echo"}
                                oai_voice = oai_voice_map.get(self.voice.lower(), "nova" if self.voice in ("shreya", "ritu") else "onyx")
                                oai_resp = await oai_client.audio.speech.create(
                                    model="tts-1",
                                    voice=oai_voice,
                                    response_format="wav",
                                    input=clause_text
                                )
                                return oai_resp.content
                        except Exception as fb_err:
                            logger.error(f"Fallback TTS failed: {fb_err}")
                        return None
                    data = await resp.json()
                    audios = data.get("audios", [])
                    if not audios:
                        return None
                    return base64.b64decode(audios[0])

            # Launch async pre-fetch tasks for all clauses in parallel
            fetch_tasks = [asyncio.create_task(fetch_clause_audio(c)) for c in clauses]

            for task in fetch_tasks:
                audio_bytes = await task
                if not audio_bytes:
                    continue

                # Extract raw PCM bytes from WAV container
                raw_pcm = audio_bytes
                detected_rate = req_sample_rate
                num_channels = 1

                try:
                    with wave.open(io.BytesIO(audio_bytes), 'rb') as wav_file:
                        detected_rate = wav_file.getframerate()
                        num_channels = wav_file.getnchannels()
                        raw_pcm = wav_file.readframes(wav_file.getnframes())
                except Exception as wav_err:
                    logger.debug(f"Parsing WAV header failed (assuming raw PCM): {wav_err}")

                # Stream audio in 4KB PCM chunks
                chunk_size = 4096
                for i in range(0, len(raw_pcm), chunk_size):
                    chunk = raw_pcm[i : i + chunk_size]
                    yield TTSAudioRawFrame(
                        audio=chunk,
                        sample_rate=detected_rate,
                        num_channels=num_channels,
                    )

            yield TTSStoppedFrame()

        except Exception as e:
            logger.error(f"SarvamTTSService error: {e}")
            yield ErrorFrame(error=f"Sarvam TTS generation failed: {e}")
