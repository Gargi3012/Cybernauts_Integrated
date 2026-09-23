"""
Tests for Data Isolation (Session, Conversation, Event, Pipeline).
Ensures independent data structures per instance.
"""

import pytest
import asyncio

from app.session.manager import SessionManager
from app.conversation.state_machine import ConversationStateMachine
from app.events.bus import EventBus
from app.pipeline.builder import PipelineBuilder
from app.pipeline.processors import ProcessorNode, ProcessorRole


@pytest.mark.asyncio
async def test_session_isolation() -> None:
    """Create 100 sessions concurrently and verify complete data isolation."""
    manager = SessionManager()
    
    # Create 100 sessions
    sessions = await asyncio.gather(*(manager.create_session(metadata={"idx": str(i)}) for i in range(100)))
    
    # Verify independent IDs
    session_ids = set(s.session_id for s in sessions)
    assert len(session_ids) == 100
    
    # Verify metadata and history references are independent
    for s in sessions:
        await manager.add_message(s.session_id, role="user", content=f"Hello {s.metadata['idx']}")
        
    for i, s in enumerate(sessions):
        assert len(s.history) == 1
        assert s.history[0].content == f"Hello {i}"
        
    # Deleting one should not affect others
    await manager.delete_session(sessions[0].session_id)
    assert await manager.total_sessions() == 99


def test_conversation_isolation() -> None:
    """Create multiple FSMs and verify independent states."""
    fsm1 = ConversationStateMachine(session_id="s1")
    fsm2 = ConversationStateMachine(session_id="s2")
    
    from app.conversation.transitions import ConversationState
    fsm1.transition_to(ConversationState.LISTENING)
    
    assert fsm1.get_current_state() == ConversationState.LISTENING
    assert fsm2.get_current_state() == ConversationState.IDLE
    assert fsm1.get_transition_history() is not fsm2.get_transition_history()


def test_pipeline_isolation() -> None:
    """Create 100 pipelines and verify independent graphs."""
    bus = EventBus()
    builders = [PipelineBuilder(bus, f"s_{i}") for i in range(100)]
    
    for i, b in enumerate(builders):
        b.add_processor(ProcessorNode(f"STT_{i}", ProcessorRole.STT))
        
    pipelines = [b.build() for b in builders]
    
    for i, p in enumerate(pipelines):
        assert f"STT_{i}" in p.processors
        if i > 0:
            assert f"STT_{i-1}" not in p.processors
            
    assert len(set(p.pipeline_id for p in pipelines)) == 100
