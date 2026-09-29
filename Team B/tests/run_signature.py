import os
from dotenv import load_dotenv
import plivo.utils

load_dotenv()

auth_token = os.environ.get("PLIVO_AUTH_TOKEN", "mock_plivo_auth_token")

url = "https://catalectic-ezra-pisciculturally.ngrok-free.dev/inbound-call"
post_vars = {"To": "+917082968702", "From": "+18303546921", "CallUUID": "plivo-call-123"}

# Plivo signature validation
# Signature format: validate_signature(uri, nonce, signature, auth_token)
print(f"Plivo validate_signature available: {callable(plivo.utils.validate_signature)}")
