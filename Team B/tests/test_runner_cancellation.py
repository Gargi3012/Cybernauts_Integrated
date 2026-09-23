"""
Tests for cooperative cancellation token.
"""

import pytest

from app.pipeline.cancellation import CancellationToken
from app.pipeline.exceptions import PipelineCancelledError


def test_cancellation_token() -> None:
    token = CancellationToken()
    assert not token.is_cancelled
    
    # Should not raise
    token.throw_if_cancelled()
    
    token.cancel()
    assert token.is_cancelled
    
    with pytest.raises(PipelineCancelledError, match="Execution was cancelled."):
        token.throw_if_cancelled()
