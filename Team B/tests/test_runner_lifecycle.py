"""
Tests for Lifecycle Manager and State.
"""

import pytest

from app.events import EventBus
from app.pipeline.exceptions import InvalidExecutionStateError
from app.pipeline.execution_state import ExecutionState
from app.pipeline.lifecycle import PipelineLifecycleManager


@pytest.fixture
def lifecycle() -> PipelineLifecycleManager:
    return PipelineLifecycleManager(EventBus(), "session1", "exec1")


def test_initial_state(lifecycle: PipelineLifecycleManager) -> None:
    assert lifecycle.state == ExecutionState.CREATED


def test_happy_path(lifecycle: PipelineLifecycleManager) -> None:
    lifecycle.initialize()
    assert lifecycle.state == ExecutionState.INITIALIZED
    
    lifecycle.start()
    assert lifecycle.state == ExecutionState.RUNNING
    
    lifecycle.complete()
    assert lifecycle.state == ExecutionState.COMPLETED
    
    lifecycle.shutdown()
    assert lifecycle.state == ExecutionState.TERMINATED


def test_pause_resume(lifecycle: PipelineLifecycleManager) -> None:
    lifecycle.initialize()
    lifecycle.start()
    
    lifecycle.pause()
    assert lifecycle.state == ExecutionState.PAUSED
    
    # Starting from paused is valid
    lifecycle.start()
    assert lifecycle.state == ExecutionState.RUNNING
    
    lifecycle.pause()
    lifecycle.resume()
    assert lifecycle.state == ExecutionState.RUNNING


def test_cancellation(lifecycle: PipelineLifecycleManager) -> None:
    lifecycle.initialize()
    lifecycle.start()
    
    lifecycle.cancel()
    assert lifecycle.state == ExecutionState.CANCELLING
    
    lifecycle.mark_cancelled()
    assert lifecycle.state == ExecutionState.CANCELLED


def test_failure(lifecycle: PipelineLifecycleManager) -> None:
    lifecycle.initialize()
    lifecycle.start()
    
    lifecycle.fail(ValueError("Test error"))
    assert lifecycle.state == ExecutionState.FAILED


def test_invalid_transitions(lifecycle: PipelineLifecycleManager) -> None:
    with pytest.raises(InvalidExecutionStateError):
        lifecycle.start() # Cannot start from CREATED
        
    lifecycle.initialize()
    with pytest.raises(InvalidExecutionStateError):
        lifecycle.initialize() # Cannot init twice
