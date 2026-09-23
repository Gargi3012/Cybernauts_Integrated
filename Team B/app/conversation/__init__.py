"""
Conversation Package — Public API for the conversation state machine.

Import Convention::

    from app.conversation import ConversationStateMachine, ConversationState
    from app.conversation import InvalidTransitionError, TerminalStateError
"""

from .events import (
    AudioGenerationStarted,
    ConversationClosed,
    ConversationEvent,
    ConversationStarted,
    ErrorOccurred,
    Interrupted,
    ListeningStarted,
    ResponseGenerated,
    SpeakingStarted,
    ThinkingStarted,
    TranscriptReady,
    TransitionRecord,
)
from .exceptions import (
    ConversationError,
    InvalidStateError,
    InvalidTransitionError,
    TerminalStateError,
)
from .state_machine import ConversationStateMachine
from .transitions import (
    ConversationState,
    TRANSITION_MAP,
    get_allowed_transitions,
)
from .validators import can_transition, validate_transition

__all__: list[str] = [
    # State machine
    "ConversationStateMachine",
    # Enum + map
    "ConversationState",
    "TRANSITION_MAP",
    "get_allowed_transitions",
    # Validators
    "can_transition",
    "validate_transition",
    # Exceptions
    "ConversationError",
    "InvalidTransitionError",
    "TerminalStateError",
    "InvalidStateError",
    # Events
    "ConversationEvent",
    "ConversationStarted",
    "ConversationClosed",
    "ListeningStarted",
    "TranscriptReady",
    "ThinkingStarted",
    "ResponseGenerated",
    "AudioGenerationStarted",
    "SpeakingStarted",
    "Interrupted",
    "ErrorOccurred",
    "TransitionRecord",
]
