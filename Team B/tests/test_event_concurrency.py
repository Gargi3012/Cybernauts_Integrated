"""
Concurrency and thread-safety tests for the Event Bus and Registry.
"""

import asyncio

import pytest

from app.events.bus import EventBus
from app.events.event_types import Event, SessionCreated


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.mark.asyncio
class TestRegistryConcurrency:
    async def test_concurrent_subscriptions(self, bus: EventBus) -> None:
        """Many tasks subscribing and unsubscribing concurrently."""
        
        async def dummy_handler(e: Event) -> None:
            pass

        async def worker(idx: int) -> None:
            sub_id = await bus.subscribe("TestEvent", dummy_handler, subscriber_id=f"sub-{idx}")
            # Yield control
            await asyncio.sleep(0)
            if idx % 2 == 0:
                await bus.unsubscribe(sub_id)

        tasks = [asyncio.create_task(worker(i)) for i in range(100)]
        await asyncio.gather(*tasks)

        # 50 unsubscriptions should have happened
        count = await bus.registry.subscriber_count()
        assert count == 50


@pytest.mark.asyncio
class TestDispatcherConcurrency:
    async def test_concurrent_publishes(self, bus: EventBus) -> None:
        """Many tasks publishing events concurrently."""
        
        received_count = 0
        lock = asyncio.Lock()
        
        async def handler(e: Event) -> None:
            nonlocal received_count
            async with lock:
                received_count += 1
                
        await bus.subscribe("SessionCreated", handler)

        async def publisher() -> None:
            await bus.publish(SessionCreated(session_id="concurrent-session"))

        tasks = [asyncio.create_task(publisher()) for _ in range(100)]
        await asyncio.gather(*tasks)

        assert received_count == 100


@pytest.mark.asyncio
class TestSyncWorkerConcurrency:
    async def test_high_volume_sync_publishing(self, bus: EventBus) -> None:
        """Push many events into the sync queue simultaneously."""
        received_count = 0
        lock = asyncio.Lock()
        
        async def handler(e: Event) -> None:
            nonlocal received_count
            async with lock:
                received_count += 1
                
        await bus.subscribe("SessionCreated", handler)
        await bus.start()

        # Fire and forget 500 events
        for _ in range(500):
            bus.publish_sync(SessionCreated(session_id="sync-session"))

        # Wait for queue to drain
        async def wait_for_queue() -> None:
            while not bus._queue.empty():
                await asyncio.sleep(0.01)
            # wait a bit more for dispatching to complete
            await asyncio.sleep(0.1)
            
        await asyncio.wait_for(wait_for_queue(), timeout=5.0)
        
        await bus.stop()
        
        assert received_count == 500
