"""
Tests for Context and Execution Isolation.
"""

import asyncio
import pytest

from app.events.bus import EventBus
from app.pipeline.builder import PipelineBuilder
from app.pipeline.processors import ProcessorNode, ProcessorRole


@pytest.mark.asyncio
async def test_cancellation_isolation() -> None:
    """Verify cancelling one pipeline does not affect others."""
    bus = EventBus()
    
    from app.pipeline.runner import PipelineRunner
    from app.pipeline.executor import AbstractProcessor
    
    class MockProcessor(AbstractProcessor):
        async def before_execute(self, context, node):
            pass
        async def execute(self, context, node):
            return "ok"
        async def after_execute(self, context, node):
            pass
            
    # Setup P1
    b1 = PipelineBuilder(bus, "s1")
    b1.add_processor(ProcessorNode("STT1", ProcessorRole.STT))
    p1 = b1.build()
    runner1 = PipelineRunner(p1, {"STT1": MockProcessor()}, bus, "s1")
    
    # Setup P2
    b2 = PipelineBuilder(bus, "s2")
    b2.add_processor(ProcessorNode("STT2", ProcessorRole.STT))
    p2 = b2.build()
    runner2 = PipelineRunner(p2, {"STT2": MockProcessor()}, bus, "s2")
    
    t1 = asyncio.create_task(runner1.run())
    t2 = asyncio.create_task(runner2.run())
    
    await asyncio.sleep(0.01)
    
    # Cancel P1 only
    runner1.cancel()
    
    await t1
    await t2
    
    assert runner1.context.cancellation_token is not runner2.context.cancellation_token
    assert runner1.context.metrics_collector is not runner2.context.metrics_collector
