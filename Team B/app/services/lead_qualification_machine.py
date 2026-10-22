"""
lead_qualification_machine.py — Deterministic Lead Qualification State Machine
=============================================================================
Enforces deterministic business eligibility, lead qualification, and tool routing.

Key Responsibilities:
1. Deterministic State Machine: Tracks verified phone, name, qualification answers,
   prospect intent, consent, persistence status, and termination status.
2. Business-Critical Rules:
   - Phone confirmation ALONE does not save a lead.
   - Qualified prospect triggers save path.
   - Prospect decline ("not interested", "don't call") is strictly respected.
   - Pending save CANNOT be bypassed by premature end_call tool call.
   - Idempotent saving: Duplicate requests do not create duplicate records.
   - Honest failure surfacing: Persistence failures are not masked as successes.
"""

from dataclasses import dataclass, field
from enum import Enum
import re
import json
import asyncio
from typing import Dict, Any, Optional, Tuple, List
from loguru import logger


class QualificationState(str, Enum):
    COLLECTING = "COLLECTING"
    PHONE_PENDING_CONFIRMATION = "PHONE_PENDING_CONFIRMATION"
    PHONE_CONFIRMED = "PHONE_CONFIRMED"
    QUALIFIED = "QUALIFIED"
    SAVING = "SAVING"
    SAVED = "SAVED"
    SAVE_FAILED = "SAVE_FAILED"
    DECLINED = "DECLINED"
    TERMINATING = "TERMINATING"
    TERMINATED = "TERMINATED"


class ProspectIntent(str, Enum):
    UNDETERMINED = "UNDETERMINED"
    INTERESTED = "INTERESTED"
    REQUESTED_FOLLOWUP = "REQUESTED_FOLLOWUP"
    DECLINED = "DECLINED"
    NEUTRAL = "NEUTRAL"


# Stop words that should never be captured as names
NAME_STOP_WORDS = {
    "and", "or", "from", "with", "here", "phone", "number", "mobile",
    "is", "i", "calling", "need", "want", "a", "the", "for", "hai",
    "speaking", "looking", "interested", "fine", "good", "okay", "yes", "no",
    "not", "none", "bye", "wait", "thanks", "thank", "hello", "hi", "sara",
    "flowiz", "actually", "mera", "naam", "call", "dont", "do",
    "bol", "rahi", "raha", "hoon", "hun", "speaking", "here"
}

DECLINE_PATTERNS = [
    r"\bnot\s+interested\b",
    r"\bno\s+thanks?\b",
    r"\bdo\s*n'?t\s+call\b",
    r"\bdo\s+not\s+call\b",
    r"\bremove\s+(?:my\s+)?(?:number|me)\b",
    r"\bstop\s+calling\b",
    r"\bnahi\s+(?:chahiye|karni|sunna|hoga)\b",
    r"\bcall\s+mat\s+karna\b",
    r"\bkoi\s+zaroorat\s+nahi\b",
    r"\bmat\s+bhejo\b",
    r"\bnever\s+call\b",
    r"\bnot\s+looking\b",
    r"\bdrop\s+it\b",
]

FOLLOWUP_PATTERNS = [
    r"\b(?:call|reach)\s+(?:me\s+)?back\b",
    r"\bhave\s+(?:your\s+)?(?:team|sales|rep)\s+call\b",
    r"\bconnect\s+(?:me\s+)?(?:to|with)\s+(?:sales|your\s+team|someone)\b",
    r"\bschedule\s+(?:a\s+)?demo\b",
    r"\bsend\s+(?:me\s+)?(?:details|info|pricing|quotation)\b",
    r"\binterested\b",
    r"\bsales\s+se\s+baat\s+(?:karao|karni)\b",
    r"\bdemo\s+(?:chahiye|dikhao)\b",
    r"\bdetails\s+bhej\s+dijiye\b",
    r"\bwant\s+to\s+explore\b",
    r"\blooking\s+to\s+implement\b",
]


