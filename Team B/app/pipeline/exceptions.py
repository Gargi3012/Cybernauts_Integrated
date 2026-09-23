"""
Pipeline custom exceptions.
"""

class PipelineError(Exception):
    """Base exception for all pipeline errors."""


class InvalidPipelineError(PipelineError):
    """Raised when a pipeline definition fails validation."""
    
    def __init__(self, message: str) -> None:
        super().__init__(f"Invalid Pipeline: {message}")


class DuplicateProcessorError(InvalidPipelineError):
    """Raised when trying to add a processor with an ID that already exists."""


class ProcessorNotFoundError(PipelineError):
    """Raised when trying to reference a processor that doesn't exist."""
    
    def __init__(self, processor_id: str) -> None:
        self.processor_id = processor_id
        super().__init__(f"Processor '{processor_id}' not found in pipeline.")


class CircularDependencyError(InvalidPipelineError):
    """Raised when a cycle is detected in the pipeline graph."""


class EmptyPipelineError(InvalidPipelineError):
    """Raised when trying to build an empty pipeline."""


# ──────────────────────────────────────────────────────────────────────
# Runner Exceptions
# ──────────────────────────────────────────────────────────────────────

class PipelineExecutionError(PipelineError):
    """Base error for execution failures."""

class ProcessorExecutionError(PipelineExecutionError):
    """Raised when a specific processor fails."""

class PipelineCancelledError(PipelineExecutionError):
    """Raised when execution is cancelled."""

class PipelinePausedError(PipelineExecutionError):
    """Raised when operations are attempted on a paused pipeline that don't allow it."""

class InvalidExecutionStateError(PipelineExecutionError):
    """Raised when an operation is invalid for the current state."""

class ExecutionTimeoutError(PipelineExecutionError):
    """Raised when execution times out."""
