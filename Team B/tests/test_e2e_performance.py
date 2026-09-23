"""
End-to-End Performance Benchmark
"""

import time
import pytest

from app.events.bus import EventBus
from app.pipeline.builder import PipelineBuilder
from app.pipeline.processors import ProcessorNode, ProcessorRole
from app.adapters.pipecat.factory import PipecatFactory


from unittest.mock import patch


@patch("app.adapters.pipecat.adapter._build_real_pipeline_task", side_effect=ImportError("mocked"))
@pytest.mark.asyncio
async def test_performance_pipeline_construction_and_execution(mock_build) -> None:
    bus = EventBus()
    
    start_time = time.perf_counter()
    
    builder = PipelineBuilder(bus, "perf-session")
    for i in range(10):
        builder.add_processor(ProcessorNode(f"Node_{i}", ProcessorRole.CUSTOM))
        if i > 0:
            builder.connect(f"Node_{i-1}", f"Node_{i}")
            
    pipeline = builder.build()
    build_time = time.perf_counter() - start_time
    
    start_run = time.perf_counter()
    adapter = PipecatFactory.create_adapter(pipeline, bus, "perf-session", "perf-exec")
    await adapter.run()
    run_time = time.perf_counter() - start_run
    
    # Assertions are mainly to log data, but we assert they finish fast
    assert build_time < 0.1
    assert run_time < 0.5
