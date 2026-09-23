"""
Immutable Execution Context.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .cancellation import CancellationToken
from .metrics import MetricsCollector


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """Immutable execution context passed to every processor."""
    pipeline_id: str
    session_id: str
    execution_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)
    cancellation_token: CancellationToken = field(default_factory=CancellationToken)
    metrics_collector: MetricsCollector = field(default_factory=lambda: MetricsCollector())
    current_processor_id: Optional[str] = field(default=None)

    def with_processor(self, processor_id: str) -> ExecutionContext:
        """Create a new context scoped to a specific processor."""
        return ExecutionContext(
            pipeline_id=self.pipeline_id,
            session_id=self.session_id,
            execution_id=self.execution_id,
            start_time=self.start_time,
            metadata=self.metadata,
            cancellation_token=self.cancellation_token,
            metrics_collector=self.metrics_collector,
            current_processor_id=processor_id,
        )
