"""
Registry — Runtime index of subscribers.

Design Decision:
    The Registry is the single mutable store of subscriptions.  The
    EventBus delegates all subscribe/unsubscribe/lookup here so that
    the bus itself stays focused on orchestration.  An asyncio.Lock
    guards mutations for coroutine safety.
"""

from __future__ import annotations

import asyncio
from typing import List

from loguru import logger

from .handlers import EventHandler
from .subscriber import Subscriber


class Registry:
    """Thread-safe / async-safe subscriber registry.

    Responsibilities:
        - Register and deregister subscribers.
        - Look up matching subscribers for a given event name.
        - Provide introspection APIs (list, count).
    """

    __slots__ = ("_subscribers", "_lock")

    def __init__(self) -> None:
        self._subscribers: List[Subscriber] = []
        self._lock: asyncio.Lock = asyncio.Lock()

    # ==================================================================
    #  Registration
    # ==================================================================

    async def register(
        self,
        event_pattern: str,
        handler: EventHandler,
        priority: int = 100,
        once: bool = False,
        subscriber_id: str = "",
    ) -> Subscriber:
        """Create and register a subscriber.

        Args:
            event_pattern: Exact event name or glob (``"Pipeline*"``).
            handler:       Async callable to invoke on match.
            priority:      Lower = higher priority (default 100).
            once:          Auto-remove after first delivery.
            subscriber_id: Optional custom ID; auto-generated if empty.

        Returns:
            The registered ``Subscriber`` instance.
        """
        kwargs: dict[str, object] = {
            "event_pattern": event_pattern,
            "handler": handler,
            "priority": priority,
            "once": once,
        }
        if subscriber_id:
            kwargs["subscriber_id"] = subscriber_id

        sub = Subscriber(**kwargs)  # type: ignore[arg-type]

        async with self._lock:
            self._subscribers.append(sub)

        logger.bind(
            subscriber_id=sub.subscriber_id,
            pattern=event_pattern,
        ).debug("Subscriber registered | priority={p}", p=priority)
        return sub

    async def unregister(self, subscriber_id: str) -> bool:
        """Remove a subscriber by ID.

        Returns:
            ``True`` if found and removed, ``False`` otherwise.
        """
        async with self._lock:
            before = len(self._subscribers)
            self._subscribers = [
                s for s in self._subscribers
                if s.subscriber_id != subscriber_id
            ]
            removed = len(self._subscribers) < before

        if removed:
            logger.bind(subscriber_id=subscriber_id).debug(
                "Subscriber unregistered"
            )
        return removed

    async def remove_once_subscribers(self, ids: List[str]) -> None:
        """Batch-remove one-shot subscribers after delivery."""
        if not ids:
            return
        id_set = set(ids)
        async with self._lock:
            self._subscribers = [
                s for s in self._subscribers
                if s.subscriber_id not in id_set
            ]

    # ==================================================================
    #  Lookup
    # ==================================================================

    async def get_matching(self, event_name: str) -> List[Subscriber]:
        """Return subscribers matching ``event_name``, sorted by priority.

        Args:
            event_name: The canonical event class name.

        Returns:
            Priority-sorted list of matching ``Subscriber`` objects.
        """
        async with self._lock:
            matches = [
                s for s in self._subscribers if s.matches(event_name)
            ]
        return sorted(matches, key=lambda s: s.priority)

    # ==================================================================
    #  Introspection
    # ==================================================================

    async def list_subscribers(self) -> List[Subscriber]:
        """Return a copy of all registered subscribers."""
        async with self._lock:
            return list(self._subscribers)

    async def subscriber_count(self) -> int:
        """Return the total number of registered subscribers."""
        async with self._lock:
            return len(self._subscribers)

    async def clear(self) -> None:
        """Remove all subscribers."""
        async with self._lock:
            self._subscribers.clear()
        logger.debug("Registry cleared — all subscribers removed")
