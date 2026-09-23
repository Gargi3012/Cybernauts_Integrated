"""
Tests for Pipeline Factory templates.
"""

from app.events import EventBus
from app.pipeline.factory import PipelineFactory


def test_create_voice_pipeline() -> None:
    bus = EventBus()
    builder = PipelineFactory.create_voice_pipeline(bus, "test-session")
    
    pipeline = builder.build()
    assert len(pipeline.processors) == 5
    
    pids = list(pipeline.processors.keys())
    assert set(pids) == {"transport_in", "stt", "llm", "tts", "transport_out"}


def test_create_text_pipeline() -> None:
    bus = EventBus()
    builder = PipelineFactory.create_text_pipeline(bus, "test-session")
    
    pipeline = builder.build()
    assert len(pipeline.processors) == 3
    assert "text_in" in pipeline.processors
