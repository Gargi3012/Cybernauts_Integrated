"""
Tests for PipelineBuilder.
"""

import pytest

from app.events import EventBus
from app.pipeline.builder import PipelineBuilder
from app.pipeline.exceptions import DuplicateProcessorError, ProcessorNotFoundError, InvalidPipelineError
from app.pipeline.processors import ProcessorNode, ProcessorRole


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def builder(bus: EventBus) -> PipelineBuilder:
    return PipelineBuilder(bus, "test-session")


def test_builder_add_processor(builder: PipelineBuilder) -> None:
    builder.add_processor(ProcessorNode("A", ProcessorRole.LLM))
    assert "A" in builder._processors
    
    with pytest.raises(DuplicateProcessorError):
        builder.add_processor(ProcessorNode("A", ProcessorRole.TTS))


def test_builder_add_transport(builder: PipelineBuilder) -> None:
    builder.add_transport(ProcessorNode("In", ProcessorRole.TRANSPORT_INPUT))
    assert "In" in builder._processors


def test_builder_connect(builder: PipelineBuilder) -> None:
    builder.add_processor(ProcessorNode("A", ProcessorRole.TRANSPORT_INPUT))
    builder.add_processor(ProcessorNode("B", ProcessorRole.LLM))
    
    builder.connect("A", "B")
    assert "B" in builder._graph.get_adjacency_list()["A"]
    
    with pytest.raises(ProcessorNotFoundError):
        builder.connect("A", "C")


def test_builder_remove_processor(builder: PipelineBuilder) -> None:
    builder.add_processor(ProcessorNode("A", ProcessorRole.TRANSPORT_INPUT))
    builder.remove_processor("A")
    assert "A" not in builder._processors
    
    with pytest.raises(ProcessorNotFoundError):
        builder.remove_processor("A")


def test_builder_insert_before(builder: PipelineBuilder) -> None:
    builder.add_processor(ProcessorNode("A", ProcessorRole.TRANSPORT_INPUT))
    builder.add_processor(ProcessorNode("B", ProcessorRole.TRANSPORT_OUTPUT))
    builder.connect("A", "B")
    
    builder.insert_before("B", ProcessorNode("C", ProcessorRole.LLM))
    
    adj = builder._graph.get_adjacency_list()
    assert "B" not in adj["A"]
    assert "C" in adj["A"]
    assert "B" in adj["C"]


def test_builder_insert_after(builder: PipelineBuilder) -> None:
    builder.add_processor(ProcessorNode("A", ProcessorRole.TRANSPORT_INPUT))
    builder.add_processor(ProcessorNode("B", ProcessorRole.TRANSPORT_OUTPUT))
    builder.connect("A", "B")
    
    builder.insert_after("A", ProcessorNode("C", ProcessorRole.LLM))
    
    adj = builder._graph.get_adjacency_list()
    assert "B" not in adj["A"]
    assert "C" in adj["A"]
    assert "B" in adj["C"]


def test_builder_replace_processor(builder: PipelineBuilder) -> None:
    builder.add_processor(ProcessorNode("A", ProcessorRole.TRANSPORT_INPUT))
    builder.add_processor(ProcessorNode("B", ProcessorRole.LLM))
    builder.add_processor(ProcessorNode("C", ProcessorRole.TRANSPORT_OUTPUT))
    builder.connect("A", "B").connect("B", "C")
    
    builder.replace_processor("B", ProcessorNode("NewB", ProcessorRole.LLM))
    
    assert "B" not in builder._processors
    assert "NewB" in builder._processors
    
    adj = builder._graph.get_adjacency_list()
    assert "NewB" in adj["A"]
    assert "C" in adj["NewB"]


def test_builder_reset(builder: PipelineBuilder) -> None:
    builder.add_processor(ProcessorNode("A", ProcessorRole.TRANSPORT_INPUT))
    builder.reset()
    assert not builder._processors


def test_build_success(builder: PipelineBuilder) -> None:
    builder.add_processor(ProcessorNode("A", ProcessorRole.TRANSPORT_INPUT))
    builder.add_processor(ProcessorNode("B", ProcessorRole.TRANSPORT_OUTPUT))
    builder.connect("A", "B")
    
    pipeline = builder.build(metadata={"foo": "bar"})
    assert pipeline.metadata == {"foo": "bar"}
    assert len(pipeline.processors) == 2


def test_build_failure(builder: PipelineBuilder) -> None:
    builder.add_processor(ProcessorNode("A", ProcessorRole.TRANSPORT_INPUT))
    builder.add_processor(ProcessorNode("B", ProcessorRole.LLM))
    # Two disconnected roots: A and B
    with pytest.raises(InvalidPipelineError):
        builder.build()
