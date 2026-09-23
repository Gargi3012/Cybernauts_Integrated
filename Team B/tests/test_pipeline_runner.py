"""
Integration tests for PipelineRunner.
"""

import asyncio
from typing import Any

import pytest

from app.events import EventBus
from app.pipeline.builder import PipelineBuilder
from app.pipeline.context import ExecutionContext
from app.pipeline.exceptions import PipelineCancelledError, PipelineExecutionError
from app.pipeline.execution_state import ExecutionState
from app.pipeline.executor import AbstractProcessor
from app.pipeline.processors import ProcessorNode, ProcessorRole
from app.pipeline.runner import PipelineRunner


class DummyProcessor(AbstractProcessor):
    def __init__(self, name: str, delay: float = 0.0) -> None:
        self.name = name
        self.delay = delay
        self.executed = False

    async def before_execute(self, context: ExecutionContext, node: ProcessorNode) -> None:
        pass

    async def execute(self, context: ExecutionContext, node: ProcessorNode) -> Any:
        if self.delay > 0:
            await asyncio.sleep(self.delay)
        self.executed = True
        return f"{self.name}_done"

    async def after_execute(self, context: ExecutionContext, node: ProcessorNode) -> None:
        pass


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.mark.asyncio
async def test_successful_runner_execution(bus: EventBus) -> None:
    builder = PipelineBuilder(bus, "test-session")
    builder.add_processor(ProcessorNode("A", ProcessorRole.TRANSPORT_INPUT))
    builder.add_processor(ProcessorNode("B", ProcessorRole.TRANSPORT_OUTPUT))
    builder.connect("A", "B")
    pipeline = builder.build()
    
    pA = DummyProcessor("A")
    pB = DummyProcessor("B")
    processors = {"A": pA, "B": pB}
    
    runner = PipelineRunner(pipeline, processors, bus, "test-session")
    
    await runner.run()
    
    assert runner.lifecycle.state == ExecutionState.TERMINATED
    assert pA.executed
    assert pB.executed
    
    metrics = runner.get_metrics()
    assert metrics["completed_processors"] == 2
    assert metrics["failed_processors"] == 0


@pytest.mark.asyncio
async def test_missing_processor_implementation(bus: EventBus) -> None:
    builder = PipelineBuilder(bus, "test-session")
    builder.add_processor(ProcessorNode("A", ProcessorRole.TRANSPORT_INPUT))
    pipeline = builder.build()
    
    # Empty implementations dict
    runner = PipelineRunner(pipeline, {}, bus, "test-session")
    
    with pytest.raises(PipelineExecutionError, match="No processor implementation provided for ID: A"):
        await runner.run()
        
    assert runner.lifecycle.state == ExecutionState.TERMINATED # Graceful cleanup


@pytest.mark.asyncio
async def test_cancellation_during_execution(bus: EventBus) -> None:
    builder = PipelineBuilder(bus, "test-session")
    builder.add_processor(ProcessorNode("A", ProcessorRole.TRANSPORT_INPUT))
    builder.add_processor(ProcessorNode("B", ProcessorRole.TRANSPORT_OUTPUT))
    builder.connect("A", "B")
    pipeline = builder.build()
    
    # A takes 0.2s, B takes 0s
    pA = DummyProcessor("A", delay=0.2)
    pB = DummyProcessor("B")
    processors = {"A": pA, "B": pB}
    
    runner = PipelineRunner(pipeline, processors, bus, "test-session")
    
    run_task = asyncio.create_task(runner.run())
    
    await asyncio.sleep(0.05) # Yield to let A start
    runner.cancel()
    
    with pytest.raises(PipelineCancelledError):
        await run_task
        
    # A should finish (cancellation is cooperative and we didn't check inside A's sleep)
    # But B should NEVER run because runner checks token between processors.
    assert pA.executed
    assert not pB.executed


@pytest.mark.asyncio
async def test_pause_and_resume(bus: EventBus) -> None:
    builder = PipelineBuilder(bus, "test-session")
    builder.add_processor(ProcessorNode("A", ProcessorRole.TRANSPORT_INPUT))
    builder.add_processor(ProcessorNode("B", ProcessorRole.TRANSPORT_OUTPUT))
    builder.connect("A", "B")
    pipeline = builder.build()
    
    pA = DummyProcessor("A", delay=0.1)
    pB = DummyProcessor("B", delay=0.1)
    processors = {"A": pA, "B": pB}
    
    runner = PipelineRunner(pipeline, processors, bus, "test-session")
    
    run_task = asyncio.create_task(runner.run())
    
    await asyncio.sleep(0.05)
    runner.pause()
    assert runner.lifecycle.state == ExecutionState.PAUSED
    
    # Wait a bit to ensure it is paused
    await asyncio.sleep(0.2)
    assert pA.executed # A finishes its 0.1s sleep
    assert not pB.executed # B should not start while paused
    
    runner.resume()
    assert runner.lifecycle.state == ExecutionState.RUNNING
    
    await run_task
    assert pB.executed
