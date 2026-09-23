"""
Performance benchmarks and memory leak tests for the Event Bus.
"""

import time
import tracemalloc

import pytest

from app.events.bus import EventBus
from app.events.event_types import Event, SessionCreated


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.mark.asyncio
class TestPublishPerformance:
    async def test_publish_1000_events(self, bus: EventBus) -> None:
        """Benchmark: Publish 1000 events to a single subscriber."""
        
        count = 0
        async def handler(e: Event) -> None:
            nonlocal count
            count += 1
            
        await bus.subscribe("SessionCreated", handler)
        
        events = [SessionCreated(session_id=f"session-{i}") for i in range(1000)]
        
        start = time.perf_counter()
        await bus.publish_batch(events)
        elapsed = time.perf_counter() - start
        
        assert count == 1000
        # Should be well under 1 second for 1000 events in memory
        assert elapsed < 1.0


@pytest.mark.asyncio
class TestFanoutPerformance:
    async def test_fanout_100_subscribers(self, bus: EventBus) -> None:
        """Benchmark: Publish 1 event to 100 subscribers."""
        
        count = 0
        async def handler(e: Event) -> None:
            nonlocal count
            count += 1
            
        for _ in range(100):
            await bus.subscribe("SessionCreated", handler)
            
        start = time.perf_counter()
        await bus.publish(SessionCreated(session_id="fanout-session"))
        elapsed = time.perf_counter() - start
        
        assert count == 100
        assert elapsed < 0.5


@pytest.mark.asyncio
class TestMemoryLeak:
    async def test_create_dispatch_cycle(self) -> None:
        """Ensure repeated publish/subscribe cycles don't leak memory."""
        tracemalloc.start()
        
        bus = EventBus()
        
        async def handler(e: Event) -> None:
            pass
            
        sub_id = await bus.subscribe("SessionCreated", handler)
        
        # Warmup
        for _ in range(1000):
            await bus.publish(SessionCreated(session_id="warmup"))
            
        snapshot1 = tracemalloc.take_snapshot()
        
        # Test loop
        for _ in range(5000):
            await bus.publish(SessionCreated(session_id="leak-test"))
            
        snapshot2 = tracemalloc.take_snapshot()
        tracemalloc.stop()
        
        # Compare memory
        stats = snapshot2.compare_to(snapshot1, "lineno")
        total_diff_kb = sum(stat.size_diff for stat in stats) / 1024
        
        # Allow up to 5000KB fluctuation for internal Python caches,
        # but prevent unbounded growth.
        assert total_diff_kb < 5000.0
