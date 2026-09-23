"""
Tests for MetricsCollector.
"""

import time
from app.pipeline.metrics import MetricsCollector


def test_metrics_collection() -> None:
    collector = MetricsCollector()
    
    collector.start_processor("p1")
    time.sleep(0.01)
    collector.end_processor("p1", success=True)
    
    collector.start_processor("p2")
    collector.end_processor("p2", success=False)
    
    metrics = collector.get_metrics()
    assert metrics["completed_processors"] == 1
    assert metrics["failed_processors"] == 1
    assert "p1" in metrics["processor_execution_times"]
    assert "p2" in metrics["processor_execution_times"]
    assert metrics["processor_execution_times"]["p1"] >= 0.01
    assert metrics["average_execution_time"] > 0
    assert metrics["throughput"] > 0
