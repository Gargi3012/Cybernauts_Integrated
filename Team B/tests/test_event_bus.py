"""
Integration tests for the main EventBus class.
"""

import asyncio

import pytest

from app.events.bus import EventBus
from app.events.event_types import Event, SessionCreated, ConversationStarted
from app.events.exceptions import MiddlewareError
from app.events.middleware import NextFn


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def event() -> Event:
    return SessionCreated(session_id="test-session")


@pytest.mark.asyncio
class TestEventBus:
    async def test_publish_no_subscribers(self, bus: EventBus, event: Event) -> None:
        # Should not raise, just return
        await bus.publish(event)

    async def test_publish_with_subscribers(self, bus: EventBus, event: Event) -> None:
        calls = []
        
        async def handler1(e: Event) -> None:
            calls.append("h1")
            
        async def handler2(e: Event) -> None:
            calls.append("h2")
            
        await bus.subscribe("SessionCreated", handler1, priority=10)
        await bus.subscribe("SessionCreated", handler2, priority=20)
        
        await bus.publish(event)
        assert calls == ["h1", "h2"]

    async def test_publish_batch(self, bus: EventBus) -> None:
        calls = 0
        
        async def handler(e: Event) -> None:
            nonlocal calls
            calls += 1
            
        await bus.subscribe("*", handler)
        
        events = [
            SessionCreated(session_id="1"),
            ConversationStarted(session_id="1")
        ]
        
        await bus.publish_batch(events)
        assert calls == 2

    async def test_publish_sync_background_worker(self, bus: EventBus, event: Event) -> None:
        called = asyncio.Event()
        
        async def handler(e: Event) -> None:
            called.set()
            
        await bus.subscribe("SessionCreated", handler)
        
        await bus.start()
        bus.publish_sync(event)
        
        await asyncio.wait_for(called.wait(), timeout=1.0)
        await bus.stop()
        
    async def test_middleware_chain(self, bus: EventBus, event: Event) -> None:
        chain = []
        
        class Middleware1:
            async def __call__(self, e: Event, next_fn: NextFn) -> None:
                chain.append("m1_start")
                await next_fn(e)
                chain.append("m1_end")
                
        class Middleware2:
            async def __call__(self, e: Event, next_fn: NextFn) -> None:
                chain.append("m2_start")
                await next_fn(e)
                chain.append("m2_end")
                
        bus.add_middleware(Middleware1())
        bus.add_middleware(Middleware2())
        
        async def handler(e: Event) -> None:
            chain.append("handler")
            
        await bus.subscribe("SessionCreated", handler)
        
        await bus.publish(event)
        
        assert chain == [
            "m1_start",
            "m2_start",
            "handler",
            "m2_end",
            "m1_end"
        ]

    async def test_middleware_error_wrapping(self, bus: EventBus, event: Event) -> None:
        class FailingMiddleware:
            async def __call__(self, e: Event, next_fn: NextFn) -> None:
                raise ValueError("Oops")
                
        bus.add_middleware(FailingMiddleware())
        
        async def handler(e: Event) -> None:
            pass
            
        await bus.subscribe("SessionCreated", handler)
        
        with pytest.raises(MiddlewareError) as exc_info:
            await bus.publish(event)
            
        assert "FailingMiddleware" in str(exc_info.value)
