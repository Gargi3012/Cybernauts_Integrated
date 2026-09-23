"""
Tests for Processor Executor.
"""

import pytest

from app.events import EventBus
from app.pipeline.context import ExecutionContext
from app.pipeline.exceptions import ProcessorExecutionError, PipelineCancelledError
from app.pipeline.executor import AbstractProcessor, DefaultProcessorExecutor
from app.pipeline.processors import ProcessorNode, ProcessorRole


class MockProcessor(AbstractProcessor):
    def __init__(self) -> None:
        self.calls = []
        self.should_fail = False

    async def before_execute(self, context: ExecutionContext, node: ProcessorNode) -> None:
        self.calls.append("before")
        
    async def execute(self, context: ExecutionContext, node: ProcessorNode) -> str:
        if self.should_fail:
            raise ValueError("Processor failure")
        self.calls.append("execute")
        return "result"
        
    async def after_execute(self, context: ExecutionContext, node: ProcessorNode) -> None:
        self.calls.append("after")


@pytest.fixture
def bus() -> EventBus:
    return EventBus()

@pytest.fixture
def context() -> ExecutionContext:
    return ExecutionContext(pipeline_id="pipe1", session_id="session1")

@pytest.fixture
def node() -> ProcessorNode:
    return ProcessorNode("p1", ProcessorRole.LLM)


@pytest.mark.asyncio
async def test_successful_execution(bus: EventBus, context: ExecutionContext, node: ProcessorNode) -> None:
    executor = DefaultProcessorExecutor(bus)
    proc = MockProcessor()
    
    result = await executor.run(proc, node, context)
    
    assert result == "result"
    assert proc.calls == ["before", "execute", "after"]
    metrics = context.metrics_collector.get_metrics()
    assert metrics["completed_processors"] == 1
    assert metrics["failed_processors"] == 0


@pytest.mark.asyncio
async def test_failed_execution(bus: EventBus, context: ExecutionContext, node: ProcessorNode) -> None:
    executor = DefaultProcessorExecutor(bus)
    proc = MockProcessor()
    proc.should_fail = True
    
    with pytest.raises(ProcessorExecutionError, match="Processor failure"):
        await executor.run(proc, node, context)
        
    assert proc.calls == ["before"] # execute raised before appending
    metrics = context.metrics_collector.get_metrics()
    assert metrics["completed_processors"] == 0
    assert metrics["failed_processors"] == 1


@pytest.mark.asyncio
async def test_cancelled_execution_before_run(bus: EventBus, context: ExecutionContext, node: ProcessorNode) -> None:
    executor = DefaultProcessorExecutor(bus)
    proc = MockProcessor()
    
    context.cancellation_token.cancel()
    
    with pytest.raises(PipelineCancelledError):
        await executor.run(proc, node, context)
        
    assert proc.calls == []
    metrics = context.metrics_collector.get_metrics()
    assert metrics["failed_processors"] == 1
