"""
Tests for Event Bus subscriber registry.
"""

import pytest

from app.events.registry import Registry
from app.events.subscriber import Subscriber
from app.events.event_types import Event


async def dummy_handler(event: Event) -> None:
    pass


@pytest.fixture
def registry() -> Registry:
    return Registry()


@pytest.mark.asyncio
class TestRegistry:
    async def test_register_subscriber(self, registry: Registry) -> None:
        sub = await registry.register("TestEvent", dummy_handler)
        assert isinstance(sub, Subscriber)
        assert sub.event_pattern == "TestEvent"
        assert sub.priority == 100
        assert not sub.once
        
        count = await registry.subscriber_count()
        assert count == 1

    async def test_register_with_custom_id(self, registry: Registry) -> None:
        sub = await registry.register(
            "TestEvent", dummy_handler, subscriber_id="sub-123"
        )
        assert sub.subscriber_id == "sub-123"

    async def test_unregister(self, registry: Registry) -> None:
        sub = await registry.register("TestEvent", dummy_handler)
        removed = await registry.unregister(sub.subscriber_id)
        assert removed is True
        assert await registry.subscriber_count() == 0

    async def test_unregister_not_found(self, registry: Registry) -> None:
        removed = await registry.unregister("bogus-id")
        assert removed is False

    async def test_clear(self, registry: Registry) -> None:
        await registry.register("Event1", dummy_handler)
        await registry.register("Event2", dummy_handler)
        await registry.clear()
        assert await registry.subscriber_count() == 0

    async def test_get_matching_exact(self, registry: Registry) -> None:
        await registry.register("TestEvent", dummy_handler)
        await registry.register("OtherEvent", dummy_handler)
        
        matches = await registry.get_matching("TestEvent")
        assert len(matches) == 1
        assert matches[0].event_pattern == "TestEvent"

    async def test_get_matching_wildcard(self, registry: Registry) -> None:
        await registry.register("Conversation*", dummy_handler)
        await registry.register("Session*", dummy_handler)
        
        matches = await registry.get_matching("ConversationStarted")
        assert len(matches) == 1
        assert matches[0].event_pattern == "Conversation*"

    async def test_priority_sorting(self, registry: Registry) -> None:
        await registry.register("TestEvent", dummy_handler, priority=50)
        await registry.register("TestEvent", dummy_handler, priority=10)
        await registry.register("TestEvent", dummy_handler, priority=100)
        
        matches = await registry.get_matching("TestEvent")
        assert len(matches) == 3
        assert matches[0].priority == 10
        assert matches[1].priority == 50
        assert matches[2].priority == 100

    async def test_remove_once_subscribers(self, registry: Registry) -> None:
        sub1 = await registry.register("TestEvent", dummy_handler, once=True)
        sub2 = await registry.register("TestEvent", dummy_handler)
        
        await registry.remove_once_subscribers([sub1.subscriber_id])
        
        assert await registry.subscriber_count() == 1
        remaining = await registry.list_subscribers()
        assert remaining[0].subscriber_id == sub2.subscriber_id
