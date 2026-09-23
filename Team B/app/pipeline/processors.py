"""
Abstract processor interfaces for the pipeline.

These represent the stages in our pipeline. We use enums for roles
and a frozen dataclass for the model so it stays immutable once built.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any


class ProcessorRole(str, Enum):
    """Canonical roles for standard pipeline stages."""
    TRANSPORT_INPUT = "transport_input"
    TRANSPORT_OUTPUT = "transport_output"
    STT = "stt"
    LLM = "llm"
    TTS = "tts"
    METRICS = "metrics"
    ROUTER = "router"
    CUSTOM = "custom"


@dataclass(frozen=True, slots=True)
class ProcessorNode:
    """Immutable representation of a processor in the pipeline graph.
    
    Attributes:
        processor_id: Unique string identifying this instance (e.g. 'stt_deepgram').
        role: The generic role this processor fills.
        name: Human-readable name or class name of the underlying implementation.
        metadata: Configuration or specific settings needed later by the runner.
    """
    processor_id: str
    role: ProcessorRole
    name: str = "UnknownProcessor"
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "processor_id": self.processor_id,
            "role": self.role.value,
            "name": self.name,
            "metadata": self.metadata,
        }
