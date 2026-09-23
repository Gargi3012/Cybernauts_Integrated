"""
Lifecycle manager for the pipeline runner.
"""

import threading
from loguru import logger

from app.events import EventBus
from app.events.event_types import (
    PipelineCancelled,
    PipelineCompleted,
    PipelineFailed,
    PipelineInitialized,
    PipelinePaused,
    PipelineResumed,
    PipelineShutdown,
    PipelineStarted,
)
from app.pipeline.execution_state import ExecutionState
from app.pipeline.exceptions import InvalidExecutionStateError


class PipelineLifecycleManager:
    """Manages the lifecycle state machine of a pipeline execution."""

    def __init__(self, event_bus: EventBus, session_id: str, execution_id: str) -> None:
        self._bus = event_bus
        self._session_id = session_id
        self._execution_id = execution_id
        self._state = ExecutionState.CREATED
        self._lock = threading.Lock()

    @property
    def state(self) -> ExecutionState:
        with self._lock:
            return self._state

    def initialize(self) -> None:
        with self._lock:
            if self._state != ExecutionState.CREATED:
                raise InvalidExecutionStateError(f"Cannot initialize from state {self._state.value}")
            self._state = ExecutionState.INITIALIZED
            
        self._bus.publish_sync(PipelineInitialized(session_id=self._session_id, payload={"execution_id": self._execution_id}))
        logger.bind(session_id=self._session_id, execution_id=self._execution_id).info("Pipeline Initialized")

    def start(self) -> None:
        with self._lock:
            if self._state not in (ExecutionState.INITIALIZED, ExecutionState.PAUSED):
                raise InvalidExecutionStateError(f"Cannot start from state {self._state.value}")
            self._state = ExecutionState.RUNNING
            
        self._bus.publish_sync(PipelineStarted(session_id=self._session_id, payload={"execution_id": self._execution_id}))
        logger.bind(session_id=self._session_id, execution_id=self._execution_id).info("Pipeline Started")

    def pause(self) -> None:
        with self._lock:
            if self._state != ExecutionState.RUNNING:
                return # Idempotent or ignore
            self._state = ExecutionState.PAUSED
            
        self._bus.publish_sync(PipelinePaused(session_id=self._session_id, payload={"execution_id": self._execution_id}))
        logger.bind(session_id=self._session_id, execution_id=self._execution_id).info("Pipeline Paused")

    def resume(self) -> None:
        with self._lock:
            if self._state != ExecutionState.PAUSED:
                return
            self._state = ExecutionState.RUNNING
            
        self._bus.publish_sync(PipelineResumed(session_id=self._session_id, payload={"execution_id": self._execution_id}))
        logger.bind(session_id=self._session_id, execution_id=self._execution_id).info("Pipeline Resumed")

    def cancel(self) -> None:
        with self._lock:
            if self._state in (ExecutionState.CANCELLED, ExecutionState.COMPLETED, ExecutionState.FAILED, ExecutionState.TERMINATED):
                return
            self._state = ExecutionState.CANCELLING
            
        logger.bind(session_id=self._session_id, execution_id=self._execution_id).info("Pipeline Cancelling")

    def mark_cancelled(self) -> None:
        with self._lock:
            self._state = ExecutionState.CANCELLED
            
        self._bus.publish_sync(PipelineCancelled(session_id=self._session_id, payload={"execution_id": self._execution_id}))
        logger.bind(session_id=self._session_id, execution_id=self._execution_id).info("Pipeline Cancelled")

    def complete(self) -> None:
        with self._lock:
            if self._state in (ExecutionState.CANCELLING, ExecutionState.CANCELLED, ExecutionState.FAILED):
                return
            self._state = ExecutionState.COMPLETED
            
        self._bus.publish_sync(PipelineCompleted(session_id=self._session_id, payload={"execution_id": self._execution_id}))
        logger.bind(session_id=self._session_id, execution_id=self._execution_id).info("Pipeline Completed")

    def fail(self, error: Exception) -> None:
        with self._lock:
            self._state = ExecutionState.FAILED
            
        self._bus.publish_sync(PipelineFailed(session_id=self._session_id, payload={"execution_id": self._execution_id, "error": str(error)}))
        logger.bind(session_id=self._session_id, execution_id=self._execution_id).error(f"Pipeline Failed: {error}")

    def shutdown(self) -> None:
        with self._lock:
            if self._state == ExecutionState.TERMINATED:
                return
            self._state = ExecutionState.TERMINATED
            
        self._bus.publish_sync(PipelineShutdown(session_id=self._session_id, payload={"execution_id": self._execution_id}))
        logger.bind(session_id=self._session_id, execution_id=self._execution_id).info("Pipeline Shutdown")
