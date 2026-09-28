import os
import plivo
from dotenv import load_dotenv

load_dotenv()
auth_id = os.environ.get('PLIVO_AUTH_ID', '')
auth_token = os.environ.get('PLIVO_AUTH_TOKEN', '')

if auth_id and auth_token and not auth_id.startswith('dummy_'):
    client = plivo.RestClient(auth_id, auth_token)
    try:
        calls = client.calls.list(limit=5)
        print("RECENT PLIVO CALLS:", calls)
    except Exception as e:
        print(f"Failed to fetch calls: {e}")
else:
    print("Set PLIVO_AUTH_ID and PLIVO_AUTH_TOKEN in .env.")
