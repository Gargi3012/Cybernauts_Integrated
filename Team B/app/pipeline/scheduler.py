"""
Pipeline Scheduler for traversing the DAG.
"""

from typing import Dict, List

from app.pipeline.models import Pipeline


class PipelineScheduler:
    """Determines execution order for pipeline processors."""
    
    def __init__(self, pipeline: Pipeline) -> None:
        self._pipeline = pipeline
        self._execution_order: List[str] = self._compute_topological_sort()
        
    def _compute_topological_sort(self) -> List[str]:
        """Kahn's algorithm for topological sorting."""
        in_degree: Dict[str, int] = {node_id: 0 for node_id in self._pipeline.processors}
        
        for node_id, children in self._pipeline.graph.items():
            for child in children:
                in_degree[child] += 1
                
        queue = [node_id for node_id, degree in in_degree.items() if degree == 0]
        order = []
        
        while queue:
            node = queue.pop(0)
            order.append(node)
            
            for child in self._pipeline.graph.get(node, []):
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)
                    
        return order
        
    def get_execution_order(self) -> List[str]:
        """Return the complete sequential execution order."""
        return self._execution_order
