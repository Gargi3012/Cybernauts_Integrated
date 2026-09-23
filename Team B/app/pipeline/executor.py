"""
Processor execution abstractions and the Executor itself.
"""

from __future__ import annotations

import abc
from typing import Any

from loguru import logger

from app.events import EventBus
from app.events.event_types import (
    ProcessorExecutionCompleted,
    ProcessorExecutionFailed,
    ProcessorExecutionStarted,
)
from app.pipeline.context import ExecutionContext
from app.pipeline.exceptions import ProcessorExecutionError, PipelineCancelledError
from app.pipeline.processors import ProcessorNode


class AbstractProcessor(abc.ABC):
    """Abstract interface for all executable processors."""
    
    @abc.abstractmethod
    async def before_execute(self, context: ExecutionContext, node: ProcessorNode) -> None:
        """Called before main execution."""
        pass
        
    @abc.abstractmethod
    async def execute(self, context: ExecutionContext, node: ProcessorNode) -> Any:
        """Main execution logic."""
        pass
        
    @abc.abstractmethod
    async def after_execute(self, context: ExecutionContext, node: ProcessorNode) -> None:
        """Called after main execution."""
        pass


class DefaultProcessorExecutor:
    """Handles the execution lifecycle of a single processor."""
    
    def __init__(self, event_bus: EventBus) -> None:
        self._bus = event_bus

    async def run(self, processor: AbstractProcessor, node: ProcessorNode, context: ExecutionContext) -> Any:
        """Execute a processor with full lifecycle and event emission."""
        processor_id = node.processor_id
        session_id = context.session_id
        
        logger.bind(session_id=session_id, processor_id=processor_id).debug("Starting processor execution")
        self._bus.publish_sync(
            ProcessorExecutionStarted(
                session_id=session_id,
                payload={"processor_id": processor_id}
            )
        )
        
        context.metrics_collector.start_processor(processor_id)
        
        try:
            # Check cancellation before starting
            context.cancellation_token.throw_if_cancelled()
            
            await processor.before_execute(context, node)
            
            # Check cancellation before execute
            context.cancellation_token.throw_if_cancelled()
            
            result = await processor.execute(context, node)
            
            # Check cancellation before after_execute
            context.cancellation_token.throw_if_cancelled()
            
            await processor.after_execute(context, node)
            
        except PipelineCancelledError:
            # Propagate cancellation without recording it as a processor failure
            context.metrics_collector.end_processor(processor_id, success=False)
            raise
        except Exception as e:
            context.metrics_collector.end_processor(processor_id, success=False)
            logger.bind(session_id=session_id, processor_id=processor_id).error(f"Processor execution failed: {e}")
            self._bus.publish_sync(
                ProcessorExecutionFailed(
                    session_id=session_id,
                    payload={"processor_id": processor_id, "error": str(e)}
                )
            )
            raise ProcessorExecutionError(f"Processor {processor_id} failed: {e}") from e
            
        context.metrics_collector.end_processor(processor_id, success=True)
        self._bus.publish_sync(
            ProcessorExecutionCompleted(
                session_id=session_id,
                payload={"processor_id": processor_id}
            )
        )
        logger.bind(session_id=session_id, processor_id=processor_id).debug("Completed processor execution")
        return result
