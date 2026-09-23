"""
Serializer for Pipeline instances.
"""

from __future__ import annotations

import json
from .models import Pipeline
from .processors import ProcessorNode, ProcessorRole


class PipelineSerializer:
    """Handles JSON serialization and deserialization of pipelines."""
    
    @staticmethod
    def to_json(pipeline: Pipeline, pretty: bool = False) -> str:
        """Serialize a Pipeline object to a JSON string."""
        indent = 4 if pretty else None
        return json.dumps(pipeline.to_dict(), indent=indent)

    @staticmethod
    def from_json(json_str: str) -> Pipeline:
        """Deserialize a JSON string into a Pipeline object."""
        data = json.loads(json_str)
        
        raw_processors = data.get("processors", {})
        processors = {}
        for pid, p_data in raw_processors.items():
            processors[pid] = ProcessorNode(
                processor_id=p_data["processor_id"],
                role=ProcessorRole(p_data["role"]),
                name=p_data.get("name", "UnknownProcessor"),
                metadata=p_data.get("metadata", {})
            )
            
        from dateutil.parser import isoparse
        return Pipeline(
            pipeline_id=data["pipeline_id"],
            processors=processors,
            graph=data.get("graph", {}),
            metadata=data.get("metadata", {}),
            created_at=isoparse(data["created_at"])
        )
