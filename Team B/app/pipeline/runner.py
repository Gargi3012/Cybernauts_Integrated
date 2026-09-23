"""
Pipeline Runner.
Executes an immutable Pipeline definition.
"""

import asyncio
from typing import Dict, Any

from loguru import logger

from app.events import EventBus
from app.pipeline.context import ExecutionContext
from app.pipeline.exceptions import PipelineCancelledError, PipelineExecutionError
from app.pipeline.executor import AbstractProcessor, DefaultProcessorExecutor
from app.pipeline.lifecycle import PipelineLifecycleManager
from app.pipeline.models import Pipeline
from app.pipeline.scheduler import PipelineScheduler
from app.pipeline.execution_state import ExecutionState


class PipelineRunner:
    """Production-grade asynchronous Pipeline Runner."""
    
    def __init__(self, pipeline: Pipeline, processors: Dict[str, AbstractProcessor], event_bus: EventBus, session_id: str):
        self.pipeline = pipeline
        self.processors = processors
        self.event_bus = event_bus
        self.session_id = session_id
        
        # Core components
        self.context = ExecutionContext(pipeline_id=pipeline.pipeline_id, session_id=session_id)
        self.lifecycle = PipelineLifecycleManager(event_bus, session_id, self.context.execution_id)
        self.scheduler = PipelineScheduler(pipeline)
        self.executor = DefaultProcessorExecutor(event_bus)
        
        self.lifecycle.initialize()

    async def run(self) -> None:
        """Execute the pipeline graph sequentially according to topological order."""
        try:
            self.lifecycle.start()
            
            execution_order = self.scheduler.get_execution_order()
            
            for processor_id in execution_order:
                # Cooperative cancellation check
                if self.context.cancellation_token.is_cancelled:
                    self.lifecycle.mark_cancelled()
                    raise PipelineCancelledError("Pipeline execution cancelled.")
                
                # Check for pause
                while self.lifecycle.state == ExecutionState.PAUSED:
                    if self.context.cancellation_token.is_cancelled:
                        self.lifecycle.mark_cancelled()
                        raise PipelineCancelledError("Pipeline execution cancelled during pause.")
                    await asyncio.sleep(0.1)

                node = self.pipeline.processors[processor_id]
                processor = self.processors.get(processor_id)
                
                if not processor:
                    raise PipelineExecutionError(f"No processor implementation provided for ID: {processor_id}")
                
                # Setup scoped context
                scoped_context = self.context.with_processor(processor_id)
                
                # Execute node
                await self.executor.run(processor, node, scoped_context)

            if not self.context.cancellation_token.is_cancelled:
                self.lifecycle.complete()

        except PipelineCancelledError as e:
            logger.warning(f"Pipeline cancelled: {e}")
            self.lifecycle.mark_cancelled()
            raise
        except Exception as e:
            self.lifecycle.fail(e)
            raise
        finally:
            self.cleanup()

    def cancel(self) -> None:
        """Request pipeline cancellation."""
        self.lifecycle.cancel()
        self.context.cancellation_token.cancel()

    def pause(self) -> None:
        """Pause pipeline execution (at processor boundaries)."""
        self.lifecycle.pause()

    def resume(self) -> None:
        """Resume pipeline execution."""
        self.lifecycle.resume()

    def cleanup(self) -> None:
        """Perform graceful shutdown and cleanup."""
        self.lifecycle.shutdown()
        
    def get_metrics(self) -> Dict[str, Any]:
        """Expose current execution metrics."""
        return self.context.metrics_collector.get_metrics()
