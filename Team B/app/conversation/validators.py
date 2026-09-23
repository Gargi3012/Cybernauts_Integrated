"""
Transition Validators — Stateless functions that enforce FSM rules.

Design Decision:
    Validators are pure functions (no side effects, no state) so they are
    trivially testable and reusable.  The state machine delegates all
    rule-checking here, keeping its own code focused on state mutation
    and history recording.
"""

from __future__ import annotations

from .exceptions import InvalidTransitionError, TerminalStateError
from .transitions import ConversationState, TRANSITION_MAP


def validate_transition(
    from_state: ConversationState,
    to_state: ConversationState,
    session_id: str,
) -> None:
    """Validate that ``from_state → to_state`` is a legal transition.

    Args:
        from_state:  The current state of the conversation.
        to_state:    The requested target state.
        session_id:  Used only for error context in TerminalStateError.

    Raises:
        TerminalStateError:     If ``from_state`` is CLOSED.
        InvalidTransitionError: If the transition is not in TRANSITION_MAP.
    """
    if from_state.is_terminal():
        raise TerminalStateError(session_id)

    allowed = TRANSITION_MAP.get(from_state, frozenset())
    if to_state not in allowed:
        raise InvalidTransitionError(from_state.value, to_state.value)


def can_transition(
    from_state: ConversationState,
    to_state: ConversationState,
) -> bool:
    """Non-throwing check for whether a transition is legal.

    Args:
        from_state: Current state.
        to_state:   Target state.

    Returns:
        ``True`` if the transition is allowed, ``False`` otherwise.
    """
    if from_state.is_terminal():
        return False
    return to_state in TRANSITION_MAP.get(from_state, frozenset())
