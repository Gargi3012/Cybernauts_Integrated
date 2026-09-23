"""
Tests for Reference Integrity.
Validates that no mutable objects are shared across instances.
"""

from app.session.models import Session
from app.pipeline.context import ExecutionContext


def test_session_reference_integrity() -> None:
    """Verify no mutable objects are shared across Session instances."""
    s1 = Session()
    s2 = Session()
    
    assert s1.history is not s2.history
    assert s1.metadata is not s2.metadata
    assert s1.latency is not s2.latency
    
    s1.metadata["key"] = "val"
    assert "key" not in s2.metadata


def test_execution_context_reference_integrity() -> None:
    """Verify ExecutionContext object integrity."""
    ctx1 = ExecutionContext(execution_id="1", pipeline_id="p1", session_id="s1")
    ctx2 = ExecutionContext(execution_id="2", pipeline_id="p2", session_id="s2")
    
    assert ctx1.metrics_collector is not ctx2.metrics_collector
    assert ctx1.cancellation_token is not ctx2.cancellation_token
    assert ctx1.metadata is not ctx2.metadata
    
    ctx1.metadata["test"] = True
    assert "test" not in ctx2.metadata
