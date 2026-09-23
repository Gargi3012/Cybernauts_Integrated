"""
Middleware — Pluggable pre-processing pipeline for events.

Design Decision:
    Middleware follows the chain-of-responsibility pattern.  Each middleware
    receives the event and an async ``call_next`` function.  It can:
      - Inspect/log the event before passing it on
      - Modify metadata (e.g., add tracing IDs)
      - Short-circuit by NOT calling ``call_next``
      - Measure elapsed time around ``call_next``

    Middlewares are registered in order and composed into a single chain
    by the EventBus before dispatch.
"""

from __future__ import annotations

import time
from typing import Awaitable, Callable, Protocol

from loguru import logger

from .event_types import Event

# Type for the "call next middleware / dispatch" continuation.
NextFn = Callable[[Event], Awaitable[None]]


class Middleware(Protocol):
    """Protocol that all middleware must implement.

    A middleware is any async callable with signature::

        async def __call__(self, event: Event, call_next: NextFn) -> None

    Call ``await call_next(event)`` to continue the chain.
    """

    async def __call__(self, event: Event, call_next: NextFn) -> None: ...


# ──────────────────────────────────────────────────────────────────────
# Built-in middlewares
# ──────────────────────────────────────────────────────────────────────

class LoggingMiddleware:
    """Logs every event before and after dispatch with timing."""

    async def __call__(self, event: Event, call_next: NextFn) -> None:
        log = logger.bind(
            event_name=event.event_name,
            event_id=event.event_id,
            session_id=event.session_id,
        )
        log.debug("Event received by bus")
        start = time.perf_counter()
        await call_next(event)
        elapsed_ms = (time.perf_counter() - start) * 1000
        log.debug(
            "Event dispatched | elapsed={ms:.2f}ms",
            ms=elapsed_ms,
        )


class MetricsMiddleware:
    """Tracks event counts and dispatch latency in an in-memory dict.

    Access metrics via the ``stats`` attribute.
    """

    def __init__(self) -> None:
        self.stats: dict[str, int | float] = {
            "events_published": 0,
            "events_failed": 0,
            "total_dispatch_ms": 0.0,
        }

    async def __call__(self, event: Event, call_next: NextFn) -> None:
        start = time.perf_counter()
        try:
            await call_next(event)
            count = int(self.stats["events_published"])
            self.stats["events_published"] = count + 1
        except Exception:
            count = int(self.stats["events_failed"])
            self.stats["events_failed"] = count + 1
            raise
        finally:
            elapsed = (time.perf_counter() - start) * 1000
            total = float(self.stats["total_dispatch_ms"])
            self.stats["total_dispatch_ms"] = total + elapsed
