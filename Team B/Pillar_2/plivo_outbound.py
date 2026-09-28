import os
import urllib.parse
from dotenv import load_dotenv
from loguru import logger
import plivo

load_dotenv(override=False)


def place_plivo_outbound_call(to_number: str, company_context: str | None = None) -> str:
    server_base_url = (os.getenv("SERVER_BASE_URL") or os.getenv("PUBLIC_BASE_URL", "")).rstrip("/")
    plivo_auth_id = os.getenv("PLIVO_AUTH_ID", "")
    plivo_auth_token = os.getenv("PLIVO_AUTH_TOKEN", "")
    plivo_phone_number = os.getenv("PLIVO_PHONE_NUMBER", "")

    if not server_base_url:
        raise ValueError(
            "SERVER_BASE_URL is empty in .env — set it to your current public URL first "
            "(e.g. https://xxxx.ngrok-free.app)."
        )
    if not plivo_auth_id or not plivo_auth_token:
        raise ValueError("PLIVO_AUTH_ID or PLIVO_AUTH_TOKEN is missing in environment.")
    if not plivo_phone_number:
        raise ValueError("PLIVO_PHONE_NUMBER is missing in environment.")

    client = plivo.RestClient(auth_id=plivo_auth_id, auth_token=plivo_auth_token)

    # Webhook URL pointing to our Plivo answer endpoint
    answer_url = f"{server_base_url}/plivo/inbound-call"
    if company_context:
        answer_url += f"?company_context={urllib.parse.quote(company_context)}"

    logger.info(f"Placing Plivo outbound call: to={to_number}, from={plivo_phone_number}, answer_url={answer_url}")

    response = client.calls.create(
        from_=plivo_phone_number,
        to_=to_number,
        answer_url=answer_url,
        answer_method="POST",
    )

    call_uuid = (
        getattr(response, "request_uuid", None)
        or getattr(response, "call_uuid", None)
        or (response.get("request_uuid") if isinstance(response, dict) else None)
        or str(response)
    )
    logger.info(f"Plivo outbound call dispatched. UUID: {call_uuid}")
    return str(call_uuid)
