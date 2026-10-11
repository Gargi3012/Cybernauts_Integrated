"""
Instant Audio Greeting Service for Zero-Lag Telecom Pickup.

Pre-loads static 8kHz mu-law audio greetings for all 4 canonical personas (Shreya, Ritu, Ratan, Manan).
Streams audio directly over Plivo WebSocket in the first 50ms of call connection,
allowing the rest of the Pipecat pipeline, Deepgram STT, Silero VAD, and LLM to warm up
in parallel during the 3.5s greeting playback.
"""

import asyncio
import base64
import json
import os
from typing import Dict, Optional, Any
from loguru import logger

# Base directory for greetings
STATIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "static", "audio", "greetings"))

# In-memory RAM cache for pre-rendered mu-law bytes: key -> bytes
_ULAW_RAM_CACHE: Dict[str, bytes] = {}

# Active greeting streaming tasks: stream_id -> asyncio.Task
_ACTIVE_GREETING_TASKS: Dict[str, asyncio.Task] = {}


def preload_static_greetings() -> None:
    """Pre-load all static .ulaw greeting files into RAM for 0.00ms diskless access."""
    if not os.path.exists(STATIC_DIR):
        logger.warning(f"Static greetings directory not found at {STATIC_DIR}")
        return

    loaded = 0
    for filename in os.listdir(STATIC_DIR):
        if filename.endswith(".ulaw"):
            path = os.path.join(STATIC_DIR, filename)
            try:
                with open(path, "rb") as f:
                    data = f.read()
                    name_key = os.path.splitext(filename)[0]
                    _ULAW_RAM_CACHE[name_key] = data
                    loaded += 1
            except Exception as e:
                logger.warning(f"Failed to load greeting file {path}: {e}")

    logger.info(f"Loaded {loaded} static persona greeting audio files into RAM cache.")


def get_greeting_ulaw_bytes(
    persona_id: str = "shreya",
    greeting_text: str = "",
    company_context: Optional[Any] = None,
) -> tuple[bytes, str]:
    """
    Retrieve 8kHz mu-law audio bytes for the given persona and context.
    
    Priority:
    1. Memory cache (_TTS_AUDIO_CACHE) from pre-warming (ring-time synthesis)
    2. Static pre-rendered .ulaw file for persona variant (outbound vs default)
    3. Static pre-rendered .ulaw file for shreya_default as fallback
    """
    clean_p = (persona_id or "shreya").strip().lower()
    variant = "outbound" if company_context else "default"
    asset_key = f"{clean_p}_{variant}"

    # 1. Check if ring-time pre-warming synthesized custom audio in _TTS_AUDIO_CACHE
    from app.adapters.pipecat.sarvam_tts_service import _TTS_AUDIO_CACHE
    from app.services.persona_registry import get_persona
    import audioop

    p_obj = get_persona(clean_p)
    if greeting_text and greeting_text.strip():
        # Check custom cache keys
        custom_key_8k = f"{p_obj.voice}:{p_obj.model}:8000:{greeting_text.strip()}"
        custom_key_gen = f"{p_obj.voice}:{p_obj.model}:{greeting_text.strip()}"
        cached_entry = _TTS_AUDIO_CACHE.get(custom_key_8k) or _TTS_AUDIO_CACHE.get(custom_key_gen)
        if cached_entry:
            pcm_bytes, rate, channels = cached_entry
            try:
                # Convert 16-bit PCM to 8kHz mu-law
                ulaw_data = audioop.lin2ulaw(pcm_bytes, 2)
                logger.info(f"[INSTANT_GREETING] Using ring-warmed dynamic custom audio ({len(ulaw_data)} bytes) for {clean_p}")
                return ulaw_data, "dynamic_cache"
            except Exception as e:
                logger.warning(f"[INSTANT_GREETING] Error converting PCM to mu-law: {e}")

    # 2. Check RAM cache for static asset
    if asset_key in _ULAW_RAM_CACHE:
        return _ULAW_RAM_CACHE[asset_key], f"static_ram_{asset_key}"

    # 3. Fallback to reading from disk if not yet in RAM
    disk_path = os.path.join(STATIC_DIR, f"{asset_key}.ulaw")
    if os.path.exists(disk_path):
        try:
            with open(disk_path, "rb") as f:
                data = f.read()
                _ULAW_RAM_CACHE[asset_key] = data
                return data, f"static_disk_{asset_key}"
        except Exception:
            pass

    # 4. Fallback default
    fallback_key = "shreya_default"
    if fallback_key in _ULAW_RAM_CACHE:
        return _ULAW_RAM_CACHE[fallback_key], "fallback_shreya"

    fb_path = os.path.join(STATIC_DIR, f"{fallback_key}.ulaw")
    if os.path.exists(fb_path):
        with open(fb_path, "rb") as f:
            data = f.read()
            _ULAW_RAM_CACHE[fallback_key] = data
            return data, "fallback_shreya_disk"

    return b"", "none"


