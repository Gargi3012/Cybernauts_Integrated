"""
Custom exceptions for the Event Bus.
"""

from __future__ import annotations


class EventBusError(Exception):
    """Base exception for all Event Bus errors."""


class DuplicateSubscriberError(EventBusError):
    """A subscriber with this ID is already registered."""

    def __init__(self, subscriber_id: str) -> None:
        self.subscriber_id = subscriber_id
        super().__init__(f"Subscriber already registered: '{subscriber_id}'")


class EventNotRegisteredError(EventBusError):
    """An event type was published that has no registered subscribers."""

    def __init__(self, event_name: str) -> None:
        self.event_name = event_name
        super().__init__(f"No subscribers for event: '{event_name}'")


class HandlerExecutionError(EventBusError):
    """A handler raised an exception during execution."""

    def __init__(
        self, handler_name: str, event_name: str, cause: Exception
    ) -> None:
        self.handler_name = handler_name
        self.event_name = event_name
        self.cause = cause
        super().__init__(
            f"Handler '{handler_name}' failed on '{event_name}': {cause}"
        )


class MiddlewareError(EventBusError):
    """A middleware raised during event processing."""

    def __init__(self, middleware_name: str, cause: Exception) -> None:
        self.middleware_name = middleware_name
        self.cause = cause
        super().__init__(f"Middleware '{middleware_name}' failed: {cause}")


class DispatchError(EventBusError):
    """The dispatcher failed to route an event."""

    def __init__(self, event_name: str, cause: Exception) -> None:
        self.event_name = event_name
        self.cause = cause
        super().__init__(f"Dispatch failed for '{event_name}': {cause}")
