"""
Tests for Pipecat adapter package (Utils, Factory, Lifecycle).
"""

import pytest

from app.events import EventBus
from app.pipeline.builder import PipelineBuilder
from app.pipeline.processors import ProcessorNode, ProcessorRole
from app.adapters.pipecat import (
    extract_pipecat_metadata,
    PipecatFactory,
    PipecatLifecycleManager,
    MockWebSocketTransport,
    RuntimeSynchronizationError
)
from app.adapters.pipecat.processors import MockPipecatProcessor


def test_extract_pipecat_metadata() -> None:
    proc = MockPipecatProcessor("TestProc")
    meta = extract_pipecat_metadata(proc)
    assert meta["name"] == "TestProc"


def test_pipecat_factory() -> None:
    bus = EventBus()
    builder = PipelineBuilder(bus, "session1")
    builder.add_processor(ProcessorNode("STT", ProcessorRole.STT))
    pipeline = builder.build()
    
    transport = MockWebSocketTransport()
    adapter = PipecatFactory.create_adapter(pipeline, bus, "session1", "exec1", transport)
    
    assert adapter.pipeline == pipeline
    assert adapter.session_id == "session1"
    assert adapter.execution_id == "exec1"
    assert adapter.transport == transport


@pytest.mark.asyncio
async def test_lifecycle_manager_success() -> None:
    class MockTask:
        started = False
        stopped = False
        waited = False
        
        async def start(self) -> None:
            self.started = True
        
        async def stop(self) -> None:
            self.stopped = True
            
        async def wait(self) -> None:
            self.waited = True
            
    task = MockTask()
    lifecycle = PipecatLifecycleManager(task, "session1")
    
    await lifecycle.start()
    assert task.started
    
    await lifecycle.stop()
    assert task.stopped
    
    await lifecycle.wait_until_done()
    assert task.waited


@pytest.mark.asyncio
async def test_lifecycle_manager_errors() -> None:
    class FailingTask:
        async def start(self) -> None:
            raise ValueError("Start failed")
        
        async def stop(self) -> None:
            raise ValueError("Stop failed")
            
        async def wait(self) -> None:
            raise ValueError("Wait failed")
            
    task = FailingTask()
    lifecycle = PipecatLifecycleManager(task, "session1")
    
    with pytest.raises(RuntimeSynchronizationError, match="Failed to start Pipecat task: Start failed"):
        await lifecycle.start()
        
    with pytest.raises(RuntimeSynchronizationError, match="Failed to stop Pipecat task: Stop failed"):
        await lifecycle.stop()
        
    with pytest.raises(RuntimeSynchronizationError, match="Error while waiting for Pipecat task: Wait failed"):
        await lifecycle.wait_until_done()
