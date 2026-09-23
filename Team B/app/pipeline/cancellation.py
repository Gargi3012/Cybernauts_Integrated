"""
Cancellation Token for cooperative cancellation.
"""

import threading


class CancellationToken:
    """Thread-safe cooperative cancellation token."""
    
    def __init__(self) -> None:
        self._is_cancelled = False
        self._lock = threading.Lock()
        
    def cancel(self) -> None:
        """Request cancellation."""
        with self._lock:
            self._is_cancelled = True
            
    @property
    def is_cancelled(self) -> bool:
        """Check if cancellation was requested."""
        with self._lock:
            return self._is_cancelled

    def throw_if_cancelled(self) -> None:
        """Raise PipelineCancelledError if cancelled."""
        from .exceptions import PipelineCancelledError
        if self.is_cancelled:
            raise PipelineCancelledError("Execution was cancelled.")
