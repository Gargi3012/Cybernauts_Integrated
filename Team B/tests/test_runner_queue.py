"""
Tests for ExecutionQueue.
"""


import pytest

from app.pipeline.queue import ExecutionQueue


@pytest.mark.asyncio
async def test_execution_queue() -> None:
    queue = ExecutionQueue()
    assert queue.empty()
    assert queue.qsize() == 0
    
    await queue.put("item1")
    assert not queue.empty()
    assert queue.qsize() == 1
    
    item = await queue.get()
    assert item == "item1"
    
    queue.task_done()
    await queue.join()
