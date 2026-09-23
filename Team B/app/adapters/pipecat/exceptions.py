"""
Pipecat adapter exceptions.
"""

class PipecatAdapterError(Exception):
    """Base exception for Pipecat adapter errors."""

class ProcessorMappingError(PipecatAdapterError):
    """Raised when a processor cannot be mapped to Pipecat."""

class TransportMappingError(PipecatAdapterError):
    """Raised when a transport cannot be mapped."""

class PipelineConversionError(PipecatAdapterError):
    """Raised when pipeline conversion fails."""

class RuntimeSynchronizationError(PipecatAdapterError):
    """Raised when synchronization with Pipecat runtime fails."""
