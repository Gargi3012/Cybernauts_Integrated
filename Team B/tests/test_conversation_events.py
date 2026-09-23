"""
Tests for conversation event models and TransitionRecord.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from app.conversation import (
    ConversationEvent,
    ConversationStarted,
    ConversationClosed,
    ListeningStarted,
    TranscriptReady,
    ThinkingStarted,
    ResponseGenerated,
    AudioGenerationStarted,
    SpeakingStarted,
    Interrupted,
    ErrorOccurred,
    TransitionRecord,
    ConversationState,
)


class TestConversationEvent:
    def test_base_fields(self) -> None:
        e = ConversationEvent(session_id="s1")
        assert e.session_id == "s1"
        assert e.timestamp.tzinfo is not None

    def test_to_dict(self) -> None:
        e = ConversationEvent(session_id="s1")
        d = e.to_dict()
        assert d["event"] == "ConversationEvent"
        assert d["session_id"] == "s1"
        assert isinstance(d["timestamp"], str)

    def test_frozen(self) -> None:
        e = ConversationEvent(session_id="s1")
        with pytest.raises(AttributeError):
            e.session_id = "s2"  # type: ignore[misc]


class TestAllEventTypes:
    """Verify every event type can be constructed and serialized."""

    EVENT_CLASSES = [
        ConversationStarted, ConversationClosed, ListeningStarted,
        TranscriptReady, ThinkingStarted, ResponseGenerated,
        AudioGenerationStarted, SpeakingStarted, Interrupted,
    ]

    @pytest.mark.parametrize("cls", EVENT_CLASSES)
    def test_construction(self, cls: type) -> None:
        e = cls(session_id="test-session")
        assert e.session_id == "test-session"
        assert isinstance(e.timestamp, datetime)

    @pytest.mark.parametrize("cls", EVENT_CLASSES)
    def test_json_safe(self, cls: type) -> None:
        e = cls(session_id="test-session")
        serialized = json.dumps(e.to_dict())
        assert isinstance(serialized, str)

    @pytest.mark.parametrize("cls", EVENT_CLASSES)
    def test_event_name_in_dict(self, cls: type) -> None:
        d = cls(session_id="s").to_dict()
        assert d["event"] == cls.__name__


class TestErrorOccurred:
    def test_default_message(self) -> None:
        e = ErrorOccurred(session_id="s1")
        assert e.error_message == "Unknown error"

    def test_custom_message(self) -> None:
        e = ErrorOccurred(session_id="s1", error_message="STT timeout")
        assert e.error_message == "STT timeout"

    def test_to_dict_includes_error(self) -> None:
        d = ErrorOccurred(session_id="s1", error_message="fail").to_dict()
        assert d["error_message"] == "fail"


class TestConversationClosed:
    def test_default_reason(self) -> None:
        assert ConversationClosed(session_id="s1").reason == "normal"

    def test_custom_reason(self) -> None:
        e = ConversationClosed(session_id="s1", reason="timeout")
        assert e.reason == "timeout"


class TestTransitionRecord:
    def test_construction(self) -> None:
        r = TransitionRecord(
            session_id="s1",
            from_state=ConversationState.IDLE,
            to_state=ConversationState.LISTENING,
            reason="user spoke",
        )
        assert r.from_state == ConversationState.IDLE
        assert r.to_state == ConversationState.LISTENING
        assert r.reason == "user spoke"

    def test_to_dict(self) -> None:
        r = TransitionRecord(
            session_id="s1",
            from_state=ConversationState.IDLE,
            to_state=ConversationState.LISTENING,
        )
        d = r.to_dict()
        assert d["from_state"] == "idle"
        assert d["to_state"] == "listening"
        assert d["session_id"] == "s1"

    def test_json_safe(self) -> None:
        r = TransitionRecord(
            session_id="s1",
            from_state=ConversationState.IDLE,
            to_state=ConversationState.LISTENING,
        )
        assert isinstance(json.dumps(r.to_dict()), str)

    def test_frozen(self) -> None:
        r = TransitionRecord(
            session_id="s1",
            from_state=ConversationState.IDLE,
            to_state=ConversationState.LISTENING,
        )
        with pytest.raises(AttributeError):
            r.reason = "changed"  # type: ignore[misc]
