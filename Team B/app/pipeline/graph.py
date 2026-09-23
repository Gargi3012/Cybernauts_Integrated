"""
Pipeline Graph utility.

Internal mutable graph used by the builder to manage topology.
"""

from __future__ import annotations

from typing import Dict, List, Set

from .exceptions import CircularDependencyError


class PipelineGraph:
    """Manages the DAG topology of pipeline processors."""
    
    def __init__(self) -> None:
        # Adjacency list: node_id -> list of child node_ids
        self._adj: Dict[str, List[str]] = {}
        self._nodes: Set[str] = set()
        
    def add_node(self, node_id: str) -> None:
        if node_id not in self._nodes:
            self._nodes.add(node_id)
            self._adj[node_id] = []
            
    def remove_node(self, node_id: str) -> None:
        if node_id in self._nodes:
            self._nodes.remove(node_id)
            del self._adj[node_id]
            for children in self._adj.values():
                if node_id in children:
                    children.remove(node_id)
                    
    def add_edge(self, from_id: str, to_id: str) -> None:
        """Add a directed edge from one node to another."""
        self.add_node(from_id)
        self.add_node(to_id)
        if to_id not in self._adj[from_id]:
            self._adj[from_id].append(to_id)
            
        # Check for cycles immediately
        if self._has_cycle():
            # Rollback
            self._adj[from_id].remove(to_id)
            raise CircularDependencyError(f"Edge {from_id}->{to_id} creates a cycle.")
            
    def remove_edge(self, from_id: str, to_id: str) -> None:
        if from_id in self._adj and to_id in self._adj[from_id]:
            self._adj[from_id].remove(to_id)

    def get_adjacency_list(self) -> Dict[str, List[str]]:
        """Return a copy of the graph."""
        return {k: list(v) for k, v in self._adj.items()}

    def find_roots(self) -> List[str]:
        """Find nodes with zero in-degree."""
        in_degrees = {node: 0 for node in self._nodes}
        for children in self._adj.values():
            for child in children:
                in_degrees[child] += 1
        return [node for node, degree in in_degrees.items() if degree == 0]

    def _has_cycle(self) -> bool:
        """Detect cycles using DFS."""
        visited: Set[str] = set()
        rec_stack: Set[str] = set()

        def dfs(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)
            for neighbor in self._adj.get(node, []):
                if neighbor not in visited:
                    if dfs(neighbor):
                        return True
                elif neighbor in rec_stack:
                    return True
            rec_stack.remove(node)
            return False

        for n in self._nodes:
            if n not in visited:
                if dfs(n):
                    return True
        return False
