"""
Metrics collector for pipeline execution.
"""

import threading
import time
from typing import Dict, Any


class MetricsCollector:
    """Thread-safe metrics collection for pipeline execution."""
    
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.total_runtime: float = 0.0
        self.processor_execution_times: Dict[str, float] = {}
        self.failed_processors: int = 0
        self.completed_processors: int = 0
        self._processor_start_times: Dict[str, float] = {}
        
    def start_processor(self, processor_id: str) -> None:
        with self._lock:
            self._processor_start_times[processor_id] = time.perf_counter()
            
    def end_processor(self, processor_id: str, success: bool = True) -> None:
        with self._lock:
            start_time = self._processor_start_times.pop(processor_id, None)
            if start_time is not None:
                duration = time.perf_counter() - start_time
                self.processor_execution_times[processor_id] = self.processor_execution_times.get(processor_id, 0.0) + duration
            
            if success:
                self.completed_processors += 1
            else:
                self.failed_processors += 1
                
    def get_metrics(self) -> Dict[str, Any]:
        with self._lock:
            avg_time = 0.0
            if self.completed_processors > 0:
                total_proc_time = sum(self.processor_execution_times.values())
                avg_time = total_proc_time / self.completed_processors
                
            return {
                "total_runtime": self.total_runtime,
                "processor_execution_times": dict(self.processor_execution_times),
                "failed_processors": self.failed_processors,
                "completed_processors": self.completed_processors,
                "average_execution_time": avg_time,
                "throughput": self.completed_processors / (self.total_runtime or 1.0)
            }
