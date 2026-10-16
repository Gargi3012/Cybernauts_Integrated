"""
Tests for server lifecycle, database health checks, and graceful degradation policy.
Verifies that:
1. /health returns HTTP 503 before lifespan initialization.
2. /health returns HTTP 200 when core SQLite databases initialize (Team B PostgreSQL degrading gracefully by design).
3. /health returns HTTP 503 when REQUIRE_TEAM_B_DB=true is enforced and PostgreSQL is unavailable.
"""

import os
import pytest
from fastapi.testclient import TestClient


def test_health_pre_lifespan():
    """Verify /health returns 503 before server lifespan has run."""
    import server
    # Reset state to simulate cold boot before lifespan
    server.APP_STATE["is_ready"] = False
    client = TestClient(server.app)
    resp = client.get("/health")
    assert resp.status_code == 503
    data = resp.json()
    assert data["detail"]["status"] == "unhealthy"


def test_health_lifespan_graceful_degradation():
    """
    Verify /health returns 200 when SQLite databases initialize.
    Team B PostgreSQL is optional by design (graceful degradation) in standalone / lead discovery mode.
    """
    import server
    with TestClient(server.app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["ready"] is True
        assert data["team_a_db"] is True
        assert data["recordings_db"] is True
        # Proves that team_b_db=False is intentional and accepted when not required
        assert data["team_b_db_required"] is False


def test_health_when_team_b_db_strictly_required(monkeypatch):
    """
    Verify /health returns 503 if REQUIRE_TEAM_B_DB=true is enforced and PostgreSQL is unavailable.
    """
    monkeypatch.setenv("REQUIRE_TEAM_B_DB", "true")
    import server
    # Re-run lifespan with REQUIRE_TEAM_B_DB=true
    with TestClient(server.app) as client:
        # If postgres is not running locally, it must reject readiness
        if not server.APP_STATE.get("db_team_b"):
            resp = client.get("/health")
            assert resp.status_code == 503
            data = resp.json()
            assert data["detail"]["status"] == "unhealthy"
            assert data["detail"]["team_b_db_required"] is True
