"""
Lifecycle synchronization for Pipecat adapter.
"""

from typing import Any

from loguru import logger

from .exceptions import RuntimeSynchronizationError


class PipecatLifecycleManager:
    """Manages synchronization between our lifecycle and Pipecat's lifecycle."""
    
    def __init__(self, pipecat_task: Any, session_id: str):
        self._task = pipecat_task
        self._session_id = session_id
        
    async def start(self) -> None:
        logger.bind(session_id=self._session_id).info("Starting Pipecat task")
        try:
            if hasattr(self._task, "start"):
                await self._task.start()
        except Exception as e:
            raise RuntimeSynchronizationError(f"Failed to start Pipecat task: {e}") from e
            
    async def stop(self) -> None:
        logger.bind(session_id=self._session_id).info("Stopping Pipecat task")
        try:
            if hasattr(self._task, "stop"):
                await self._task.stop()
        except Exception as e:
            raise RuntimeSynchronizationError(f"Failed to stop Pipecat task: {e}") from e

    async def wait_until_done(self) -> None:
        logger.bind(session_id=self._session_id).debug("Waiting for Pipecat task to finish")
        try:
            if hasattr(self._task, "wait"):
                await self._task.wait()
        except Exception as e:
            raise RuntimeSynchronizationError(f"Error while waiting for Pipecat task: {e}") from e
