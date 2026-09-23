"""
Utility functions for Pipecat adapter.
"""

from typing import Any, Dict


def extract_pipecat_metadata(processor: Any) -> Dict[str, Any]:
    """Extract metadata from a Pipecat processor for logging/metrics."""
    return {
        "name": getattr(processor, "name", type(processor).__name__),
    }
