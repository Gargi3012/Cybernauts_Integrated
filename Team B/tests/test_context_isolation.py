"""
Tests for Execution Context and Metrics isolation.
Ensures that each execution captures only its own data.
"""

from app.pipeline.context import ExecutionContext


def test_metrics_isolation() -> None:
    """Verify metrics collectors are isolated per execution context."""
    ctx1 = ExecutionContext(execution_id="1", pipeline_id="p1", session_id="s1")
    ctx2 = ExecutionContext(execution_id="2", pipeline_id="p2", session_id="s2")
    
    # Record metrics for ctx1
    ctx1.metrics_collector.start_processor("STT")
    ctx1.metrics_collector.end_processor("STT", success=True)
    
    # Record metrics for ctx2
    ctx2.metrics_collector.start_processor("LLM")
    ctx2.metrics_collector.end_processor("LLM", success=True)
    
    # Assert isolation
    assert "STT" in ctx1.metrics_collector.processor_execution_times
    assert "LLM" not in ctx1.metrics_collector.processor_execution_times
    
    assert "LLM" in ctx2.metrics_collector.processor_execution_times
    assert "STT" not in ctx2.metrics_collector.processor_execution_times


def test_context_metadata_isolation() -> None:
    """Verify execution metadata is not shared."""
    ctx1 = ExecutionContext(execution_id="1", pipeline_id="p", session_id="s")
    ctx2 = ExecutionContext(execution_id="2", pipeline_id="p", session_id="s")
    
    ctx1.metadata["test"] = "data"
    assert "test" not in ctx2.metadata