@dataclass
class LeadQualificationStateMachine:
    session_id: str = ""
    state: QualificationState = QualificationState.COLLECTING
    verified_phone: str = ""
    phone_confirmed: bool = False
    confirmed_name: Optional[str] = None
    crm: Optional[str] = None
    pain_points: Optional[str] = None
    budget: Optional[str] = None
    timeline: Optional[str] = None
    project_details: Optional[str] = None
    prospect_intent: ProspectIntent = ProspectIntent.UNDETERMINED
    follow_up_consent: Optional[bool] = None
    readback_given: bool = False
    save_status: str = "NOT_STARTED"  # NOT_STARTED, IN_PROGRESS, SUCCESS, FAILED, SKIPPED_DECLINED
    save_attempts: int = 0
    save_error: Optional[str] = None
    saved_lead_data: Optional[Dict[str, Any]] = None
    termination_status: str = "ACTIVE"  # ACTIVE, REQUESTED, TERMINATING, TERMINATED
    hangup_requested: bool = False
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def process_user_utterance(self, text: str, source: str = "USER_SPEECH") -> None:
        """Deterministically evaluates caller input and updates the qualification state."""
        if not text or source != "USER_SPEECH":
            return

        lower_text = text.lower().strip()

        # 1. Check for explicit decline / refusal
        if any(re.search(pat, lower_text) for pat in DECLINE_PATTERNS):
            logger.warning(
                f"[QUAL_MACHINE] Prospect explicit decline detected | "
                f"session={self.session_id} | text='{text}'"
            )
            self.prospect_intent = ProspectIntent.DECLINED
            self.follow_up_consent = False
            self.state = QualificationState.DECLINED
            self.save_status = "SKIPPED_DECLINED"
            return

        # 2. Check for explicit follow-up / interest
        if any(re.search(pat, lower_text) for pat in FOLLOWUP_PATTERNS):
            logger.info(
                f"[QUAL_MACHINE] Follow-up / Interest intent detected | "
                f"session={self.session_id} | text='{text}'"
            )
            self.prospect_intent = ProspectIntent.REQUESTED_FOLLOWUP
            self.follow_up_consent = True

        # 3. Check for Name extraction
        name_match = re.search(r"(?:my name is|i am|i'm|this is|mera naam|main|mai|call me)\s+([^,.\n!]+)", text, re.IGNORECASE)
        if name_match:
            raw_cand = name_match.group(1).strip()
            clean_words = []
            for w in raw_cand.split():
                if w.lower() in NAME_STOP_WORDS or not w.isalpha():
                    break
                clean_words.append(w)
                if len(clean_words) >= 3:
                    break
            if clean_words:
                cand_name = " ".join(clean_words).title()
                if cand_name.lower() not in NAME_STOP_WORDS:
                    self.confirmed_name = cand_name
                    logger.info(f"[QUAL_MACHINE] Confirmed Name detected: {self.confirmed_name} | session={self.session_id}")

        # 4. Check CRM detection
        crm_keywords = {
            "salesforce": "Salesforce",
            "hubspot": "HubSpot",
            "zoho": "Zoho CRM",
            "sap": "SAP ERP / CRM",
            "freshsales": "Freshsales",
            "freshworks": "Freshworks",
            "pipedrive": "Pipedrive",
            "leadsquared": "LeadSquared",
            "excel": "Excel / Spreadsheets",
            "sheets": "Google Sheets",
            "custom crm": "Custom Internal CRM",
        }
        for k, v in crm_keywords.items():
            if k in lower_text:
                self.crm = v
                logger.info(f"[QUAL_MACHINE] CRM detected: {self.crm} | session={self.session_id}")
                break
        if not self.crm and re.search(r'\bcrm\b', lower_text):
            self.crm = "CRM Integration"

        # 5. Check project requirements / use-case keywords
        project_req_patterns = [
            r"\b(?:automation|automate|outbound|calling|sdr|voice\s*agent|ai\s*agent|follow-?ups?|leads?|integration)\b"
        ]
        if any(re.search(pat, lower_text) for pat in project_req_patterns):
            if not self.project_details:
                self.project_details = "Voice calling automation & lead follow-up"

        # 6. Check pain points
        pain_matches = []
        if any(k in lower_text for k in ["latency", "delay", "slow", "deri"]):
            pain_matches.append("High latency / slow response times")
        if any(k in lower_text for k in ["dropped call", "drop off", "cut off", "call drop"]):
            pain_matches.append("Call drops and customer drop-off")
        if any(k in lower_text for k in ["manual", "follow up", "follow-up"]):
            pain_matches.append("Manual calling and slow follow-ups")
        if any(k in lower_text for k in ["scale", "volume"]):
            pain_matches.append("Scaling outbound call volume")
        if pain_matches:
            self.pain_points = "; ".join(pain_matches)
            logger.info(f"[QUAL_MACHINE] Pain points captured: {self.pain_points} | session={self.session_id}")

        # 6. Re-evaluate state transitions
        self._evaluate_state()

    def update_phone_state(self, digits: str, confirmed: bool, readback_given: Optional[bool] = None) -> None:
        """Updates verified phone digits, spoken readback delivery, and explicit confirmation status."""
        self.verified_phone = digits or ""
        self.phone_confirmed = confirmed
        if readback_given is not None:
            self.readback_given = readback_given
        elif confirmed:
            self.readback_given = True
        self._evaluate_state()

    def _evaluate_state(self) -> None:
        """Determines the current qualification state from tracked business criteria."""
        if self.state in (QualificationState.SAVED, QualificationState.TERMINATED):
            return

        if self.prospect_intent == ProspectIntent.DECLINED:
            self.state = QualificationState.DECLINED
            self.save_status = "SKIPPED_DECLINED"
            return

        has_valid_phone = len(self.verified_phone) == 10 and self.verified_phone[0] in "6789"
        has_valid_name = bool(self.confirmed_name and len(self.confirmed_name) >= 2)
        has_business_criteria = bool(self.crm or self.pain_points or self.project_details)
        has_intent = self.prospect_intent in (ProspectIntent.INTERESTED, ProspectIntent.REQUESTED_FOLLOWUP)

        if self.phone_confirmed and self.readback_given and has_valid_phone:
            # Check if all business qualification criteria are met
            if has_valid_name and (has_business_criteria or has_intent):
                self.state = QualificationState.QUALIFIED
            else:
                self.state = QualificationState.PHONE_CONFIRMED
        elif len(self.verified_phone) > 0:
            self.state = QualificationState.PHONE_PENDING_CONFIRMATION
        else:
            self.state = QualificationState.COLLECTING

    def is_eligible_for_save(self) -> Tuple[bool, str]:
        """
        Determines whether the lead satisfies all business requirements for persistence.
        Returns (True, '') if eligible, or (False, reason) if ineligible.
        """
        if self.state == QualificationState.DECLINED or self.prospect_intent == ProspectIntent.DECLINED:
            return False, "Prospect explicitly declined follow-up / refused contact."

        if not self.readback_given:
            return False, "Spoken readback of the phone number has not been delivered to the caller."

        if not self.phone_confirmed:
            return False, "Phone number has not been explicitly confirmed by the caller."

        if len(self.verified_phone) != 10 or self.verified_phone[0] not in "6789":
            return False, f"Phone number '{self.verified_phone}' is not a valid 10-digit Indian mobile."

        if not self.confirmed_name or len(self.confirmed_name) < 2:
            return False, "Caller name is missing or too short."

        has_business_criteria = bool(self.crm or self.pain_points or self.project_details)
        has_intent = self.prospect_intent in (ProspectIntent.INTERESTED, ProspectIntent.REQUESTED_FOLLOWUP)
        if not (has_business_criteria or has_intent):
            return False, "Qualification incomplete: No business requirements, CRM, or follow-up intent identified."

        if self.save_status == "SUCCESS":
            return False, "Lead has already been saved successfully (idempotent)."

        return True, "Eligible"

    def can_terminate_call(self) -> Tuple[bool, str]:
        """
        Evaluates whether an end_call tool call or termination request can proceed.
        Returns:
            (True, reason): Safe to terminate.
            (False, reason): Premature; pending qualified save must be executed first.
        """
        # 1. If prospect declined, termination is always immediately permitted
        if self.state == QualificationState.DECLINED or self.prospect_intent == ProspectIntent.DECLINED:
            return True, "Prospect declined; allow graceful termination without saving."

        # 2. If prospect is qualified but save has not completed, prevent premature loss
        if self.state == QualificationState.QUALIFIED and self.save_status in ("NOT_STARTED", "FAILED"):
            return False, "Prospect is qualified with pending save; lead must be saved before call termination."

        # 3. If lead was already saved, safe to terminate
        if self.save_status == "SUCCESS":
            return True, "Lead already saved; allow graceful termination."

        # 4. If prospect hangs up before qualifying, allow termination without saving
        return True, "Call terminating before qualification completion; no save required."

    async def execute_save(
        self,
        save_lead_func=None,
        params=None,
        custom_name: Optional[str] = None,
        custom_phone: Optional[str] = None,
        custom_details: Optional[str] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """
        Executes lead persistence idempotently and deterministically.
        Guarantees:
        - Atomic execution across concurrent tasks.
        - Prevents duplicate database entries.
        - Surfaces actual persistence errors honestly.
        """
        async with self._lock:
            # Idempotency check: If already successfully saved, return existing success
            if self.save_status == "SUCCESS":
                logger.info(
                    f"[QUAL_MACHINE] Idempotent save hit | session={self.session_id} | "
                    f"phone={self.verified_phone}"
                )
                if params and getattr(params, "result_callback", None):
                    await params.result_callback({
                        "status": "success",
                        "message": "Lead already saved successfully. Do not call save_lead again.",
                        "idempotent": True
                    })
                return {
                    "status": "success",
                    "message": "Lead already saved successfully.",
                    "idempotent": True,
                    "lead": self.saved_lead_data
                }

            # Eligibility verification
            if not force:
                eligible, reason = self.is_eligible_for_save()
                if not eligible:
                    logger.warning(
                        f"[QUAL_MACHINE] Save rejected due to eligibility | "
                        f"session={self.session_id} | reason='{reason}'"
                    )
                    if params and getattr(params, "result_callback", None):
                        await params.result_callback({
                            "status": "error",
                            "message": f"Validation Failed: {reason}"
                        })
                    return {"status": "error", "message": reason}

            self.state = QualificationState.SAVING
            self.save_status = "IN_PROGRESS"
            self.save_attempts += 1

            name = custom_name or self.confirmed_name or "Valued Prospect"
            phone = custom_phone or self.verified_phone
            details = custom_details or self.project_details or ""
            if not details:
                parts = []
                if self.crm:
                    parts.append(f"CRM: {self.crm}")
                if self.pain_points:
                    parts.append(f"Pain points: {self.pain_points}")
                if self.prospect_intent == ProspectIntent.REQUESTED_FOLLOWUP:
                    parts.append("Requested Sales Follow-up")
                details = "; ".join(parts) if parts else "Flowiz automation inquiry"

            try:
                if save_lead_func is None:
                    from app.services.lead_manager import save_lead
                    save_lead_func = save_lead

                # Execute persistence
                await save_lead_func(params, name, phone, details)

                # Check if save succeeded
                self.state = QualificationState.SAVED
                self.save_status = "SUCCESS"
                self.save_error = None
                self.saved_lead_data = {
                    "name": name,
                    "phone": phone,
                    "project_details": details
                }
                logger.info(
                    f"[QUAL_MACHINE] Lead saved successfully | session={self.session_id} | "
                    f"name='{name}', phone='{phone}'"
                )
                return {
                    "status": "success",
                    "message": "Lead saved successfully.",
                    "lead": self.saved_lead_data
                }

            except Exception as e:
                self.state = QualificationState.SAVE_FAILED
                self.save_status = "FAILED"
                self.save_error = str(e)
                logger.error(
                    f"[QUAL_MACHINE] Lead persistence failed | session={self.session_id} | "
                    f"error='{e}'"
                )
                if params and getattr(params, "result_callback", None):
                    await params.result_callback({
                        "status": "error",
                        "message": f"Failed to persist lead: {e}"
                    })
                return {"status": "error", "message": f"Persistence failure: {e}"}

    async def handle_end_call_request(self, save_lead_func=None, params=None) -> Dict[str, Any]:
        """
        Intercepts end_call requests. Prevents premature termination when a qualified lead is pending.
        """
        can_term, reason = self.can_terminate_call()
        if not can_term:
            logger.warning(
                f"[QUAL_MACHINE] Premature end_call blocked! {reason}. "
                f"Triggering deterministic lead save before termination."
            )
            # Deterministically save the qualified lead first
            save_res = await self.execute_save(save_lead_func=save_lead_func, params=params)
            if save_res.get("status") != "success":
                logger.error(
                    f"[QUAL_MACHINE] Automatic lead save failed during end_call: {save_res.get('message')}"
                )

        self.hangup_requested = True
        self.termination_status = "REQUESTED"
        if params and getattr(params, "result_callback", None):
            await params.result_callback({
                "success": True,
                "hangup_requested": True,
                "message": "Call ending initialized. Please say a brief goodbye to the user."
            })
        return {"success": True, "hangup_requested": True}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "state": self.state.value,
            "verified_phone": self.verified_phone,
            "readback_given": self.readback_given,
            "phone_confirmed": self.phone_confirmed,
            "confirmed_name": self.confirmed_name,
            "crm": self.crm,
            "pain_points": self.pain_points,
            "budget": self.budget,
            "timeline": self.timeline,
            "project_details": self.project_details,
            "prospect_intent": self.prospect_intent.value,
            "follow_up_consent": self.follow_up_consent,
            "save_status": self.save_status,
            "save_attempts": self.save_attempts,
            "save_error": self.save_error,
            "termination_status": self.termination_status,
            "hangup_requested": self.hangup_requested,
        }
