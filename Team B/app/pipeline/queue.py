"""
Execution Queue for passing control/data between processors.
"""

import asyncio
from typing import Any


class ExecutionQueue:
    """Async queue for inter-processor communication or task scheduling."""
    
    def __init__(self, maxsize: int = 0) -> None:
        self._queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=maxsize)
        
    async def put(self, item: Any) -> None:
        """Put an item into the queue."""
        await self._queue.put(item)
        
    async def get(self) -> Any:
        """Get an item from the queue."""
        return await self._queue.get()
        
    def task_done(self) -> None:
        """Mark a task as done."""
        self._queue.task_done()
        
    async def join(self) -> None:
        """Wait until all tasks in the queue are done."""
        await self._queue.join()
        
    def empty(self) -> bool:
        """Check if queue is empty."""
        return self._queue.empty()
        
    def qsize(self) -> int:
        """Get the queue size."""
        return self._queue.qsize()
