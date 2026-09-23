"""
Handler type aliases and utilities.

Design Decision:
    Handlers are plain async callables: ``async def handler(event: Event) -> None``.
    No base class or decorator magic — any async function with the right
    signature works.  This keeps the barrier to entry minimal and makes
    testing trivial (just pass a coroutine).
"""

from __future__ import annotations

from typing import Awaitable, Callable

from .event_types import Event

# The canonical handler signature: takes an Event, returns nothing.
EventHandler = Callable[[Event], Awaitable[None]]
