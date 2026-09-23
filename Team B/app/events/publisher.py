"""
Publisher — Interface for emitting events.

Design Decision:
    The Publisher is separated from the EventBus to adhere to the Interface
    Segregation Principle. Components that only produce events (like STT)
    should only receive a Publisher, not the full bus with registry access.
"""

from __future__ import annotations

from typing import List, Protocol

from .event_types import Event


class Publisher(Protocol):
    """Protocol for emitting events to the bus."""

    async def publish(self, event: Event) -> None:
        """Publish a single event asynchronously."""
        ...

    async def publish_batch(self, events: List[Event]) -> None:
        """Publish multiple events asynchronously."""
        ...

    def publish_sync(self, event: Event) -> None:
        """Publish a single event synchronously (fire and forget).

        This pushes the event into the bus's background queue.
        Useful for sync code (like HTTP endpoints) to emit events.
        """
        ...
