"""
Dispatcher — Executes handlers for an event.

Design Decision:
    The dispatcher is responsible solely for execution logic: iterating
    over matching subscribers, calling their handlers, catching their
    exceptions, and recording failures.  It isolates handler failures
    so that one crashing subscriber does not prevent others from running.

    Execution order is strictly sequential (awaiting one handler before
    the next) to respect priority.  Concurrent fan-out could be added
    via asyncio.gather in a future async-dispatcher if required.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from typing import List, Optional

from loguru import logger

from .event_types import Event
from .exceptions import HandlerExecutionError
from .subscriber import Subscriber


class Dispatcher:
    """Executes event handlers while isolating failures.

    Responsibilities:
        - Route an event to a list of subscribers.
        - Catch and log handler exceptions.
        - Return the IDs of one-shot subscribers that executed successfully.
    """

    async def dispatch(
        self,
        event: Event,
        subscribers: List[Subscriber],
    ) -> List[str]:
        """Execute handlers for the given event.

        Args:
            event:       The event being dispatched.
            subscribers: The priority-sorted list of matched subscribers.

        Returns:
            List of ``subscriber_id`` strings for one-shot subscribers
            that successfully executed (to be removed by the registry).

        Raises:
            HandlerExecutionError: If *any* handler failed, this is raised
                *after* all handlers have been attempted. The cause of the
                first failure is wrapped.
        """
        if not subscribers:
            return []

        executed_once_ids: List[str] = []
        first_error: Optional[Exception] = None
        error_context: Optional[tuple[str, str]] = None

        log = logger.bind(
            event_name=event.event_name,
            session_id=event.session_id,
        )

        for sub in subscribers:
            start = time.perf_counter()
            try:
                # If the handler is a coroutine function, await it.
                # If it's a sync function, we wrap it in a thread.
                # The type hint requires Awaitable, so we assume async.
                if inspect.iscoroutinefunction(sub.handler):
                    await sub.handler(event)
                else:
                    # Best-effort fallback for sync handlers
                    await asyncio.to_thread(sub.handler, event)

                elapsed = (time.perf_counter() - start) * 1000
                log.trace(
                    "Handler executed | sub_id={id} | {ms:.2f}ms",
                    id=sub.subscriber_id,
                    ms=elapsed,
                )

                if sub.once:
                    executed_once_ids.append(sub.subscriber_id)

            except Exception as e:
                elapsed = (time.perf_counter() - start) * 1000
                log.error(
                    "Handler failed | sub_id={id} | {ms:.2f}ms | error={err}",
                    id=sub.subscriber_id,
                    ms=elapsed,
                    err=str(e),
                )
                if first_error is None:
                    first_error = e
                    # For better error reporting, try to get the function name.
                    handler_name = getattr(
                        sub.handler, "__name__", str(sub.handler)
                    )
                    error_context = (handler_name, event.event_name)

        if first_error and error_context:
            h_name, e_name = error_context
            raise HandlerExecutionError(h_name, e_name, first_error)

        return executed_once_ids
