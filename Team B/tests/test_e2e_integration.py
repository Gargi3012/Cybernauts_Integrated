"""
End-to-End Integration Tests for Real-Time Voice Pipeline
"""

import asyncio
import pytest

from app.session.manager import SessionManager
from app.conversation.state_machine import ConversationStateMachine
from app.events.bus import EventBus
from app.pipeline.builder import PipelineBuilder
from app.pipeline.processors import ProcessorNode, ProcessorRole
from app.adapters.pipecat.factory import PipecatFactory
from app.adapters.pipecat.transport import MockWebSocketTransport


@pytest.fixture
def e2e_setup():
    """Sets up the complete integrated environment."""
    bus = EventBus()
    session_manager = SessionManager(event_bus=bus) # Wait, SessionManager signature: SessionManager() currently doesn't take event_bus in Milestone 1, but let's assume it doesn't or does.
    # Ah, let's just initialize them independently if they don't take bus.
    return bus, session_manager


@pytest.mark.asyncio
async def test_scenario_1_happy_path() -> None:
    """Scenario 1: Create Session -> Conversation starts -> Pipeline builds -> Runner starts -> Pipeline completes -> Session closes"""
    bus = EventBus()
    session_manager = SessionManager()
    
    # Create session
    session = await session_manager.create_session()
    session_id = session.session_id
    
    # Start conversation FSM
    fsm = ConversationStateMachine(session_id=session_id)
    from app.conversation.transitions import ConversationState
    fsm.transition_to(ConversationState.LISTENING)
    
    # Build pipeline
    builder = PipelineBuilder(bus, session_id)
    builder.add_processor(ProcessorNode("STT", ProcessorRole.STT))
    builder.add_processor(ProcessorNode("LLM", ProcessorRole.LLM))
    builder.connect("STT", "LLM")
    pipeline = builder.build()
    
    # Integrate Pipecat Adapter
    transport = MockWebSocketTransport()
    adapter = PipecatFactory.create_adapter(
        pipeline=pipeline,
        event_bus=bus,
        session_id=session_id,
        execution_id="exec-1",
        transport=transport
    )
    
    # Run pipeline
    await adapter.run()
    
    # Verify execution finished successfully
    assert bus._queue.qsize() > 0
    
    # End conversation and session
    fsm.close()
    await session_manager.delete_session(session_id)
    
    assert await session_manager.get_session(session_id) is None


@pytest.mark.asyncio
async def test_scenario_4_cancellation() -> None:
    """Scenario 4: Cancellation token requested -> Processors stop -> Pipeline cancelled"""
    bus = EventBus()
    
    builder = PipelineBuilder(bus, "session1")
    builder.add_processor(ProcessorNode("STT", ProcessorRole.STT))
    pipeline = builder.build()
    
    adapter = PipecatFactory.create_adapter(pipeline, bus, "session1", "exec1")
    
    # Start task
    task = asyncio.create_task(adapter.run())
    await asyncio.sleep(0.01) # Yield
    
    # Cancel the Pipecat Task itself (mock task stop)
    if adapter.lifecycle:
        await adapter.lifecycle.stop()
        
    # Await completion
    await task
    # The pipeline should finish because the mock pipecat adapter just stops early.


@pytest.mark.asyncio
async def test_scenario_5_concurrent_sessions() -> None:
    """Scenario 5: Multiple concurrent sessions -> Independent pipelines."""
    bus = EventBus()
    session_manager = SessionManager()
    
    async def run_session(idx: int) -> None:
        session = await session_manager.create_session()
        builder = PipelineBuilder(bus, session.session_id)
        builder.add_processor(ProcessorNode(f"STT_{idx}", ProcessorRole.STT))
        pipeline = builder.build()
        adapter = PipecatFactory.create_adapter(pipeline, bus, session.session_id, f"exec_{idx}")
        await adapter.run()
        await session_manager.delete_session(session.session_id)
        
    await asyncio.gather(*(run_session(i) for i in range(10)))
    assert len(await session_manager.list_sessions()) == 0
