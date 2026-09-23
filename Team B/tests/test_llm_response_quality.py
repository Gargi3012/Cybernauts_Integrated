"""
Quality check: generate real speech from a realistic LLM-style response
and save it so you can LISTEN and judge accuracy/naturalness yourself.

This is different from the latency tests — those measure SPEED.
This one measures QUALITY: does it sound right, is pronunciation
correct, does it handle punctuation/numbers/names naturally.

Run with:
    python -m tests.test_llm_response_quality
"""

import os
from elevenlabs.client import ElevenLabs
from dotenv import load_dotenv

load_dotenv()

# A realistic, full LLM assistant response — the kind Groq would actually
# generate in this project: conversational, with punctuation, a number,
# and a slightly technical term, to stress-test pronunciation.
SAMPLE_LLM_RESPONSE = (
    "Sure, I can help with that. Based on your account, you have 3 "
    "pending orders, and the fastest one should arrive by Thursday. "
    "Would you like me to send a tracking link, or check the other two as well?"
)


def generate_quality_sample():
    api_key = os.getenv("ELEVEN_LABS_API_KEY")
    voice_id = os.getenv("ELEVEN_LABS_VOICE_ID")

    assert api_key, "ELEVEN_LABS_API_KEY missing from .env"
    assert voice_id, "ELEVEN_LABS_VOICE_ID missing from .env"

    client = ElevenLabs(api_key=api_key)

    print(f"Generating speech for:\n\"{SAMPLE_LLM_RESPONSE}\"\n")

    audio = client.text_to_speech.convert(
        text=SAMPLE_LLM_RESPONSE,
        voice_id=voice_id,
        model_id="eleven_turbo_v2_5",
        output_format="mp3_44100_128",
    )

    audio_bytes = b"".join(chunk for chunk in audio if isinstance(chunk, bytes))

    output_path = "tests/llm_response_quality_sample.mp3"
    with open(output_path, "wb") as f:
        f.write(audio_bytes)

    print(f"Saved {len(audio_bytes)} bytes -> {output_path}")
    print("\nOpen this file and listen. Check specifically for:")
    print("  - Does '3 pending orders' sound natural (number pronunciation)?")
    print("  - Does the question at the end have natural rising intonation?")
    print("  - Any robotic artifacts, mispronunciations, or awkward pauses?")


if __name__ == "__main__":
    generate_quality_sample()