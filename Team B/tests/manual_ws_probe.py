import asyncio
import websockets
import json

async def test_websocket():
    uri = "ws://localhost:8000/ws"
    try:
        async with websockets.connect(uri) as websocket:
            print("Connected to WebSocket")
            
            # Send the start event exactly like Plivo does
            start_event = {
                "event": "start",
                "start": {
                    "streamId": "plivo-stream-12345",
                    "callId": "plivo-call-12345",
                    "customParameters": {
                        "phone": "+1234567890",
                        "lead_id": "test.com",
                        "session_id": "sess-test-123"
                    }
                }
            }
            await websocket.send(json.dumps(start_event))
            print("Sent start event")
            
            # Wait for any response or close
            while True:
                msg = await websocket.recv()
                print(f"Received: {msg}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_websocket())
