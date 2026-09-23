"""
Tests for Event Bus Middleware.
"""

import pytest

from app.events.event_types import Event, SessionCreated
from app.events.middleware import LoggingMiddleware, MetricsMiddleware, NextFn


@pytest.fixture
def event() -> Event:
    return SessionCreated(session_id="test-session")


@pytest.mark.asyncio
class TestMiddlewares:
    async def test_logging_middleware(self, event: Event) -> None:
        mw = LoggingMiddleware()
        called = False
        
        async def call_next(e: Event) -> None:
            nonlocal called
            called = True
            
        await mw(event, call_next)
        assert called is True

    async def test_metrics_middleware_success(self, event: Event) -> None:
        mw = MetricsMiddleware()
        
        async def call_next(e: Event) -> None:
            pass
            
        await mw(event, call_next)
        
        assert mw.stats["events_published"] == 1
        assert mw.stats["events_failed"] == 0
        assert mw.stats["total_dispatch_ms"] > 0

    async def test_metrics_middleware_failure(self, event: Event) -> None:
        mw = MetricsMiddleware()
        
        async def call_next(e: Event) -> None:
            raise ValueError("Boom")
            
        with pytest.raises(ValueError):
            await mw(event, call_next)
            
        assert mw.stats["events_published"] == 0
        assert mw.stats["events_failed"] == 1
        assert mw.stats["total_dispatch_ms"] > 0

    async def test_middleware_short_circuit(self, event: Event) -> None:
        """A middleware that doesn't call next_fn stops the chain."""
        class BlockMiddleware:
            async def __call__(self, e: Event, next_fn: NextFn) -> None:
                pass # short circuit
                
        mw = BlockMiddleware()
        called = False
        
        async def call_next(e: Event) -> None:
            nonlocal called
            called = True
            
        await mw(event, call_next)
        assert called is False
