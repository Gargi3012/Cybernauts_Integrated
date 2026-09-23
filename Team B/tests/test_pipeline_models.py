"""
Tests for immutable Pipeline and Processor models.
"""

from app.pipeline.models import Pipeline
from app.pipeline.processors import ProcessorNode, ProcessorRole


def test_processor_to_dict() -> None:
    p = ProcessorNode("id1", ProcessorRole.LLM, "MyLLM", {"temp": 0.7})
    d = p.to_dict()
    assert d == {
        "processor_id": "id1",
        "role": "llm",
        "name": "MyLLM",
        "metadata": {"temp": 0.7}
    }


def test_pipeline_serialization_and_clone() -> None:
    p = ProcessorNode("id1", ProcessorRole.LLM)
    pipe = Pipeline(processors={"id1": p}, graph={"id1": []}, metadata={"version": 1})
    
    d = pipe.to_dict()
    assert d["pipeline_id"] == pipe.pipeline_id
    assert d["processors"]["id1"]["role"] == "llm"
    assert d["metadata"] == {"version": 1}
    
    clone = pipe.clone()
    assert clone.pipeline_id != pipe.pipeline_id
    assert clone.processors == pipe.processors
    assert clone.graph == pipe.graph
    assert clone.metadata == pipe.metadata
