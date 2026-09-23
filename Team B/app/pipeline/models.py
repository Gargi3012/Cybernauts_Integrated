"""
Immutable Pipeline Model.

This represents a successfully built, validated, ready-to-run pipeline.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Any

from .processors import ProcessorNode


@dataclass(frozen=True, slots=True)
class Pipeline:
    """Immutable representation of a complete processing pipeline.
    
    Attributes:
        pipeline_id: Unique identifier for this pipeline definition.
        processors: Dictionary of processor nodes keyed by their ID.
        graph: DAG structure represented as an adjacency list { node_id: [child_ids] }.
        created_at: UTC timestamp of creation.
        metadata: Arbitrary metadata for the pipeline.
    """
    processors: Dict[str, ProcessorNode]
    graph: Dict[str, List[str]]
    pipeline_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize pipeline to a dictionary."""
        return {
            "pipeline_id": self.pipeline_id,
            "created_at": self.created_at.isoformat(),
            "processors": {
                k: v.to_dict() for k, v in self.processors.items()
            },
            "graph": self.graph,
            "metadata": self.metadata,
        }
        
    def clone(self) -> Pipeline:
        """Create a deep copy of the pipeline with a new ID."""
        import copy
        return Pipeline(
            pipeline_id=str(uuid.uuid4()),
            processors=copy.deepcopy(self.processors),
            graph=copy.deepcopy(self.graph),
            metadata=copy.deepcopy(self.metadata),
            created_at=datetime.now(timezone.utc)
        )
