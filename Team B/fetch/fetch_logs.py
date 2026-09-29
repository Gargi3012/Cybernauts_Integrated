import os
import sys
from dotenv import load_dotenv
import plivo

load_dotenv()

auth_id = os.getenv("PLIVO_AUTH_ID", "")
auth_token = os.getenv("PLIVO_AUTH_TOKEN", "")

if auth_id and auth_token and not auth_id.startswith("dummy_"):
    client = plivo.RestClient(auth_id, auth_token)
    try:
        response = client.calls.list(limit=5)
        print(f"Plivo calls: {response}")
    except Exception as e:
        print(f"Failed to fetch Plivo calls: {e}")
else:
    print("Set PLIVO_AUTH_ID and PLIVO_AUTH_TOKEN in .env.")
