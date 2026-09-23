"""
Pipeline Builder Package — Assembles immutable execution graphs.
"""

from .builder import PipelineBuilder
from .exceptions import (
    CircularDependencyError,
    DuplicateProcessorError,
    EmptyPipelineError,
    InvalidPipelineError,
    PipelineError,
    ProcessorNotFoundError,
    PipelineExecutionError,
    ProcessorExecutionError,
    PipelineCancelledError,
    PipelinePausedError,
    InvalidExecutionStateError,
    ExecutionTimeoutError,
)
from .factory import PipelineFactory
from .graph import PipelineGraph
from .models import Pipeline
from .processors import ProcessorNode, ProcessorRole
from .serializer import PipelineSerializer
from .validators import validate_pipeline
from .runner import PipelineRunner
from .executor import AbstractProcessor
from .context import ExecutionContext
from .execution_state import ExecutionState
from .cancellation import CancellationToken
from .metrics import MetricsCollector

__all__ = [
    "PipelineBuilder",
    "PipelineFactory",
    "PipelineGraph",
    "Pipeline",
    "ProcessorNode",
    "ProcessorRole",
    "PipelineSerializer",
    "validate_pipeline",
    "PipelineError",
    "InvalidPipelineError",
    "DuplicateProcessorError",
    "ProcessorNotFoundError",
    "CircularDependencyError",
    "EmptyPipelineError",
    "PipelineExecutionError",
    "ProcessorExecutionError",
    "PipelineCancelledError",
    "PipelinePausedError",
    "InvalidExecutionStateError",
    "ExecutionTimeoutError",
    "PipelineRunner",
    "AbstractProcessor",
    "ExecutionContext",
    "ExecutionState",
    "CancellationToken",
    "MetricsCollector",
]
