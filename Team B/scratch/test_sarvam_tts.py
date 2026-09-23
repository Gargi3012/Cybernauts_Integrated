
import asyncio
from app.adapters.pipecat.sarvam_tts_service import SarvamTTSService
from app.config import SARVAM_API_KEY

async def test_sarvam():
    tts = SarvamTTSService(api_key=SARVAM_API_KEY, voice="shreya", model="bulbul:v3")
    frames = []
    async for frame in tts.run_tts("Hello m Cybernauts se Shreya baat kar rahi hu. Kaise help kar sakti hu?"):
        frames.append(frame)
    print(f"Sarvam TTS Shreya Test SUCCESS! Received {len(frames)} frames.")

if __name__ == "__main__":
    asyncio.run(test_sarvam())
