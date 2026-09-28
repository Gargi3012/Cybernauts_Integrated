import os
from fastapi.testclient import TestClient
from app.main import app
import plivo.utils
from dotenv import load_dotenv

load_dotenv()
auth_token = os.environ.get("PLIVO_AUTH_TOKEN", "mock_plivo_auth_token")

url = "http://testserver/inbound-call"
post_vars = {"To": "+917082968702", "From": "+18303546921", "CallUUID": "plivo-call-123"}

client = TestClient(app)
try:
    response = client.post(
        "/inbound-call", 
        data=post_vars
    )
    print("Status:", response.status_code)
    print("Response XML:\n", response.text)
except Exception as e:
    import traceback
    traceback.print_exc()
