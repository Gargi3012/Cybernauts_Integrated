"""
Subscriber — Registration model for event handlers.

Design Decision:
    A Subscriber is a frozen dataclass pairing an event pattern with a
    handler.  Patterns support exact match (``"TranscriptReady"``) and
    wildcard prefix (``"Conversation*"``).  Priority ordering ensures
    deterministic dispatch.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from fnmatch import fnmatch

from .handlers import EventHandler


@dataclass(frozen=True, slots=True)
class Subscriber:
    """A registered event handler with pattern, priority, and one-shot flag.

    Attributes:
        subscriber_id: Unique ID for unsubscribe operations.
        event_pattern: Exact event name or glob pattern (e.g. ``"Pipeline*"``).
        handler:       Async callable invoked when a matching event arrives.
        priority:      Lower values execute first (default 100).
        once:          If True, the subscriber auto-removes after first delivery.
    """

    handler: EventHandler
    event_pattern: str
    subscriber_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    priority: int = 100
    once: bool = False

    def matches(self, event_name: str) -> bool:
        """Return True if ``event_name`` matches this subscriber's pattern.

        Supports exact match and glob wildcards (``*``, ``?``).

        Args:
            event_name: The canonical name of the event (class name).
        """
        return fnmatch(event_name, self.event_pattern)
