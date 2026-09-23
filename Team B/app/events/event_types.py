"""
Event Types — Strongly typed event models for the Event Bus.

Design Decision:
    Every event inherits from ``Event`` which carries identity (event_id),
    correlation (session_id), timing (timestamp), and extension points
    (payload, metadata).  This uniform shape allows the dispatcher,
    middleware, and metrics layer to operate generically on any event.

    Events are frozen dataclasses — immutable once created, thread-safe
    by construction, and safe to pass across async tasks.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict


# ──────────────────────────────────────────────────────────────────────
# Base Event
# ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Event:
    """Base class for all bus events.

    Attributes:
        event_id:   Globally unique identifier (UUID4).
        event_name: Derived from the class name automatically.
        session_id: The session this event relates to.
        timestamp:  UTC creation time.
        payload:    Arbitrary data dict for event-specific content.
        metadata:   Arbitrary metadata (tracing IDs, source info, etc.).
    """

    session_id: str
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    payload: Dict[str, object] = field(default_factory=dict)
    metadata: Dict[str, str] = field(default_factory=dict)

    @property
    def event_name(self) -> str:
        """Return the class name as the canonical event name."""
        return type(self).__name__

    def to_dict(self) -> dict[str, object]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "event_id": self.event_id,
            "event_name": self.event_name,
            "session_id": self.session_id,
            "timestamp": self.timestamp.isoformat(),
            "payload": self.payload,
            "metadata": self.metadata,
        }


# ──────────────────────────────────────────────────────────────────────
# Session events
# ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class SessionCreated(Event):
    """A new session was created."""


@dataclass(frozen=True, slots=True)
class SessionClosed(Event):
    """A session was deleted / closed."""


# ──────────────────────────────────────────────────────────────────────
# Conversation lifecycle events
# ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class ConversationStarted(Event):
    """Conversation transitioned from IDLE to active."""


@dataclass(frozen=True, slots=True)
class ConversationEnded(Event):
    """Conversation reached terminal CLOSED state."""


@dataclass(frozen=True, slots=True)
class ConversationInterrupted(Event):
    """User barged in during AI speech."""


@dataclass(frozen=True, slots=True)
class ConversationResumed(Event):
    """Conversation resumed after interruption."""


# ──────────────────────────────────────────────────────────────────────
# Pipeline stage events
# ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class ListeningStarted(Event):
    """Microphone opened, audio streaming to STT."""


@dataclass(frozen=True, slots=True)
class ListeningStopped(Event):
    """Microphone closed, audio buffered."""


@dataclass(frozen=True, slots=True)
class TranscriptReady(Event):
    """STT finished transcribing — text available in payload."""


@dataclass(frozen=True, slots=True)
class ThinkingStarted(Event):
    """LLM began processing user transcript."""


@dataclass(frozen=True, slots=True)
class ResponseGenerated(Event):
    """LLM completed response generation."""


@dataclass(frozen=True, slots=True)
class AudioGenerationStarted(Event):
    """TTS began synthesising audio."""


@dataclass(frozen=True, slots=True)
class SpeakingStarted(Event):
    """Audio playback to user began."""


@dataclass(frozen=True, slots=True)
class SpeakingFinished(Event):
    """Audio playback to user completed."""


# ──────────────────────────────────────────────────────────────────────
# Error & metrics events
# ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class ErrorOccurred(Event):
    """A recoverable pipeline error occurred."""


@dataclass(frozen=True, slots=True)
class MetricsUpdated(Event):
    """Component metrics updated — values in payload."""


# ──────────────────────────────────────────────────────────────────────
# Pipeline control events
# ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class PipelineStarted(Event):
    """Pipecat pipeline started for a session."""


@dataclass(frozen=True, slots=True)
class PipelineStopped(Event):
    """Pipecat pipeline stopped."""


@dataclass(frozen=True, slots=True)
class PipelinePaused(Event):
    """Pipecat pipeline paused."""


@dataclass(frozen=True, slots=True)
class PipelineResumed(Event):
    """Pipecat pipeline resumed from pause."""


# ──────────────────────────────────────────────────────────────────────
# Pipeline Builder Events
# ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class PipelineCreated(Event):
    """A new pipeline builder instance was created."""


@dataclass(frozen=True, slots=True)
class ProcessorAdded(Event):
    """A processor was added to the pipeline builder."""


@dataclass(frozen=True, slots=True)
class ProcessorRemoved(Event):
    """A processor was removed from the pipeline builder."""


@dataclass(frozen=True, slots=True)
class PipelineValidated(Event):
    """The pipeline graph passed validation."""


@dataclass(frozen=True, slots=True)
class PipelineBuildSucceeded(Event):
    """The pipeline was successfully built into an immutable graph."""


@dataclass(frozen=True, slots=True)
class PipelineBuildFailed(Event):
    """The pipeline build process failed."""


# ──────────────────────────────────────────────────────────────────────
# Pipeline Runner Events
# ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class PipelineInitialized(Event):
    """The pipeline runner was initialized."""


@dataclass(frozen=True, slots=True)
class PipelineCompleted(Event):
    """The pipeline completed execution successfully."""


@dataclass(frozen=True, slots=True)
class PipelineFailed(Event):
    """The pipeline failed during execution."""


@dataclass(frozen=True, slots=True)
class PipelineCancelled(Event):
    """The pipeline execution was cancelled."""


@dataclass(frozen=True, slots=True)
class PipelineShutdown(Event):
    """The pipeline runner shut down gracefully."""


@dataclass(frozen=True, slots=True)
class ProcessorExecutionStarted(Event):
    """A processor started execution."""


@dataclass(frozen=True, slots=True)
class ProcessorExecutionCompleted(Event):
    """A processor completed execution successfully."""


@dataclass(frozen=True, slots=True)
class ProcessorExecutionFailed(Event):
    """A processor failed during execution."""

# ──────────────────────────────────────────────────────────────────────
# Greeting Events
# ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class AssistantGreetingStarted(Event):
    """Assistant initiated the conversation greeting."""


@dataclass(frozen=True, slots=True)
class AssistantGreetingGenerated(Event):
    """LLM generated the greeting text."""


@dataclass(frozen=True, slots=True)
class AssistantGreetingTTSStarted(Event):
    """TTS began synthesizing the greeting."""


@dataclass(frozen=True, slots=True)
class AssistantGreetingCompleted(Event):
    """Greeting playback completed."""


@dataclass(frozen=True, slots=True)
class ConversationReady(Event):
    """Greeting complete and assistant is ready to listen."""
