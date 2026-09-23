"""
Tests for Pipeline JSON serialization.
"""

from app.pipeline.models import Pipeline
from app.pipeline.processors import ProcessorNode, ProcessorRole
from app.pipeline.serializer import PipelineSerializer


def test_serialize_deserialize() -> None:
    p1 = ProcessorNode("in", ProcessorRole.TRANSPORT_INPUT)
    p2 = ProcessorNode("out", ProcessorRole.TRANSPORT_OUTPUT)
    
    original = Pipeline(
        processors={"in": p1, "out": p2},
        graph={"in": ["out"], "out": []}
    )
    
    json_str = PipelineSerializer.to_json(original)
    assert isinstance(json_str, str)
    assert "TRANSPORT_INPUT" not in json_str # Enum value is used, so "transport_input"
    assert "transport_input" in json_str
    
    restored = PipelineSerializer.from_json(json_str)
    
    assert restored.pipeline_id == original.pipeline_id
    assert restored.graph == original.graph
    assert len(restored.processors) == 2
    assert restored.processors["in"].role == ProcessorRole.TRANSPORT_INPUT
    assert restored.created_at == original.created_at
