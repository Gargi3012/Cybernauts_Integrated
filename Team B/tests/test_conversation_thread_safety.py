"""
Thread safety stress tests for ConversationStateMachine.
"""

from __future__ import annotations

import threading


from app.conversation import (
    ConversationStateMachine,
    ConversationState,
    InvalidTransitionError,
    TerminalStateError,
)


class TestConcurrentTransitions:
    """Multiple threads racing to transition the same FSM."""

    def test_concurrent_valid_transitions(self) -> None:
        """Only one thread should win each race; no crashes."""
        fsm = ConversationStateMachine(session_id="thread-test")
        fsm.transition_to(ConversationState.LISTENING)
        errors: list[Exception] = []
        successes: list[bool] = []

        def try_transition(target: ConversationState) -> None:
            try:
                fsm.transition_to(target)
                successes.append(True)
            except (InvalidTransitionError, TerminalStateError):
                successes.append(False)
            except Exception as e:
                errors.append(e)

        # From LISTENING, only TRANSCRIBING, INTERRUPTED, ERROR, CLOSED valid
        threads = [
            threading.Thread(target=try_transition, args=(ConversationState.TRANSCRIBING,)),
            threading.Thread(target=try_transition, args=(ConversationState.INTERRUPTED,)),
            threading.Thread(target=try_transition, args=(ConversationState.ERROR,)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors, f"Unexpected errors: {errors}"
        # At least one should succeed; state should be valid
        assert fsm.get_current_state() in {
            ConversationState.TRANSCRIBING,
            ConversationState.INTERRUPTED,
            ConversationState.ERROR,
        }

    def test_concurrent_close_race(self) -> None:
        """Multiple threads try to close; exactly one should succeed."""
        fsm = ConversationStateMachine(session_id="close-race")
        results: list[bool] = []
        errors: list[Exception] = []

        def try_close() -> None:
            try:
                fsm.close()
                results.append(True)
            except TerminalStateError:
                results.append(False)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=try_close) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors
        assert results.count(True) == 1
        assert fsm.get_current_state() == ConversationState.CLOSED


class TestConcurrentReads:
    """Reads must not crash or corrupt state under load."""

    def test_concurrent_reads_during_transitions(self) -> None:
        fsm = ConversationStateMachine(session_id="read-test")
        errors: list[Exception] = []

        def do_transitions() -> None:
            try:
                fsm.transition_to(ConversationState.LISTENING)
                fsm.transition_to(ConversationState.TRANSCRIBING)
                fsm.transition_to(ConversationState.THINKING)
            except Exception as e:
                errors.append(e)

        def do_reads() -> None:
            try:
                for _ in range(50):
                    fsm.get_current_state()
                    fsm.get_previous_state()
                    fsm.get_transition_history()
                    fsm.to_dict()
                    len(fsm)
            except Exception as e:
                errors.append(e)

        t_write = threading.Thread(target=do_transitions)
        readers = [threading.Thread(target=do_reads) for _ in range(5)]

        t_write.start()
        for r in readers:
            r.start()
        t_write.join(timeout=5)
        for r in readers:
            r.join(timeout=5)

        assert not errors


class TestManyFSMInstances:
    """Many independent FSMs running concurrently."""

    def test_100_independent_fsms(self) -> None:
        errors: list[Exception] = []

        def run_conversation(idx: int) -> None:
            try:
                fsm = ConversationStateMachine(session_id=f"session-{idx}")
                fsm.transition_to(ConversationState.LISTENING)
                fsm.transition_to(ConversationState.TRANSCRIBING)
                fsm.transition_to(ConversationState.THINKING)
                fsm.transition_to(ConversationState.GENERATING_RESPONSE)
                fsm.transition_to(ConversationState.GENERATING_AUDIO)
                fsm.transition_to(ConversationState.SPEAKING)
                fsm.close()
                assert fsm.get_current_state() == ConversationState.CLOSED
                assert len(fsm) == 7
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=run_conversation, args=(i,))
            for i in range(100)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors
