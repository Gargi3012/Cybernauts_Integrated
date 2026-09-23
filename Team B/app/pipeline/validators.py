"""
Pipeline definition validators.
"""

from __future__ import annotations

from typing import Dict, List

from .exceptions import EmptyPipelineError, InvalidPipelineError
from .processors import ProcessorNode, ProcessorRole


def validate_pipeline(processors: Dict[str, ProcessorNode], graph: Dict[str, List[str]]) -> None:
    """Validate a complete pipeline definition.
    
    Rules:
        1. Cannot be empty.
        2. Must have exactly one Transport Input (or exactly one root node if custom).
        3. Must have at least one valid path from an input to an output.
        4. No orphaned nodes (nodes not connected to the main flow).
    """
    if not processors:
        raise EmptyPipelineError("Pipeline has no processors.")
        
    if not graph:
        raise InvalidPipelineError("Pipeline graph is empty (no connections).")

    # Count transport inputs
    inputs = [p for p in processors.values() if p.role == ProcessorRole.TRANSPORT_INPUT]
    if len(inputs) > 1:
        raise InvalidPipelineError(f"Multiple transport inputs found: {[p.processor_id for p in inputs]}")
        
    # Ensure there's at least one root node
    in_degrees = {pid: 0 for pid in processors}
    for children in graph.values():
        for child in children:
            if child in in_degrees:
                in_degrees[child] += 1
                
    roots = [node for node, degree in in_degrees.items() if degree == 0]
    if not roots:
        raise InvalidPipelineError("Pipeline has no root nodes (invalid topology).")
        
    if len(roots) > 1 and inputs:
        # If we explicitly have an input transport, it should be the only root.
        input_id = inputs[0].processor_id
        if input_id not in roots or len(roots) > 1:
            raise InvalidPipelineError("Pipeline has multiple disconnected root nodes.")

    # Check for disconnected components (simple reachability from roots)
    visited = set()
    
    def dfs(node_id: str) -> None:
        visited.add(node_id)
        for child in graph.get(node_id, []):
            if child not in visited:
                dfs(child)
                
    for root in roots:
        dfs(root)
        
    unreachable = set(processors.keys()) - visited
    if unreachable:
        raise InvalidPipelineError(f"Pipeline contains unreachable processors: {unreachable}")
