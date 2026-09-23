"""
Tests for pipeline validation logic.
"""

import pytest

from app.pipeline.exceptions import EmptyPipelineError, InvalidPipelineError
from app.pipeline.processors import ProcessorNode, ProcessorRole
from app.pipeline.validators import validate_pipeline


def test_empty_pipeline() -> None:
    with pytest.raises(EmptyPipelineError):
        validate_pipeline({}, {})


def test_no_edges() -> None:
    processors = {"A": ProcessorNode("A", ProcessorRole.TRANSPORT_INPUT)}
    with pytest.raises(InvalidPipelineError, match="Pipeline graph is empty"):
        validate_pipeline(processors, {})


def test_multiple_transport_inputs() -> None:
    processors = {
        "A": ProcessorNode("A", ProcessorRole.TRANSPORT_INPUT),
        "B": ProcessorNode("B", ProcessorRole.TRANSPORT_INPUT),
    }
    graph = {"A": ["B"], "B": []}
    with pytest.raises(InvalidPipelineError, match="Multiple transport inputs"):
        validate_pipeline(processors, graph)





def test_multiple_roots_with_transport() -> None:
    processors = {
        "A": ProcessorNode("A", ProcessorRole.TRANSPORT_INPUT),
        "B": ProcessorNode("B", ProcessorRole.LLM),
        "C": ProcessorNode("C", ProcessorRole.STT),
    }
    graph = {"A": ["B"], "B": [], "C": ["B"]}
    
    with pytest.raises(InvalidPipelineError, match="multiple disconnected root nodes"):
        validate_pipeline(processors, graph)


def test_valid_pipeline() -> None:
    processors = {
        "A": ProcessorNode("A", ProcessorRole.TRANSPORT_INPUT),
        "B": ProcessorNode("B", ProcessorRole.LLM),
        "C": ProcessorNode("C", ProcessorRole.TRANSPORT_OUTPUT),
    }
    graph = {"A": ["B"], "B": ["C"], "C": []}
    
    # Should not raise
    validate_pipeline(processors, graph)
