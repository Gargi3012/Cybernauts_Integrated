import json
import os
import asyncio
from datetime import datetime
from loguru import logger

LEADS_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "leads.json"))

_leads_lock = asyncio.Lock()

def _normalize_phone(phone: str) -> str:
    """Normalize an Indian phone number to exactly 10 digits.
    
    Strips common prefixes spoken by users:
    - +91XXXXXXXXXX  → XXXXXXXXXX  (12 chars with +)
    - 91XXXXXXXXXX   → XXXXXXXXXX  (12 digits)
    - 0XXXXXXXXXX    → XXXXXXXXXX  (11 digits, landline-style)
    """
    import re
    digits = re.sub(r'\D', '', phone)
    # Strip +91 / 91 country-code prefix (leaves 10 digits for Indian mobile)
    if len(digits) == 12 and digits.startswith('91'):
        digits = digits[2:]
    # Strip leading STD trunk '0' (e.g., 07012345678 → 7012345678)
    elif len(digits) == 11 and digits.startswith('0'):
        digits = digits[1:]
    return digits


async def save_lead(params, name: str, phone: str, project_details: str = ""):
    """Save the caller's lead details (Name, Phone number, and project requirements) to the database.
    
    This tool should ONLY be called after the user has explicitly provided both their name and phone number
    AND you have read the phone number back to them and they have CONFIRMED it is correct.
    Do NOT call this tool with placeholder data.
    
    Args:
        name (str): The name of the user/caller.
        phone (str): The phone number of the user/caller.
        project_details (str): Summary of what the user wants to build or their project requirements.
    """
    import re

    # --- Name validation ---
    clean_name = (name or "").strip()
    if len(clean_name) < 2:
        logger.warning(f"ACTIONABLE AI: 'save_lead' failed validation! Name '{name}' is too short.")
        if getattr(params, "result_callback", None):
            await params.result_callback({
                "status": "error",
                "message": "Validation Failed: The name provided is missing or too short. Please ask the user to clearly state their full name."
            })
        return

    # --- Phone normalization & validation ---
    digits = _normalize_phone(phone)

    if len(digits) != 10:
        logger.warning(f"ACTIONABLE AI: 'save_lead' failed validation! Phone '{phone}' normalized to '{digits}' ({len(digits)} digits, expected 10).")
        if getattr(params, "result_callback", None):
            await params.result_callback({
                "status": "error",
                "message": (
                    f"Validation Failed: The phone number '{phone}' is invalid — it normalized to {len(digits)} digits "
                    f"but Indian mobile numbers must be exactly 10 digits. "
                    f"Tell the user: 'I'm sorry, that doesn't seem like a valid 10-digit Indian mobile number. "
                    f"Could you please say your number digit by digit?' Then try again after they confirm."
                )
            })
        return

    # Hash or mask PII in logs — use the normalized digits for storage
    phone = digits  # persist only the clean 10-digit value
    masked_phone = f"{phone[:3]}******{phone[-4:]}" if len(phone) > 7 else "***"
    logger.info(f"ACTIONABLE AI: Triggered 'save_lead' tool! Name: {clean_name[:2]}***, Phone: {masked_phone}, Project: {project_details}")
    
    lead_entry = {
        "timestamp": datetime.now().isoformat(),
        "name": clean_name,
        "phone": phone,
        "project_details": project_details
    }
    
    try:
        async with _leads_lock:
            leads = []
            if os.path.exists(LEADS_FILE):
                with open(LEADS_FILE, "r") as f:
                    content = f.read().strip()
                    if content:
                        leads = json.loads(content)
                        
            # Prevent duplicate lead creation
            recent_phones = [lead.get("phone") for lead in leads[-10:]]
            if phone in recent_phones:
                logger.info(f"save_lead: Lead with phone {phone} was already saved recently. Skipping duplicate insertion.")
                if getattr(params, "result_callback", None):
                    await params.result_callback({"status": "success", "message": "Lead already saved successfully. Do not call save_lead again for this user."})
                return
            
            leads.append(lead_entry)
            
            with open(LEADS_FILE, "w") as f:
                json.dump(leads, f, indent=4)
            
        logger.info(f"Lead saved successfully to {LEADS_FILE}")
        
        # Return success back to the LLM so it can inform the user
        if getattr(params, "result_callback", None):
            await params.result_callback({"status": "success", "message": "Lead saved successfully."})
        
    except Exception as e:
        logger.error(f"Failed to save lead: {e}")
        if getattr(params, "result_callback", None):
            await params.result_callback({"status": "error", "message": "Failed to save lead."})

