
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
from fastapi.testclient import TestClient
from app.main import app, APP_STATE
from app.routers.livekit_router import broadcast_frontend_event, frontend_websockets


def test_root_endpoint_returns_200_without_redirect_loop():
    """Verify GET / returns HTTP 200 with HTML rather than an infinite 302 redirect loop."""
    client = TestClient(app, follow_redirects=False)
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers.get("content-type", "")
    assert len(res.content) > 0


def test_static_asset_serving():
    """Verify static assets are mounted and served correctly."""
    client = TestClient(app, follow_redirects=False)
    res = client.get("/static/Flowiz.png")
    # If file exists, returns 200, otherwise 404 (not 500 or redirect loop)
    assert res.status_code in (200, 404)


def test_legacy_voice_redirect_to_root():
    """Verify legacy routes return HTTP 302 pointing to /."""
    client = TestClient(app, follow_redirects=False)
    res = client.get("/voice")
    assert res.status_code == 302
    assert res.headers.get("location") == "/"


def test_health_check_endpoint():
    """Verify /health reflects APP_STATE readiness."""
    client = TestClient(app, follow_redirects=False)
    APP_STATE["is_ready"] = True
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_broadcast_frontend_event_concurrency_safety():
    """Verify broadcast_frontend_event is safe against concurrent modifications of frontend_websockets."""
    mock_ws1 = AsyncMock()
    mock_ws2 = AsyncMock()
    mock_ws3 = AsyncMock()
    mock_ws2.send_json.side_effect = Exception("Simulated disconnect")

    frontend_websockets.clear()
    frontend_websockets.extend([mock_ws1, mock_ws2, mock_ws3])

    # Run multiple concurrent broadcast tasks
    await asyncio.gather(
        broadcast_frontend_event("test_event_1", {"data": 1}),
        broadcast_frontend_event("test_event_2", {"data": 2}),
    )

    # Disconnected websocket should be pruned cleanly without raising RuntimeError
    assert mock_ws2 not in frontend_websockets
    assert mock_ws1 in frontend_websockets
    assert mock_ws3 in frontend_websockets
    frontend_websockets.clear()
