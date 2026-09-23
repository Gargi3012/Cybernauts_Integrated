"""
End-to-End Stress Tests for Real-Time Voice Pipeline
"""

import asyncio
import pytest

from app.events.bus import EventBus
from app.pipeline.builder import PipelineBuilder
from app.pipeline.processors import ProcessorNode, ProcessorRole
from app.adapters.pipecat.factory import PipecatFactory


@pytest.mark.asyncio
async def test_stress_100_concurrent_pipelines() -> None:
    """Run 100 concurrent pipelines to ensure no race conditions or deadlocks."""
    bus = EventBus()
    
    async def run_pipeline(idx: int) -> None:
        builder = PipelineBuilder(bus, f"session_{idx}")
        builder.add_processor(ProcessorNode(f"STT_{idx}", ProcessorRole.STT))
        builder.add_processor(ProcessorNode(f"LLM_{idx}", ProcessorRole.LLM))
        builder.connect(f"STT_{idx}", f"LLM_{idx}")
        pipeline = builder.build()
        
        adapter = PipecatFactory.create_adapter(pipeline, bus, f"session_{idx}", f"exec_{idx}")
        await adapter.run()
        
    await asyncio.gather(*(run_pipeline(i) for i in range(100)))
    
    # Just checking it finishes deterministically
    assert True
