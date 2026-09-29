import os
import json
import plivo
from dotenv import load_dotenv

load_dotenv()
auth_id = os.environ.get('PLIVO_AUTH_ID')
auth_token = os.environ.get('PLIVO_AUTH_TOKEN')
call_uuid = os.environ.get('PLIVO_CALL_UUID', 'test_uuid')

if auth_id and auth_token and not auth_id.startswith('dummy_'):
    client = plivo.RestClient(auth_id, auth_token)
    try:
        call = client.calls.get(call_uuid)
        print(call)
    except Exception as e:
        print(f"Plivo call status: {e}")
else:
    print("Set PLIVO_AUTH_ID and PLIVO_AUTH_TOKEN in .env to query Plivo call status.")
