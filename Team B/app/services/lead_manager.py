import json
import os
import asyncio
from datetime import datetime
from loguru import logger

LEADS_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "leads.json"))

_leads_lock = asyncio.Lock()

def _normalize_phone(phone: str) -> str:
    """Normalize an Indian phone number to exactly 10 digits.
    
    Supports words, colons, spaces, and prefixes:
    - +91XXXXXXXXXX  → XXXXXXXXXX
    - 91XXXXXXXXXX   → XXXXXXXXXX
    - 0XXXXXXXXXX    → XXXXXXXXXX
    """
    if not phone:
        return ""
    try:
        from app.services.phone_digit_normalizer import PhoneDigitNormalizer
        cands = PhoneDigitNormalizer.extract_turn_candidates(phone)
        for cand in cands:
            norm = PhoneDigitNormalizer._normalize_complete_number(cand)
            if norm and len(norm) == 10:
                return norm
    except Exception:
        pass

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

    if len(digits) != 10 or digits[0] not in "6789":
        logger.warning(f"ACTIONABLE AI: 'save_lead' failed validation! Phone '{phone}' normalized to '{digits}' (expected 10 digits starting with 6, 7, 8, or 9).")
        if getattr(params, "result_callback", None):
            await params.result_callback({
                "status": "error",
                "message": (
                    f"Validation Failed: The phone number '{phone}' is invalid — "
                    f"valid Indian mobile numbers must be exactly 10 digits starting with 6, 7, 8, or 9. "
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
            success, is_duplicate, err_msg = await asyncio.to_thread(
                _persist_lead_sync, lead_entry, phone, LEADS_FILE
            )
            
        if is_duplicate:
            logger.info(f"save_lead: Lead with phone {phone} was already saved. Skipping duplicate insertion.")
            if getattr(params, "result_callback", None):
                await params.result_callback({
                    "status": "success",
                    "message": "Lead already saved successfully. Do not call save_lead again for this user.",
                    "idempotent": True
                })
            return

        if not success:
            raise RuntimeError(err_msg or "Failed to persist lead")
            
        logger.info(f"Lead saved successfully to {LEADS_FILE}")
        
        # Return success back to the LLM so it can inform the user
        if getattr(params, "result_callback", None):
            await params.result_callback({"status": "success", "message": "Lead saved successfully."})
        
    except Exception as e:
        logger.error(f"Failed to save lead: {e}")
        if getattr(params, "result_callback", None):
            await params.result_callback({"status": "error", "message": f"Failed to save lead: {e}"})


def _cleanup_stale_temp_files(dir_path: str, max_age_seconds: float = 60.0):
    """Cleans up abandoned .tmp files from previous crashed processes."""
    import time
    try:
        now = time.time()
        for fname in os.listdir(dir_path):
            if fname.startswith("leads.json.tmp."):
                full_path = os.path.join(dir_path, fname)
                try:
                    if os.path.isfile(full_path) and (now - os.path.getmtime(full_path) > max_age_seconds):
                        os.unlink(full_path)
                except OSError:
                    pass
    except Exception:
        pass


def _persist_lead_sync(lead_entry: dict, phone: str, leads_file: str = LEADS_FILE) -> tuple:
    """Synchronous cross-process atomic persistence with durable file locking.
    
    Returns:
        (success: bool, is_duplicate: bool, error_msg: str)
    """
    import fcntl
    import uuid
    import time

    leads_dir = os.path.dirname(os.path.abspath(leads_file))
    os.makedirs(leads_dir, exist_ok=True)
    _cleanup_stale_temp_files(leads_dir, max_age_seconds=60.0)

    lock_file_path = f"{leads_file}.lock"
    temp_file = None

    # Open with 'a' (append) mode to avoid truncating while another process holds an open fd
    with open(lock_file_path, "a") as lock_f:
        fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
        try:
            leads = []
            if os.path.exists(leads_file):
                try:
                    with open(leads_file, "r", encoding="utf-8") as f:
                        content = f.read().strip()
                        if content:
                            leads = json.loads(content)
                except Exception as read_err:
                    corrupt_backup = f"{leads_file}.corrupt.{int(time.time())}"
                    logger.error(f"[LEAD_PERSISTENCE] Corrupt {leads_file} ({read_err}); backing up to {corrupt_backup}")
                    try:
                        os.replace(leads_file, corrupt_backup)
                    except OSError:
                        pass
                    leads = []

            # Multi-process duplicate lead prevention (durable idempotency)
            saved_phones = {lead.get("phone") for lead in leads if isinstance(lead, dict) and lead.get("phone")}
            if phone in saved_phones:
                return (True, True, "")

            leads.append(lead_entry)

            # Atomic write to temporary file followed by fsync and atomic rename
            temp_file = f"{leads_file}.tmp.{os.getpid()}_{uuid.uuid4().hex}"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(leads, f, indent=4)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_file, leads_file)
            temp_file = None
            return (True, False, "")
        except Exception as e:
            return (False, False, str(e))
        finally:
            if temp_file and os.path.exists(temp_file):
                try:
                    os.unlink(temp_file)
                except OSError:
                    pass
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)


