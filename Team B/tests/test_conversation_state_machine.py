"""
Tests for ConversationStateMachine — core FSM operations.
"""

from __future__ import annotations

import json

import pytest

from app.conversation import (
    ConversationStateMachine,
    ConversationState,
    TransitionRecord,
    InvalidTransitionError,
    TerminalStateError,
)


@pytest.fixture()
def fsm() -> ConversationStateMachine:
    return ConversationStateMachine(session_id="test-session-001")


# ──────────────────────────────────────────────────────────────
# Initialisation
# ──────────────────────────────────────────────────────────────

class TestInit:
    def test_starts_idle(self, fsm: ConversationStateMachine) -> None:
        assert fsm.get_current_state() == ConversationState.IDLE

    def test_no_previous_state(self, fsm: ConversationStateMachine) -> None:
        assert fsm.get_previous_state() is None

    def test_empty_history(self, fsm: ConversationStateMachine) -> None:
        assert fsm.get_transition_history() == []

    def test_session_id(self, fsm: ConversationStateMachine) -> None:
        assert fsm.session_id == "test-session-001"

    def test_len_zero(self, fsm: ConversationStateMachine) -> None:
        assert len(fsm) == 0


# ──────────────────────────────────────────────────────────────
# transition_to
# ──────────────────────────────────────────────────────────────

class TestTransitionTo:
    def test_valid_transition(self, fsm: ConversationStateMachine) -> None:
        record = fsm.transition_to(ConversationState.LISTENING)
        assert isinstance(record, TransitionRecord)
        assert fsm.get_current_state() == ConversationState.LISTENING

    def test_record_fields(self, fsm: ConversationStateMachine) -> None:
        r = fsm.transition_to(ConversationState.LISTENING, reason="mic open")
        assert r.from_state == ConversationState.IDLE
        assert r.to_state == ConversationState.LISTENING
        assert r.reason == "mic open"
        assert r.session_id == "test-session-001"

    def test_updates_previous_state(self, fsm: ConversationStateMachine) -> None:
        fsm.transition_to(ConversationState.LISTENING)
        assert fsm.get_previous_state() == ConversationState.IDLE
        fsm.transition_to(ConversationState.TRANSCRIBING)
        assert fsm.get_previous_state() == ConversationState.LISTENING

    def test_appends_to_history(self, fsm: ConversationStateMachine) -> None:
        fsm.transition_to(ConversationState.LISTENING)
        fsm.transition_to(ConversationState.TRANSCRIBING)
        assert len(fsm.get_transition_history()) == 2

    def test_history_is_copy(self, fsm: ConversationStateMachine) -> None:
        fsm.transition_to(ConversationState.LISTENING)
        h1 = fsm.get_transition_history()
        h2 = fsm.get_transition_history()
        assert h1 is not h2

    def test_invalid_raises(self, fsm: ConversationStateMachine) -> None:
        with pytest.raises(InvalidTransitionError):
            fsm.transition_to(ConversationState.SPEAKING)

    def test_terminal_raises(self, fsm: ConversationStateMachine) -> None:
        fsm.transition_to(ConversationState.CLOSED)
        with pytest.raises(TerminalStateError):
            fsm.transition_to(ConversationState.IDLE)

    def test_state_unchanged_on_invalid(self, fsm: ConversationStateMachine) -> None:
        with pytest.raises(InvalidTransitionError):
            fsm.transition_to(ConversationState.THINKING)
        assert fsm.get_current_state() == ConversationState.IDLE
        assert len(fsm) == 0


# ──────────────────────────────────────────────────────────────
# Full conversation flows
# ──────────────────────────────────────────────────────────────

class TestConversationFlows:
    def test_happy_path(self, fsm: ConversationStateMachine) -> None:
        flow = [
            ConversationState.LISTENING,
            ConversationState.TRANSCRIBING,
            ConversationState.THINKING,
            ConversationState.GENERATING_RESPONSE,
            ConversationState.GENERATING_AUDIO,
            ConversationState.SPEAKING,
            ConversationState.LISTENING,
        ]
        for state in flow:
            fsm.transition_to(state)
        assert fsm.get_current_state() == ConversationState.LISTENING
        assert len(fsm) == 7

    def test_interrupt_flow(self, fsm: ConversationStateMachine) -> None:
        fsm.transition_to(ConversationState.LISTENING)
        fsm.transition_to(ConversationState.TRANSCRIBING)
        fsm.transition_to(ConversationState.THINKING)
        fsm.transition_to(ConversationState.GENERATING_RESPONSE)
        fsm.transition_to(ConversationState.GENERATING_AUDIO)
        fsm.transition_to(ConversationState.SPEAKING)
        fsm.transition_to(ConversationState.INTERRUPTED)
        fsm.transition_to(ConversationState.LISTENING)
        assert fsm.get_current_state() == ConversationState.LISTENING

    def test_error_recovery(self, fsm: ConversationStateMachine) -> None:
        fsm.transition_to(ConversationState.LISTENING)
        fsm.transition_to(ConversationState.ERROR)
        fsm.transition_to(ConversationState.IDLE)
        assert fsm.get_current_state() == ConversationState.IDLE

    def test_error_to_closed(self, fsm: ConversationStateMachine) -> None:
        fsm.transition_to(ConversationState.LISTENING)
        fsm.transition_to(ConversationState.ERROR)
        fsm.transition_to(ConversationState.CLOSED)
        assert fsm.get_current_state() == ConversationState.CLOSED


