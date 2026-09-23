"""
Tests for Pipecat Pipeline Mapper.
"""

import pytest

from app.events import EventBus
from app.pipeline.builder import PipelineBuilder
from app.pipeline.models import Pipeline
from app.pipeline.processors import ProcessorNode, ProcessorRole
from app.adapters.pipecat import PipecatPipelineMapper
from app.adapters.pipecat.exceptions import PipelineConversionError


from unittest.mock import patch

@patch("app.adapters.pipecat.processors._create_real_processor", side_effect=ImportError("mocked"))
def test_mapper_success(mock_create) -> None:
    bus = EventBus()
    builder = PipelineBuilder(bus, "session1")
    builder.add_processor(ProcessorNode("STT", ProcessorRole.STT))
    builder.add_processor(ProcessorNode("LLM", ProcessorRole.LLM))
    builder.add_processor(ProcessorNode("TTS", ProcessorRole.TTS))
    builder.connect("STT", "LLM")
    builder.connect("LLM", "TTS")
    pipeline = builder.build()
    
    adapters = PipecatPipelineMapper.map_pipeline(pipeline)
    
    assert len(adapters) == 3
    assert adapters[0].name == "STT"
    assert adapters[0].get_processor().name == "MockSTT"
    assert adapters[1].name == "LLM"
    assert adapters[1].get_processor().name == "MockLLM"
    assert adapters[2].name == "TTS"
    assert adapters[2].get_processor().name == "MockTTS"


def test_mapper_missing_processor(monkeypatch: pytest.MonkeyPatch) -> None:
    pipeline = Pipeline(
        pipeline_id="pipe1",
        processors={},
        graph={}
    )
    
    # Mock scheduler to return a missing processor ID
    monkeypatch.setattr("app.adapters.pipecat.mapper.PipelineScheduler.get_execution_order", lambda self: ["Missing"])
    
    with pytest.raises(PipelineConversionError) as exc_info:
        PipecatPipelineMapper.map_pipeline(pipeline)
        
    assert "Processor Missing not found in pipeline" in str(exc_info.value)
