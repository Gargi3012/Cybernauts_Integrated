"""
Tests for PipelineGraph DAG management.
"""

import pytest

from app.pipeline.exceptions import CircularDependencyError
from app.pipeline.graph import PipelineGraph


def test_add_remove_node() -> None:
    g = PipelineGraph()
    g.add_node("A")
    assert "A" in g.get_adjacency_list()
    
    g.remove_node("A")
    assert "A" not in g.get_adjacency_list()


def test_add_edge() -> None:
    g = PipelineGraph()
    g.add_edge("A", "B")
    adj = g.get_adjacency_list()
    assert "B" in adj["A"]
    assert "A" in adj
    assert "B" in adj


def test_remove_node_cleans_edges() -> None:
    g = PipelineGraph()
    g.add_edge("A", "B")
    g.add_edge("B", "C")
    g.remove_node("B")
    
    adj = g.get_adjacency_list()
    assert "B" not in adj
    assert "B" not in adj["A"]
    assert "C" in adj


def test_find_roots() -> None:
    g = PipelineGraph()
    g.add_edge("A", "B")
    g.add_edge("B", "C")
    g.add_edge("D", "B")
    
    roots = g.find_roots()
    assert set(roots) == {"A", "D"}


def test_cycle_detection() -> None:
    g = PipelineGraph()
    g.add_edge("A", "B")
    g.add_edge("B", "C")
    
    with pytest.raises(CircularDependencyError):
        g.add_edge("C", "A")
        
    # Ensure graph state is rolled back
    assert "A" not in g.get_adjacency_list()["C"]