async def play_instant_greeting(
    websocket: Any,
    stream_sid: str,
    persona_id: str = "shreya",
    greeting_text: str = "",
    company_context: Optional[Any] = None,
) -> bool:
    """
    Stream greeting audio to Plivo WebSocket immediately upon call connection (<50ms).
    Sends 640-byte chunks (80ms of 8kHz audio) every 60ms to fill carrier jitter buffer smoothly.
    """
    ulaw_bytes, source = get_greeting_ulaw_bytes(persona_id, greeting_text, company_context)
    if not ulaw_bytes:
        logger.warning(f"[INSTANT_GREETING] No greeting audio available for stream {stream_sid}")
        return False

    total_len = len(ulaw_bytes)
    duration_s = total_len / 8000.0
    logger.info(
        f"[INSTANT_GREETING] Starting zero-lag greeting blast | stream_sid={stream_sid} | "
        f"persona={persona_id} | source={source} | bytes={total_len} | duration={duration_s:.2f}s"
    )

    chunk_size = 640  # 80ms @ 8000Hz mono mu-law
    try:
        # Send initial 2 chunks immediately to pre-fill carrier jitter buffer
        initial_burst = min(1280, total_len)
        first_payload = base64.b64encode(ulaw_bytes[:initial_burst]).decode("utf-8")
        msg = json.dumps({
            "event": "playAudio",
            "media": {
                "contentType": "audio/x-mulaw",
                "sampleRate": 8000,
                "payload": first_payload,
            },
            "streamId": stream_sid,
        })
        await websocket.send_text(msg)

        # Stream the remaining audio smoothly
        for i in range(initial_burst, total_len, chunk_size):
            chunk = ulaw_bytes[i : i + chunk_size]
            payload = base64.b64encode(chunk).decode("utf-8")
            chunk_msg = json.dumps({
                "event": "playAudio",
                "media": {
                    "contentType": "audio/x-mulaw",
                    "sampleRate": 8000,
                    "payload": payload,
                },
                "streamId": stream_sid,
            })
            await websocket.send_text(chunk_msg)
            # Sleep 60ms per 80ms chunk (slightly faster than realtime ensures zero underrun)
            await asyncio.sleep(0.060)

        logger.info(f"[INSTANT_GREETING] Completed zero-lag greeting blast for stream {stream_sid}")
        return True

    except asyncio.CancelledError:
        logger.info(f"[INSTANT_GREETING] Greeting interrupted / cancelled for stream {stream_sid}")
        try:
            # Send clearAudio to Plivo if interrupted by caller speech
            clear_msg = json.dumps({"event": "clearAudio", "streamId": stream_sid})
            await websocket.send_text(clear_msg)
        except Exception:
            pass
        return False
    except Exception as e:
        logger.warning(f"[INSTANT_GREETING] Error during audio streaming to {stream_sid}: {e}")
        return False
    finally:
        _ACTIVE_GREETING_TASKS.pop(stream_sid, None)


def register_greeting_task(stream_sid: str, task: asyncio.Task) -> None:
    """Register an active greeting streaming task for interruption handling."""
    _ACTIVE_GREETING_TASKS[stream_sid] = task


def cancel_greeting_task(stream_sid: str) -> None:
    """Cancel an active greeting task if the caller speaks early."""
    task = _ACTIVE_GREETING_TASKS.get(stream_sid)
    if task and not task.done():
        task.cancel()
