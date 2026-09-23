"""
Custom Pipecat TTS service for Chatterbox (local, CPU-based, no API).

There is no official pipecat.services.chatterbox — this wraps the
standalone chatterbox-tts package ourselves, following the same
structural pattern as Pipecat's built-in services (e.g. Piper).

CRITICAL: model.generate() is synchronous and CPU-blocking. Running it
directly inside the async pipeline would freeze the ENTIRE server, not
just this one call. We offload it to a background thread using
loop.run_in_executor() to keep the event loop responsive.

Place this file at: app/adapters/pipecat/chatterbox_tts_service.py
"""

import asyncio
import io
from typing import AsyncGenerator, Optional

import numpy as np
from loguru import logger

from pipecat.frames.frames import Frame, TTSAudioRawFrame, TTSStartedFrame, TTSStoppedFrame, ErrorFrame
from pipecat.services.tts_service import TTSService


class ChatterboxTTSService(TTSService):
    """Local, CPU-based TTS using Resemble AI's Chatterbox model."""

    def __init__(self, *, sample_rate: Optional[int] = None, **kwargs):
        super().__init__(sample_rate=sample_rate, **kwargs)
        self._model = None  # lazy-loaded on first use, not at startup

    def can_generate_metrics(self) -> bool:
        return True

    async def _ensure_model_loaded(self):
        if self._model is None:
            logger.info("Loading Chatterbox model (first call only, this is slow)...")
            loop = asyncio.get_event_loop()
            # Loading the model is also blocking — run it in a thread too
            self._model = await loop.run_in_executor(None, self._load_model)
            logger.info("Chatterbox model loaded.")

    def _load_model(self):
        from chatterbox.tts import ChatterboxTTS
        return ChatterboxTTS.from_pretrained(device="cpu")

    def _generate_sync(self, text: str):
        """Runs in a background thread — this is the blocking CPU work."""
        wav = self._model.generate(text)
        # wav is a torch tensor; convert to raw 16-bit PCM bytes for Pipecat
        audio_np = wav.squeeze().cpu().numpy()
        audio_int16 = (audio_np * 32767).astype(np.int16)
        return audio_int16.tobytes(), self._model.sr

    async def run_tts(self, text: str) -> AsyncGenerator[Frame, None]:
        try:
            await self._ensure_model_loaded()

            yield TTSStartedFrame()

            logger.info(f"ChatterboxTTSService: generating (CPU, will be slow) [{text}]")
            loop = asyncio.get_event_loop()
            audio_bytes, model_sample_rate = await loop.run_in_executor(
                None, self._generate_sync, text
            )

            # Chunk the audio so it streams progressively rather than
            # arriving as one giant frame
            chunk_size = 4096
            for i in range(0, len(audio_bytes), chunk_size):
                chunk = audio_bytes[i:i + chunk_size]
                yield TTSAudioRawFrame(
                    audio=chunk,
                    sample_rate=model_sample_rate,
                    num_channels=1,
                )

            yield TTSStoppedFrame()

        except Exception as e:
            logger.error(f"ChatterboxTTSService error: {e}")
            yield ErrorFrame(error=f"Chatterbox generation failed: {e}")