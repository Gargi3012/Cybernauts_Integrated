"""
Conversation State Machine — Thread-safe FSM controlling voice conversation flow.

Design Decisions:

1.  **One state machine per session**: Each ``ConversationStateMachine``
    is bound to a ``session_id`` at construction.  The future pipeline
    coordinator will maintain a ``Dict[str, ConversationStateMachine]``.

2.  **Strict transition validation**: Every ``transition_to()`` call is
    validated against the ``TRANSITION_MAP`` via the validators module.
    Invalid transitions raise, never silently succeed.

3.  **Transition history**: An append-only list of ``TransitionRecord``
    objects provides a full audit trail per conversation for debugging,
    analytics, and latency measurement.

4.  **threading.Lock**: Matches the SessionManager locking strategy.
    All state reads and mutations are guarded by a single lock to
    prevent concurrent corruption.

5.  **Loose coupling with SessionManager**: The state machine does NOT
    import or depend on SessionManager.  The pipeline coordinator (future
    milestone) will synchronise both layers.

Future Compatibility:
    - Event Bus integration: ``transition_to`` will emit events.
    - Pipecat processors: will call ``transition_to`` at each stage.
    - Async variant: swap ``threading.Lock`` for ``asyncio.Lock``.
"""

from __future__ import annotations

import threading
from typing import List, Optional

from loguru import logger

from .events import TransitionRecord
from .transitions import ConversationState
from .validators import validate_transition, can_transition as _can_transition


class ConversationStateMachine:
    """Thread-safe finite state machine for a single voice conversation.

    The machine starts in ``IDLE`` and enforces all transitions against
    the ``TRANSITION_MAP``.  An ordered transition history is maintained
    for auditing and latency analysis.

    Args:
        session_id: The UUID of the session this machine is bound to.

    Example::

        fsm = ConversationStateMachine(session_id="abc-123")
        fsm.transition_to(ConversationState.LISTENING, reason="user spoke")
        fsm.transition_to(ConversationState.TRANSCRIBING)
        print(fsm.get_current_state())     # ConversationState.TRANSCRIBING
        print(fsm.get_previous_state())    # ConversationState.LISTENING
        print(len(fsm.get_transition_history()))  # 2

    Thread Safety:
        All public methods acquire ``_lock`` before reading or mutating
        state.  Safe for concurrent access from multiple ASGI handlers.
    """

    __slots__ = ("_session_id", "_current_state", "_previous_state",
                 "_history", "_lock")

    def __init__(self, session_id: str) -> None:
        """Initialise the state machine in the IDLE state.

        Args:
            session_id: The session UUID this machine manages.
        """
        self._session_id: str = session_id
        self._current_state: ConversationState = ConversationState.IDLE
        self._previous_state: Optional[ConversationState] = None
        self._history: List[TransitionRecord] = []
        self._lock: threading.Lock = threading.Lock()

        logger.bind(session_id=session_id).info(
            "ConversationStateMachine initialised | state={state}",
            state=self._current_state.value,
        )

    # ==================================================================
    #  PROPERTIES
    # ==================================================================

    @property
    def session_id(self) -> str:
        """The session UUID this machine is bound to."""
        return self._session_id

    # ==================================================================
    #  STATE QUERIES
    # ==================================================================

    def get_current_state(self) -> ConversationState:
        """Return the current conversation state.

        Returns:
            The current ``ConversationState``.
        """
        with self._lock:
            return self._current_state

    def get_previous_state(self) -> Optional[ConversationState]:
        """Return the state before the most recent transition.

        Returns:
            The previous ``ConversationState``, or ``None`` if no
            transition has occurred yet.
        """
        with self._lock:
            return self._previous_state

    def get_transition_history(self) -> List[TransitionRecord]:
        """Return a copy of the full transition history.

        Returns:
            A shallow copy of the ordered list of ``TransitionRecord``
            objects.
        """
        with self._lock:
            return list(self._history)

    # ==================================================================
    #  STATE MUTATIONS
    # ==================================================================

    def transition_to(
        self,
        target: ConversationState,
        reason: str = "",
    ) -> TransitionRecord:
        """Transition to ``target`` state with strict validation.

        Args:
            target: The desired next state.
            reason: Optional human-readable reason for the transition
                    (e.g., ``"user barged in"``, ``"STT complete"``).

        Returns:
            The ``TransitionRecord`` that was appended to the history.

        Raises:
            TerminalStateError:     If current state is CLOSED.
            InvalidTransitionError: If the transition is not allowed.
        """
        with self._lock:
            # Validate (raises on failure)
            validate_transition(
                self._current_state, target, self._session_id
            )

            old_state = self._current_state
            self._previous_state = old_state
            self._current_state = target

            record = TransitionRecord(
                session_id=self._session_id,
                from_state=old_state,
                to_state=target,
                reason=reason,
            )
            self._history.append(record)

        logger.bind(session_id=self._session_id).info(
            "Transition | {old} → {new}{reason}",
            old=old_state.value,
            new=target.value,
            reason=f" | reason={reason}" if reason else "",
        )
        return record

    def set_state(
        self,
        target: ConversationState,
        reason: str = "",
    ) -> TransitionRecord:
        """Alias for ``transition_to`` — validates and transitions.

        Provided for API symmetry with ``SessionManager.set_state()``.
        """
        return self.transition_to(target, reason=reason)

    def can_transition(self, target: ConversationState) -> bool:
        """Check whether transitioning to ``target`` is currently allowed.

        Args:
            target: The candidate target state.

        Returns:
            ``True`` if the transition is legal, ``False`` otherwise.
        """
        with self._lock:
            return _can_transition(self._current_state, target)

    # ==================================================================
    #  CONVENIENCE METHODS
    # ==================================================================

    def reset(self, reason: str = "reset") -> TransitionRecord:
        """Reset the conversation to IDLE.

        This is valid from ERROR or SPEAKING.  From other states, the
        standard transition rules apply.

        Args:
            reason: Reason for the reset.

        Returns:
            The ``TransitionRecord`` for the IDLE transition.

        Raises:
            InvalidTransitionError: If resetting from the current state
                is not allowed by the transition map.
        """
        return self.transition_to(ConversationState.IDLE, reason=reason)

    def close(self, reason: str = "conversation ended") -> TransitionRecord:
        """Close the conversation (terminal transition).

        CLOSED is reachable from every non-terminal state.

        Args:
            reason: Reason for closing.

        Returns:
            The ``TransitionRecord`` for the CLOSED transition.

        Raises:
            TerminalStateError: If already CLOSED.
        """
        return self.transition_to(ConversationState.CLOSED, reason=reason)

    # ==================================================================
    #  SERIALIZATION
    # ==================================================================

    def to_dict(self) -> dict[str, object]:
        """Serialize the machine state to a JSON-compatible dictionary.

        Returns:
            Dictionary with current state, previous state, session_id,
            and full transition history.
        """
        with self._lock:
            return {
                "session_id": self._session_id,
                "current_state": self._current_state.value,
                "previous_state": (
                    self._previous_state.value
                    if self._previous_state else None
                ),
                "transition_count": len(self._history),
                "history": [r.to_dict() for r in self._history],
            }

    # ==================================================================
    #  DUNDER
    # ==================================================================

    def __repr__(self) -> str:
        with self._lock:
            return (
                f"ConversationStateMachine("
                f"session={self._session_id[:8]}…, "
                f"state={self._current_state.value}, "
                f"transitions={len(self._history)})"
            )

    def __len__(self) -> int:
        """Return the number of transitions that have occurred."""
        with self._lock:
            return len(self._history)
