"""
Event Bus Package — Centralised pub/sub messaging.

Import Convention::

    from app.events import EventBus, Publisher
    from app.events import TranscriptReady, SessionCreated
"""

from .bus import EventBus
from .dispatcher import Dispatcher
from .event_types import (
    AudioGenerationStarted,
    ConversationEnded,
    ConversationInterrupted,
    ConversationResumed,
    ConversationStarted,
    ErrorOccurred,
    Event,
    ListeningStarted,
    ListeningStopped,
    MetricsUpdated,
    PipelinePaused,
    PipelineResumed,
    PipelineStarted,
    PipelineStopped,
    ResponseGenerated,
    SessionClosed,
    SessionCreated,
    SpeakingFinished,
    SpeakingStarted,
    ThinkingStarted,
    TranscriptReady,
    PipelineCreated,
    ProcessorAdded,
    ProcessorRemoved,
    PipelineValidated,
    PipelineBuildSucceeded,
    PipelineBuildFailed,
    PipelineInitialized,
    PipelineCompleted,
    PipelineFailed,
    PipelineCancelled,
    PipelineShutdown,
    ProcessorExecutionStarted,
    ProcessorExecutionCompleted,
    ProcessorExecutionFailed,
)
from .exceptions import (
    DispatchError,
    DuplicateSubscriberError,
    EventBusError,
    EventNotRegisteredError,
    HandlerExecutionError,
    MiddlewareError,
)
from .handlers import EventHandler
from .middleware import LoggingMiddleware, MetricsMiddleware, Middleware
from .publisher import Publisher
from .registry import Registry
from .subscriber import Subscriber

__all__: list[str] = [
    # Core
    "EventBus",
    "Publisher",
    "Dispatcher",
    "Registry",
    "Subscriber",
    "EventHandler",
    # Middleware
    "Middleware",
    "LoggingMiddleware",
    "MetricsMiddleware",
    # Exceptions
    "EventBusError",
    "DuplicateSubscriberError",
    "EventNotRegisteredError",
    "HandlerExecutionError",
    "MiddlewareError",
    "DispatchError",
    # Events Base
    "Event",
    # Session Events
    "SessionCreated",
    "SessionClosed",
    # Conversation Events
    "ConversationStarted",
    "ConversationEnded",
    "ConversationInterrupted",
    "ConversationResumed",
    # Pipeline Stage Events
    "ListeningStarted",
    "ListeningStopped",
    "TranscriptReady",
    "ThinkingStarted",
    "ResponseGenerated",
    "AudioGenerationStarted",
    "SpeakingStarted",
    "SpeakingFinished",
    # Error/Metrics Events
    "ErrorOccurred",
    "MetricsUpdated",
    # Control Events
    "PipelineStarted",
    "PipelineStopped",
    "PipelinePaused",
    "PipelineResumed",
    # Builder Events
    "PipelineCreated",
    "ProcessorAdded",
    "ProcessorRemoved",
    "PipelineValidated",
    "PipelineBuildSucceeded",
    "PipelineBuildFailed",
    # Runner Events
    "PipelineInitialized",
    "PipelineCompleted",
    "PipelineFailed",
    "PipelineCancelled",
    "PipelineShutdown",
    "ProcessorExecutionStarted",
    "ProcessorExecutionCompleted",
    "ProcessorExecutionFailed",
]
