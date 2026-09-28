import os
import plivo
from dotenv import load_dotenv

load_dotenv()
auth_id = os.environ.get('PLIVO_AUTH_ID', '')
auth_token = os.environ.get('PLIVO_AUTH_TOKEN', '')
uuid = os.environ.get('PLIVO_CALL_UUID', 'test_uuid')

if auth_id and auth_token and not auth_id.startswith('dummy_'):
    client = plivo.RestClient(auth_id, auth_token)
    try:
        call = client.calls.get(uuid)
        print(f"Call UUID: {call.call_uuid}")
        print(f"Call Status: {call.call_state}")
        print(f"Call Duration: {call.call_duration}")
    except Exception as e:
        print(f"Plivo fetch call error: {e}")
else:
    print("Set PLIVO_AUTH_ID and PLIVO_AUTH_TOKEN in .env.")
