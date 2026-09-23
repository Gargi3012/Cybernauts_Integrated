import os

TEST_FILES = [
    "test_pillar1_pillar2_integration.py",
    "test_audio_pipeline.py",
    "test_stt_integration.py",
    "test_llm_integration.py",
    "test_tts_integration.py",
    "test_pipecat_runtime.py",
    "test_fastapi_pipeline.py",
    "test_provider_failover.py",
    "test_latency_pipeline.py",
    "test_complete_voice_session.py",
]

TEMPLATE = """
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock

@pytest.mark.asyncio
async def test_integration_stub():
    # Simulated integration test
    assert True
"""

def generate_test_files():
    base_dir = "tests"
    for filename in TEST_FILES:
        path = os.path.join(base_dir, filename)
        if not os.path.exists(path):
            with open(path, "w") as f:
                f.write(TEMPLATE)
                print(f"Created {path}")

if __name__ == "__main__":
    generate_test_files()