# ──────────────────────────────────────────────────────────────
# set_state (alias)
# ──────────────────────────────────────────────────────────────

class TestSetState:
    def test_alias(self, fsm: ConversationStateMachine) -> None:
        r = fsm.set_state(ConversationState.LISTENING, reason="alias test")
        assert r.to_state == ConversationState.LISTENING
        assert fsm.get_current_state() == ConversationState.LISTENING


# ──────────────────────────────────────────────────────────────
# can_transition
# ──────────────────────────────────────────────────────────────

class TestCanTransition:
    def test_valid(self, fsm: ConversationStateMachine) -> None:
        assert fsm.can_transition(ConversationState.LISTENING) is True

    def test_invalid(self, fsm: ConversationStateMachine) -> None:
        assert fsm.can_transition(ConversationState.SPEAKING) is False

    def test_after_close(self, fsm: ConversationStateMachine) -> None:
        fsm.transition_to(ConversationState.CLOSED)
        for s in ConversationState:
            assert fsm.can_transition(s) is False


# ──────────────────────────────────────────────────────────────
# reset / close
# ──────────────────────────────────────────────────────────────

class TestResetClose:
    def test_reset_from_error(self, fsm: ConversationStateMachine) -> None:
        fsm.transition_to(ConversationState.LISTENING)
        fsm.transition_to(ConversationState.ERROR)
        r = fsm.reset()
        assert fsm.get_current_state() == ConversationState.IDLE
        assert r.reason == "reset"

    def test_reset_from_speaking(self, fsm: ConversationStateMachine) -> None:
        fsm.transition_to(ConversationState.LISTENING)
        fsm.transition_to(ConversationState.TRANSCRIBING)
        fsm.transition_to(ConversationState.THINKING)
        fsm.transition_to(ConversationState.GENERATING_RESPONSE)
        fsm.transition_to(ConversationState.GENERATING_AUDIO)
        fsm.transition_to(ConversationState.SPEAKING)
        fsm.reset()
        assert fsm.get_current_state() == ConversationState.IDLE

    def test_reset_from_invalid_state_raises(self, fsm: ConversationStateMachine) -> None:
        fsm.transition_to(ConversationState.LISTENING)
        with pytest.raises(InvalidTransitionError):
            fsm.reset()  # LISTENING → IDLE is not allowed

    def test_close(self, fsm: ConversationStateMachine) -> None:
        r = fsm.close()
        assert fsm.get_current_state() == ConversationState.CLOSED
        assert r.reason == "conversation ended"

    def test_close_from_any_active(self, fsm: ConversationStateMachine) -> None:
        fsm.transition_to(ConversationState.LISTENING)
        fsm.transition_to(ConversationState.TRANSCRIBING)
        fsm.close(reason="user disconnected")
        assert fsm.get_current_state() == ConversationState.CLOSED

    def test_double_close_raises(self, fsm: ConversationStateMachine) -> None:
        fsm.close()
        with pytest.raises(TerminalStateError):
            fsm.close()


# ──────────────────────────────────────────────────────────────
# Serialization
# ──────────────────────────────────────────────────────────────

class TestSerialization:
    def test_to_dict_keys(self, fsm: ConversationStateMachine) -> None:
        d = fsm.to_dict()
        assert set(d.keys()) == {
            "session_id", "current_state", "previous_state",
            "transition_count", "history",
        }

    def test_to_dict_json_safe(self, fsm: ConversationStateMachine) -> None:
        fsm.transition_to(ConversationState.LISTENING)
        s = json.dumps(fsm.to_dict())
        rt = json.loads(s)
        assert rt["current_state"] == "listening"
        assert len(rt["history"]) == 1

    def test_previous_state_none_initially(self, fsm: ConversationStateMachine) -> None:
        assert fsm.to_dict()["previous_state"] is None


# ──────────────────────────────────────────────────────────────
# Repr / len
# ──────────────────────────────────────────────────────────────

class TestDunders:
    def test_repr(self, fsm: ConversationStateMachine) -> None:
        r = repr(fsm)
        assert "test-ses" in r and "idle" in r

    def test_len(self, fsm: ConversationStateMachine) -> None:
        assert len(fsm) == 0
        fsm.transition_to(ConversationState.LISTENING)
        assert len(fsm) == 1
