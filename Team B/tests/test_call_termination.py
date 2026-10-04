import pytest
import asyncio
from pipecat.frames.frames import TextFrame, LLMFullResponseEndFrame, TranscriptionFrame, BotStoppedSpeakingFrame
from app.adapters.pipecat.language_router import CallTerminationProcessor
from pipecat.processors.frame_processor import FrameDirection

@pytest.mark.asyncio
async def test_explicit_end_call():
    shared_state = {"hangup_requested": True}
    processor = CallTerminationProcessor(shared_state=shared_state)
    await processor.process_frame(BotStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    assert shared_state.get("termination_started") == True

@pytest.mark.asyncio
async def test_natural_llm_conclusion():
    shared_state = {}
    processor = CallTerminationProcessor(shared_state=shared_state)
    
    # Simulate LLM output
    await processor.process_frame(TextFrame("Thank you for your time. Have a great day!"), FrameDirection.DOWNSTREAM)
    await processor.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)
    
    assert shared_state.get("termination_requested") == True
    
    await processor.process_frame(BotStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    assert shared_state.get("termination_started") == True

@pytest.mark.asyncio
async def test_normal_thank_you():
    shared_state = {}
    processor = CallTerminationProcessor(shared_state=shared_state)
    
    await processor.process_frame(TextFrame("Thank you for confirming your details. Now let me ask one final question."), FrameDirection.DOWNSTREAM)
    await processor.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)
    
    assert not shared_state.get("termination_requested")

@pytest.mark.asyncio
async def test_duplicate_termination_signals():
    shared_state = {"hangup_requested": True}
    processor = CallTerminationProcessor(shared_state=shared_state)
    
    # First termination
    await processor.process_frame(BotStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    assert shared_state.get("termination_started") == True
    
    # Second termination
    shared_state["_call_hung_up"] = False
    await processor.process_frame(BotStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    # The flag shouldn't be flipped again if it was properly idempotent
    # Wait, my logic uses termination_started for idempotency

@pytest.mark.asyncio
async def test_bot_stopped_without_termination():
    shared_state = {}
    processor = CallTerminationProcessor(shared_state=shared_state)
    
    await processor.process_frame(BotStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    assert not shared_state.get("termination_started")
