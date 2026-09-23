"""
Locust Load Testing Suite for Real-Time Voice Pipeline
Simulates concurrent voice call joins, WebSocket control connections, and health checks.
"""

import json
import time
from locust import HttpUser, task, between, events
import websocket


class VoicePipelineUser(HttpUser):
    wait_time = between(1, 3)  # Wait 1-3 seconds between tasks

    def on_start(self):
        """Executed when a simulated user starts."""
        self.client_id = f"locust_user_{self.environment.runner.user_count}"
        self.headers = {"Content-Type": "application/json"}

    @task(3)
    def test_health_check(self):
        """Test server health endpoint under concurrent load."""
        with self.client.get("/health", catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Health check failed with status {response.status_code}")

    @task(5)
    def test_join_call(self):
        """Simulate concurrent call join requests (Token Generation)."""
        payload = {
            "client_id": self.client_id,
            "transport": "livekit"
        }
        t0 = time.time()
        with self.client.post("/api/livekit/join", json=payload, headers=self.headers, catch_response=True) as response:
            latency_ms = (time.time() - t0) * 1000
            if response.status_code == 200:
                data = response.json()
                if "token" in data and "roomUrl" in data:
                    response.success()
                    events.request.fire(
                        request_type="Join_Call_Token",
                        name="LiveKit_Join",
                        response_time=latency_ms,
                        response_length=len(response.content),
                        exception=None,
                    )
                else:
                    response.failure("Missing token or roomUrl in response")
            else:
                response.failure(f"Join failed: {response.status_code}")

    @task(2)
    def test_websocket_connection(self):
        """Simulate WebSocket control channel connection & messaging under load."""
        host = self.host.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{host}/ws/frontend"
        
        t0 = time.time()
        try:
            ws = websocket.create_connection(ws_url, timeout=5)
            connection_time = (time.time() - t0) * 1000
            
            events.request.fire(
                request_type="WebSocket",
                name="WS_Connect",
                response_time=connection_time,
                response_length=0,
                exception=None,
            )
            
            # Receive greeting / transport_mode frame
            ws.settimeout(2.0)
            try:
                result = ws.recv()
                data = json.loads(result)
                if "event" in data:
                    events.request.fire(
                        request_type="WebSocket",
                        name="WS_Event_Receive",
                        response_time=50,
                        response_length=len(result),
                        exception=None,
                    )
            except Exception:
                pass
                
            ws.close()
        except Exception as e:
            events.request.fire(
                request_type="WebSocket",
                name="WS_Connect_Failed",
                response_time=(time.time() - t0) * 1000,
                response_length=0,
                exception=e,
            )
