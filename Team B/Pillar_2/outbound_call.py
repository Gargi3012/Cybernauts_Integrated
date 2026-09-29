"""
Pillar 2 — Plivo Outbound Call Dispatcher
Triggers automated outbound phone calls through Plivo REST API and wires
the active answer URL to our bidirectional Pipecat voice pipeline.
"""

import argparse
import os
import urllib.parse
from typing import Optional
from dotenv import load_dotenv
from loguru import logger
import plivo

load_dotenv(override=True)


def place_outbound_call(
    to_number: str,
    company_context: Optional[str] = None,
    lead_id: Optional[str] = None,
    session_id: Optional[str] = None,
    dispatch_id: Optional[str] = None,
) -> str:
    """
    Trigger an outbound call using Plivo's REST API.
    
    Args:
        to_number: Target phone number in E.164 format (e.g. +91XXXXXXXXXX).
        company_context: Optional serialized business intelligence from Team A.
        lead_id: Optional Team A lead record ID for post-call result correlation.
        session_id: Optional unique voice session ID.
        dispatch_id: Optional idempotency dispatch tracking ID.
        
    Returns:
        The Plivo request_uuid or call_uuid string.
    """
    public_base_url = os.getenv("PUBLIC_BASE_URL", "")
    plivo_auth_id = os.getenv("PLIVO_AUTH_ID", "")
    plivo_auth_token = os.getenv("PLIVO_AUTH_TOKEN", "")
    plivo_phone_number = os.getenv("PLIVO_PHONE_NUMBER", os.getenv("PLIVO_FROM_NUMBER", ""))

    if not public_base_url:
        raise ValueError(
            "PUBLIC_BASE_URL is empty in .env — set it to your current ngrok/public URL "
            "(e.g. https://xxxx.ngrok-free.app) so Plivo can reach your webhook."
        )

    if not plivo_auth_id or not plivo_auth_token:
        raise ValueError("PLIVO_AUTH_ID and PLIVO_AUTH_TOKEN must be configured in .env.")

    client = plivo.RestClient(plivo_auth_id, plivo_auth_token)

    webhook_url = f"{public_base_url.rstrip('/')}/inbound-call"
    query_params = {}
    if company_context:
        query_params["company_context"] = company_context
    if lead_id:
        query_params["lead_id"] = str(lead_id)
    if session_id:
        query_params["session_id"] = str(session_id)
    if dispatch_id:
        query_params["dispatch_id"] = str(dispatch_id)

    if query_params:
        webhook_url += f"?{urllib.parse.urlencode(query_params)}"

    hangup_url = f"{public_base_url.rstrip('/')}/plivo/hangup"
    if lead_id:
        hangup_url += f"?lead_id={urllib.parse.quote(str(lead_id))}"

    masked_to = f"{to_number[:3]}******{to_number[-4:]}" if len(to_number) > 7 else to_number
    logger.info(f"Placing Plivo outbound call: to={masked_to}, from={plivo_phone_number}, lead_id={lead_id}, dispatch_id={dispatch_id}")

    response = client.calls.create(
        from_=plivo_phone_number,
        to_=to_number,
        answer_url=webhook_url,
        answer_method="POST",
        hangup_url=hangup_url,
        hangup_method="POST",
    )

    call_id = getattr(response, "request_uuid", None) or getattr(response, "call_uuid", None) or str(response)
    logger.info(f"Plivo outbound call initiated successfully. Call ID: {call_id}")
    return str(call_id)


def main():
    parser = argparse.ArgumentParser(description="Place an outbound qualification call through Plivo")
    parser.add_argument("--to", required=True, help="Phone number to call, in E.164 format, e.g. +91XXXXXXXXXX")
    parser.add_argument("--company-context", default=None, help="Optional B2B record text to inject into the call")
    parser.add_argument("--lead-id", default=None, help="Optional Team A Lead ID for result correlation")
    args = parser.parse_args()

    place_outbound_call(args.to, company_context=args.company_context, lead_id=args.lead_id)


if __name__ == "__main__":
    main()