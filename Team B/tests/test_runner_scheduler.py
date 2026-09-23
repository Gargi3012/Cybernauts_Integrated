"""
Tests for PipelineScheduler.
"""

from app.pipeline.models import Pipeline
from app.pipeline.processors import ProcessorNode, ProcessorRole
from app.pipeline.scheduler import PipelineScheduler


def test_topological_sort() -> None:
    processors = {
        "A": ProcessorNode("A", ProcessorRole.TRANSPORT_INPUT),
        "B": ProcessorNode("B", ProcessorRole.LLM),
        "C": ProcessorNode("C", ProcessorRole.TTS),
        "D": ProcessorNode("D", ProcessorRole.TRANSPORT_OUTPUT),
    }
    # A -> B -> C -> D
    graph = {
        "A": ["B"],
        "B": ["C"],
        "C": ["D"],
        "D": []
    }
    pipeline = Pipeline(processors=processors, graph=graph)
    scheduler = PipelineScheduler(pipeline)
    
    order = scheduler.get_execution_order()
    assert order == ["A", "B", "C", "D"]


def test_topological_sort_branching() -> None:
    processors = {
        "Root": ProcessorNode("Root", ProcessorRole.TRANSPORT_INPUT),
        "Branch1": ProcessorNode("Branch1", ProcessorRole.CUSTOM),
        "Branch2": ProcessorNode("Branch2", ProcessorRole.CUSTOM),
        "Join": ProcessorNode("Join", ProcessorRole.TRANSPORT_OUTPUT),
    }
    graph = {
        "Root": ["Branch1", "Branch2"],
        "Branch1": ["Join"],
        "Branch2": ["Join"],
        "Join": []
    }
    pipeline = Pipeline(processors=processors, graph=graph)
    scheduler = PipelineScheduler(pipeline)
    
    order = scheduler.get_execution_order()
    assert order[0] == "Root"
    assert set(order[1:3]) == {"Branch1", "Branch2"}
    assert order[3] == "Join"
