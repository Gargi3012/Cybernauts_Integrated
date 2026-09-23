"""
Edge case and exception tests for the conversation package.
"""

from __future__ import annotations

import pytest

from app.conversation import (
    ConversationStateMachine,
    ConversationState,
    InvalidTransitionError,
    TerminalStateError,
    ConversationError,
    InvalidStateError,
)


@pytest.fixture()
def fsm() -> ConversationStateMachine:
    return ConversationStateMachine(session_id="edge-case-session")


class TestExceptionHierarchy:
    def test_invalid_transition_is_conversation_error(self) -> None:
        assert issubclass(InvalidTransitionError, ConversationError)

    def test_terminal_state_is_conversation_error(self) -> None:
        assert issubclass(TerminalStateError, ConversationError)

    def test_invalid_state_is_conversation_error(self) -> None:
        assert issubclass(InvalidStateError, ConversationError)

    def test_catch_all(self, fsm: ConversationStateMachine) -> None:
        with pytest.raises(ConversationError):
            fsm.transition_to(ConversationState.SPEAKING)


class TestExceptionAttributes:
    def test_invalid_transition_attrs(self) -> None:
        e = InvalidTransitionError("idle", "speaking")
        assert e.from_state == "idle"
        assert e.to_state == "speaking"
        assert "idle → speaking" in str(e)

    def test_terminal_state_attrs(self) -> None:
        e = TerminalStateError("abc-123")
        assert e.session_id == "abc-123"
        assert "abc-123" in str(e)

    def test_invalid_state_attrs(self) -> None:
        e = InvalidStateError("bogus")
        assert e.state_value == "bogus"
        assert "bogus" in str(e)


class TestSelfTransition:
    """Same-state transitions should fail (not in the map)."""

    def test_idle_to_idle(self, fsm: ConversationStateMachine) -> None:
        with pytest.raises(InvalidTransitionError):
            fsm.transition_to(ConversationState.IDLE)

    def test_listening_to_listening(self, fsm: ConversationStateMachine) -> None:
        fsm.transition_to(ConversationState.LISTENING)
        with pytest.raises(InvalidTransitionError):
            fsm.transition_to(ConversationState.LISTENING)


class TestMultipleCloseAttempts:
    def test_triple_close(self, fsm: ConversationStateMachine) -> None:
        fsm.close()
        with pytest.raises(TerminalStateError):
            fsm.close()
        with pytest.raises(TerminalStateError):
            fsm.close()

    def test_all_ops_fail_after_close(self, fsm: ConversationStateMachine) -> None:
        fsm.close()
        for state in ConversationState:
            assert fsm.can_transition(state) is False
        with pytest.raises(TerminalStateError):
            fsm.transition_to(ConversationState.IDLE)
        with pytest.raises(TerminalStateError):
            fsm.reset()


class TestHistoryIntegrity:
    def test_history_order_matches_transitions(self, fsm: ConversationStateMachine) -> None:
        flow = [
            ConversationState.LISTENING,
            ConversationState.TRANSCRIBING,
            ConversationState.THINKING,
        ]
        for s in flow:
            fsm.transition_to(s)
        history = fsm.get_transition_history()
        for i, record in enumerate(history):
            assert record.to_state == flow[i]

    def test_timestamps_non_decreasing(self, fsm: ConversationStateMachine) -> None:
        fsm.transition_to(ConversationState.LISTENING)
        fsm.transition_to(ConversationState.TRANSCRIBING)
        fsm.transition_to(ConversationState.THINKING)
        history = fsm.get_transition_history()
        for i in range(1, len(history)):
            assert history[i].timestamp >= history[i - 1].timestamp

    def test_failed_transition_no_history(self, fsm: ConversationStateMachine) -> None:
        with pytest.raises(InvalidTransitionError):
            fsm.transition_to(ConversationState.SPEAKING)
        assert len(fsm) == 0

    def test_history_survives_close(self, fsm: ConversationStateMachine) -> None:
        fsm.transition_to(ConversationState.LISTENING)
        fsm.close()
        assert len(fsm.get_transition_history()) == 2


class TestErrorStateConstraints:
    """ERROR can only go to IDLE or CLOSED."""

    @pytest.mark.parametrize("target", [
        ConversationState.LISTENING,
        ConversationState.TRANSCRIBING,
        ConversationState.THINKING,
        ConversationState.GENERATING_RESPONSE,
        ConversationState.GENERATING_AUDIO,
        ConversationState.SPEAKING,
        ConversationState.INTERRUPTED,
        ConversationState.ERROR,
    ])
    def test_error_rejects_invalid(
        self, fsm: ConversationStateMachine, target: ConversationState
    ) -> None:
        fsm.transition_to(ConversationState.LISTENING)
        fsm.transition_to(ConversationState.ERROR)
        with pytest.raises(InvalidTransitionError):
            fsm.transition_to(target)


class TestInterruptedConstraints:
    """INTERRUPTED can only go to LISTENING or CLOSED."""

    @pytest.mark.parametrize("target", [
        ConversationState.IDLE,
        ConversationState.TRANSCRIBING,
        ConversationState.THINKING,
        ConversationState.SPEAKING,
        ConversationState.ERROR,
    ])
    def test_interrupted_rejects_invalid(
        self, fsm: ConversationStateMachine, target: ConversationState
    ) -> None:
        fsm.transition_to(ConversationState.LISTENING)
        fsm.transition_to(ConversationState.TRANSCRIBING)
        fsm.transition_to(ConversationState.THINKING)
        fsm.transition_to(ConversationState.GENERATING_RESPONSE)
        fsm.transition_to(ConversationState.GENERATING_AUDIO)
        fsm.transition_to(ConversationState.SPEAKING)
        fsm.transition_to(ConversationState.INTERRUPTED)
        with pytest.raises(InvalidTransitionError):
            fsm.transition_to(target)
