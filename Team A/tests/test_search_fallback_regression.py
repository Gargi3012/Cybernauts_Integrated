"""
Team A Regression Test: Search Provider Fallback & Discovery Pipeline State
Validates:
1. config.activate_fallback_mode exists and activates fallback mode
2. SearchManager handles SerpApi rate limit / quota exhaustion without raising AttributeError
3. API pipeline state accurately tracks elapsed time and reports real errors
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

import config
from search.manager import SearchManager
from search.exceptions import ProviderUnavailable


class TestSearchFallbackRegression(unittest.TestCase):
    def test_config_has_fallback_mode_and_activator(self):
        """Verify config defines FALLBACK_MODE and activate_fallback_mode."""
        self.assertTrue(hasattr(config, "FALLBACK_MODE"))
        self.assertTrue(hasattr(config, "activate_fallback_mode"))
        self.assertTrue(callable(config.activate_fallback_mode))

        # Test activating fallback mode
        config.activate_fallback_mode("Test fallback activation")
        self.assertTrue(config.FALLBACK_MODE)
        self.assertEqual(config.FALLBACK_REASON, "Test fallback activation")

    def test_search_manager_handles_serpapi_quota_exhaustion_without_crashing(self):
        """Verify SearchManager does not crash with AttributeError when SerpApi fails."""
        sm = SearchManager()
        sm.serpapi_available = True

        # Mock SerpApi provider to raise quota exceeded (HTTP 429)
        mock_serpapi = MagicMock()
        mock_serpapi.name = "serpapi"
        mock_serpapi.search.side_effect = ProviderUnavailable("serpapi", "quota exceeded (HTTP 429)")

        with patch.object(sm, "_get_instance", return_value=mock_serpapi):
            # Run _run_serpapi_primary
            provider_report = []
            success = sm._run_serpapi_primary(
                query="AI Software Development",
                max_results=5,
                page=0,
                deadline=None,
                all_results=[],
                seen_canonical=set(),
                providers_used=[],
                provider_report=provider_report,
            )
            # Must return False and disable serpapi_available rather than raising AttributeError
            self.assertFalse(success)
            self.assertFalse(sm.serpapi_available)
            self.assertEqual(len(provider_report), 1)
            self.assertEqual(provider_report[0]["provider"], "serpapi")
            self.assertEqual(provider_report[0]["status"], "ERROR")

    def test_api_pipeline_state_updates_elapsed_sec(self):
        """Verify pipeline status includes elapsed_sec and valid stages."""
        from api import pipeline_state, update_stage, status_lock

        update_stage("TEST_STAGE", "Running test...", 50, elapsed_sec=12.5)
        with status_lock:
            self.assertEqual(pipeline_state["stage_code"], "TEST_STAGE")
            self.assertEqual(pipeline_state["elapsed_sec"], 12.5)
            self.assertEqual(pipeline_state["progress_pct"], 50)


if __name__ == "__main__":
    unittest.main()
