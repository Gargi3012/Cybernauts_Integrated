"""
Execution state definitions.
"""
from enum import Enum


class ExecutionState(str, Enum):
    """Pipeline and Processor execution states."""
    CREATED = "created"
    INITIALIZED = "initialized"
    RUNNING = "running"
    PAUSED = "paused"
    RESUMED = "resumed"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"
    CLEANUP = "cleanup"
    TERMINATED = "terminated"
