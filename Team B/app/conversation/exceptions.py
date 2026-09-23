"""
Custom exceptions for the Conversation State Machine.

Design Decision:
    Each exception type maps to a specific failure mode so that callers
    can handle them granularly (e.g., retry on TransitionError but abort
    on TerminalStateError).  All inherit from a common base so that a
    single ``except ConversationError`` catch-all is also possible.
"""

from __future__ import annotations


class ConversationError(Exception):
    """Base exception for all conversation state machine errors."""


class InvalidTransitionError(ConversationError):
    """Raised when a state transition violates the allowed transition map.

    Attributes:
        from_state: The state the machine was in when the transition was attempted.
        to_state:   The target state that was rejected.
    """

    def __init__(self, from_state: str, to_state: str) -> None:
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(
            f"Invalid transition: {from_state} → {to_state}"
        )


class TerminalStateError(ConversationError):
    """Raised when a transition is attempted from the terminal CLOSED state.

    Attributes:
        session_id: The session that is already closed.
    """

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        super().__init__(
            f"Session '{session_id}' is in terminal state CLOSED — "
            f"no further transitions allowed"
        )


class InvalidStateError(ConversationError):
    """Raised when an unknown or invalid state value is encountered.

    Attributes:
        state_value: The invalid value that was provided.
    """

    def __init__(self, state_value: str) -> None:
        self.state_value = state_value
        super().__init__(f"Unknown conversation state: '{state_value}'")
