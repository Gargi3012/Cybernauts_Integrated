"""
Config loader for Pillar 4 (TTS & Interruption).

Deliberately matches the naming convention already used in the
target repo's app/config.py, so this module can be dropped in
later with zero renaming.
"""
import os
from dotenv import load_dotenv

load_dotenv()

ELEVEN_LABS_API_KEY = os.getenv("ELEVEN_LABS_API_KEY")
ELEVEN_LABS_VOICE_ID = os.getenv("ELEVEN_LABS_VOICE_ID")

# Tunable defaults, proven via your own benchmarking (0.32s TTFB at level 4)
DEFAULT_TTS_MODEL = "eleven_turbo_v2_5"
DEFAULT_LATENCY_OPT = 4
DEFAULT_STABILITY = 0.5
DEFAULT_SIMILARITY_BOOST = 0.8


def validate_config() -> None:
    """Fail loudly and early if required keys are missing."""
    if not ELEVEN_LABS_API_KEY:
        raise ValueError(
            "ELEVEN_LABS_API_KEY is not set. Add it to your .env file."
        )
    if not ELEVEN_LABS_VOICE_ID:
        raise ValueError(
            "ELEVEN_LABS_VOICE_ID is not set. Add it to your .env file."
        )