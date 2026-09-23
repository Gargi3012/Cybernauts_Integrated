"""
Tests for Event Bus dispatcher.
"""

import pytest

from app.events.dispatcher import Dispatcher
from app.events.event_types import Event, SessionCreated
from app.events.exceptions import HandlerExecutionError
from app.events.subscriber import Subscriber


@pytest.fixture
def dispatcher() -> Dispatcher:
    return Dispatcher()


@pytest.fixture
def event() -> Event:
    return SessionCreated(session_id="test-session")


@pytest.mark.asyncio
class TestDispatcher:
    async def test_successful_dispatch(self, dispatcher: Dispatcher, event: Event) -> None:
        called = False
        
        async def handler(e: Event) -> None:
            nonlocal called
            called = True
            
        sub = Subscriber(handler=handler, event_pattern="SessionCreated")
        once_ids = await dispatcher.dispatch(event, [sub])
        
        assert called is True
        assert once_ids == []

    async def test_one_shot_subscriber_returns_id(
        self, dispatcher: Dispatcher, event: Event
    ) -> None:
        async def handler(e: Event) -> None:
            pass
            
        sub = Subscriber(handler=handler, event_pattern="SessionCreated", once=True)
        once_ids = await dispatcher.dispatch(event, [sub])
        
        assert once_ids == [sub.subscriber_id]

    async def test_sync_handler_fallback(
        self, dispatcher: Dispatcher, event: Event
    ) -> None:
        called = False
        
        def sync_handler(e: Event) -> None:
            nonlocal called
            called = True
            
        sub = Subscriber(handler=sync_handler, event_pattern="SessionCreated")  # type: ignore[arg-type]
        await dispatcher.dispatch(event, [sub])
        
        assert called is True

    async def test_handler_error_isolation(
        self, dispatcher: Dispatcher, event: Event
    ) -> None:
        calls = []
        
        async def failing_handler(e: Event) -> None:
            calls.append("fail")
            raise ValueError("Boom")
            
        async def success_handler(e: Event) -> None:
            calls.append("success")
            
        sub1 = Subscriber(handler=failing_handler, event_pattern="*", priority=10)
        sub2 = Subscriber(handler=success_handler, event_pattern="*", priority=20)
        
        with pytest.raises(HandlerExecutionError) as exc_info:
            await dispatcher.dispatch(event, [sub1, sub2])
            
        # Both handlers should have been attempted, despite the first failing
        assert calls == ["fail", "success"]
        
        err = exc_info.value
        assert "failing_handler" in str(err)
        assert isinstance(err.cause, ValueError)

    async def test_empty_subscribers(self, dispatcher: Dispatcher, event: Event) -> None:
        once_ids = await dispatcher.dispatch(event, [])
        assert once_ids == []
