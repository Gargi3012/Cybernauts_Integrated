"""
Fluent Pipeline Builder.

Constructs an immutable Pipeline definition without executing it.
Integrates with EventBus to emit lifecycle events.
"""

from __future__ import annotations

import threading
from typing import Dict, Optional, Any

from loguru import logger

from app.events import EventBus
from app.events.event_types import (
    PipelineBuildFailed,
    PipelineBuildSucceeded,
    PipelineCreated,
    PipelineValidated,
    ProcessorAdded,
    ProcessorRemoved,
)

from .exceptions import DuplicateProcessorError, ProcessorNotFoundError
from .graph import PipelineGraph
from .models import Pipeline
from .processors import ProcessorNode, ProcessorRole
from .validators import validate_pipeline


class PipelineBuilder:
    """Fluent builder for constructing a Pipeline DAG.
    
    Safe to use across multiple threads. Returns an immutable Pipeline.
    """
    
    def __init__(self, event_bus: EventBus, session_id: str) -> None:
        self._bus = event_bus
        self._session_id = session_id
        
        self._lock = threading.Lock()
        self._processors: Dict[str, ProcessorNode] = {}
        self._graph = PipelineGraph()
        
        # Fire-and-forget init event
        self._bus.publish_sync(PipelineCreated(session_id=self._session_id))
        logger.bind(session_id=self._session_id).debug("PipelineBuilder initialized")

    def add_processor(self, processor: ProcessorNode) -> PipelineBuilder:
        """Add a processor to the pipeline as a disconnected node."""
        with self._lock:
            if processor.processor_id in self._processors:
                raise DuplicateProcessorError(f"Processor ID '{processor.processor_id}' already exists.")
                
            self._processors[processor.processor_id] = processor
            self._graph.add_node(processor.processor_id)
            
        self._bus.publish_sync(
            ProcessorAdded(
                session_id=self._session_id,
                payload={"processor_id": processor.processor_id, "role": processor.role.value}
            )
        )
        logger.debug(f"Added processor: {processor.processor_id}")
        return self

    def add_transport(self, processor: ProcessorNode) -> PipelineBuilder:
        """Convenience method for adding a transport node.
        
        Usually just delegates to add_processor, but can apply specific logic.
        """
        if processor.role not in (ProcessorRole.TRANSPORT_INPUT, ProcessorRole.TRANSPORT_OUTPUT):
            logger.warning("add_transport called with non-transport role")
        return self.add_processor(processor)

    def connect(self, from_id: str, to_id: str) -> PipelineBuilder:
        """Connect two processors in the DAG."""
        with self._lock:
            if from_id not in self._processors:
                raise ProcessorNotFoundError(from_id)
            if to_id not in self._processors:
                raise ProcessorNotFoundError(to_id)
                
            self._graph.add_edge(from_id, to_id)
        logger.debug(f"Connected {from_id} -> {to_id}")
        return self

    def insert_before(self, target_id: str, processor: ProcessorNode) -> PipelineBuilder:
        """Insert a new processor immediately before a target processor.
        
        All edges pointing TO target_id will instead point to the new processor,
        and the new processor will point to target_id.
        """
        with self._lock:
            if target_id not in self._processors:
                raise ProcessorNotFoundError(target_id)
            if processor.processor_id in self._processors:
                raise DuplicateProcessorError(processor.processor_id)

            self._processors[processor.processor_id] = processor
            self._graph.add_node(processor.processor_id)
            
            adj = self._graph.get_adjacency_list()
            # Redirect parents
            for parent_id, children in adj.items():
                if target_id in children:
                    self._graph.remove_edge(parent_id, target_id)
                    self._graph.add_edge(parent_id, processor.processor_id)
            
            # Connect to target
            self._graph.add_edge(processor.processor_id, target_id)

        self._bus.publish_sync(
            ProcessorAdded(
                session_id=self._session_id,
                payload={"processor_id": processor.processor_id, "role": processor.role.value, "inserted_before": target_id}
            )
        )
        return self

    def insert_after(self, target_id: str, processor: ProcessorNode) -> PipelineBuilder:
        """Insert a new processor immediately after a target processor."""
        with self._lock:
            if target_id not in self._processors:
                raise ProcessorNotFoundError(target_id)
            if processor.processor_id in self._processors:
                raise DuplicateProcessorError(processor.processor_id)

            self._processors[processor.processor_id] = processor
            self._graph.add_node(processor.processor_id)
            
            adj = self._graph.get_adjacency_list()
            # Redirect children
            for child_id in adj.get(target_id, []).copy():
                self._graph.remove_edge(target_id, child_id)
                self._graph.add_edge(processor.processor_id, child_id)
                
            # Connect from target
            self._graph.add_edge(target_id, processor.processor_id)

        self._bus.publish_sync(
            ProcessorAdded(
                session_id=self._session_id,
                payload={"processor_id": processor.processor_id, "role": processor.role.value, "inserted_after": target_id}
            )
        )
        return self

    def remove_processor(self, processor_id: str) -> PipelineBuilder:
        """Remove a processor and its associated edges."""
        with self._lock:
            if processor_id not in self._processors:
                raise ProcessorNotFoundError(processor_id)
            
            del self._processors[processor_id]
            self._graph.remove_node(processor_id)
            
        self._bus.publish_sync(
            ProcessorRemoved(
                session_id=self._session_id,
                payload={"processor_id": processor_id}
            )
        )
        logger.debug(f"Removed processor: {processor_id}")
        return self

    def replace_processor(self, old_id: str, new_processor: ProcessorNode) -> PipelineBuilder:
        """Replace a processor while preserving its connections."""
        with self._lock:
            if old_id not in self._processors:
                raise ProcessorNotFoundError(old_id)
            if new_processor.processor_id in self._processors and new_processor.processor_id != old_id:
                raise DuplicateProcessorError(new_processor.processor_id)

            # Gather edges
            adj = self._graph.get_adjacency_list()
            parents = [p for p, c in adj.items() if old_id in c]
            children = adj.get(old_id, []).copy()

            # Swap
            del self._processors[old_id]
            self._graph.remove_node(old_id)

            self._processors[new_processor.processor_id] = new_processor
            self._graph.add_node(new_processor.processor_id)

            for p in parents:
                self._graph.add_edge(p, new_processor.processor_id)
            for c in children:
                self._graph.add_edge(new_processor.processor_id, c)

        self._bus.publish_sync(ProcessorRemoved(session_id=self._session_id, payload={"processor_id": old_id}))
        self._bus.publish_sync(ProcessorAdded(session_id=self._session_id, payload={"processor_id": new_processor.processor_id}))
        return self

    def validate(self) -> PipelineBuilder:
        """Run validation rules against the current graph."""
        with self._lock:
            try:
                validate_pipeline(self._processors, self._graph.get_adjacency_list())
            except Exception as e:
                logger.error(f"Pipeline validation failed: {e}")
                self._bus.publish_sync(PipelineBuildFailed(session_id=self._session_id, payload={"error": str(e)}))
                raise
                
        self._bus.publish_sync(PipelineValidated(session_id=self._session_id))
        logger.debug("Pipeline validation passed")
        return self
        
    def reset(self) -> PipelineBuilder:
        """Clear all processors and edges."""
        with self._lock:
            self._processors.clear()
            self._graph = PipelineGraph()
        return self

    def build(self, metadata: Optional[Dict[str, Any]] = None) -> Pipeline:
        """Validate and construct the final immutable Pipeline."""
        logger.bind(session_id=self._session_id).debug("Pipeline build started")
        self.validate()
        
        with self._lock:
            pipeline = Pipeline(
                processors=self._processors.copy(),
                graph=self._graph.get_adjacency_list(),
                metadata=metadata or {}
            )
            
        self._bus.publish_sync(PipelineBuildSucceeded(session_id=self._session_id, payload={"pipeline_id": pipeline.pipeline_id}))
        logger.bind(session_id=self._session_id).info("Pipeline successfully built", pipeline_id=pipeline.pipeline_id)
        
        return pipeline
