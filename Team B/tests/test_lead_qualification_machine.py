"""
test_lead_qualification_machine.py — Test Suite for Deterministic Lead Qualification Machine
============================================================================================
Validates:
1. Phone confirmation ALONE does not save a lead (incomplete qualification).
2. A qualified and eligible prospect triggers the save path.
3. An unqualified prospect is not incorrectly saved.
4. An explicit decline is strictly respected (no save, graceful termination).
5. A pending save cannot be bypassed by an premature/inappropriate end-call tool call.
6. Save failures are surfaced honestly and state marked as SAVE_FAILED.
7. Duplicate requests do not create duplicate leads (idempotent persistence).
8. Context manager & adapter integration with the state machine.
"""

import asyncio
import os
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.lead_qualification_machine import (
    LeadQualificationStateMachine,
    QualificationState,
    ProspectIntent,
)
from app.adapters.pipecat.context_manager import (
    CriticalCallMemory,
    SlidingWindowLLMContext,
)
from app.services.lead_manager import LEADS_FILE


class MockParams:
    def __init__(self):
        self.result = None

    async def result_callback(self, data):
        self.result = data


@pytest.fixture
def clean_leads_file(tmp_path):
    test_leads = tmp_path / "leads_test.json"
    with patch("app.services.lead_manager.LEADS_FILE", str(test_leads)):
        yield str(test_leads)


@pytest.mark.asyncio
async def test_phone_confirmation_alone_does_not_save_lead():
    """Requirement: Phone confirmation alone does not save a lead."""
    machine = LeadQualificationStateMachine(session_id="test_sess_1")
    machine.process_user_utterance("My number is 9876543210")
    machine.update_phone_state("9876543210", confirmed=True)

    # State should be PHONE_CONFIRMED, NOT QUALIFIED
    assert machine.state == QualificationState.PHONE_CONFIRMED
    assert machine.phone_confirmed is True
    assert machine.confirmed_name is None
    
    # Eligibility check must fail because name and business requirements are missing
    eligible, reason = machine.is_eligible_for_save()
    assert eligible is False
    assert "name is missing" in reason.lower()

    # Attempting to execute save should be rejected
    params = MockParams()
    res = await machine.execute_save(params=params)
    assert res["status"] == "error"
    assert machine.save_status != "SUCCESS"


@pytest.mark.asyncio
async def test_qualified_prospect_triggers_save_path(clean_leads_file):
    """Requirement: A qualified and eligible prospect triggers the save path."""
    machine = LeadQualificationStateMachine(session_id="test_sess_2")
    machine.process_user_utterance("My name is Rahul Manchanda, we use Salesforce and need automated follow-ups.")
    machine.process_user_utterance("My number is 9876543210")
    machine.process_user_utterance("Yes, exactly, that is my number. Please have your team call me.")
    machine.update_phone_state("9876543210", confirmed=True)

    assert machine.state == QualificationState.QUALIFIED
    assert machine.confirmed_name == "Rahul Manchanda"
    assert machine.crm == "Salesforce"
    assert machine.prospect_intent == ProspectIntent.REQUESTED_FOLLOWUP

    eligible, reason = machine.is_eligible_for_save()
    assert eligible is True
    assert reason == "Eligible"

    # Execute save
    params = MockParams()
    res = await machine.execute_save(params=params)
    assert res["status"] == "success"
    assert machine.state == QualificationState.SAVED
    assert machine.save_status == "SUCCESS"
    assert machine.saved_lead_data["name"] == "Rahul Manchanda"
    assert machine.saved_lead_data["phone"] == "9876543210"


@pytest.mark.asyncio
async def test_unqualified_prospect_is_not_incorrectly_saved():
    """Requirement: An unqualified prospect is not incorrectly saved."""
    machine = LeadQualificationStateMachine(session_id="test_sess_3")
    machine.process_user_utterance("Just browsing your website, nothing specific.")
    
    assert machine.state == QualificationState.COLLECTING
    eligible, reason = machine.is_eligible_for_save()
    assert eligible is False

    res = await machine.execute_save()
    assert res["status"] == "error"
    assert machine.state != QualificationState.SAVED


@pytest.mark.asyncio
async def test_prospect_decline_is_strictly_respected():
    """Requirement: A decline is respected (no save, immediate graceful termination)."""
    machine = LeadQualificationStateMachine(session_id="test_sess_4")
    machine.process_user_utterance("My name is John.")
    machine.process_user_utterance("9876543210")
    machine.update_phone_state("9876543210", confirmed=True)
    
    # Caller states refusal
    machine.process_user_utterance("Actually no thanks, I am not interested, please do not call me.")
    
    assert machine.state == QualificationState.DECLINED
    assert machine.prospect_intent == ProspectIntent.DECLINED
    assert machine.follow_up_consent is False
    assert machine.save_status == "SKIPPED_DECLINED"

    # Must be ineligible for save
    eligible, reason = machine.is_eligible_for_save()
    assert eligible is False
    assert "declined" in reason.lower()

    # Attempting to save must fail
    res = await machine.execute_save()
    assert res["status"] == "error"

    # Call termination must be permitted immediately
    can_term, term_reason = machine.can_terminate_call()
    assert can_term is True
    assert "declined" in term_reason.lower()


@pytest.mark.asyncio
async def test_pending_save_cannot_be_bypassed_by_end_call(clean_leads_file):
    """
    Requirement: A pending save cannot be bypassed by an inappropriate end-call tool call.
    (Fixes the GPT-4o-mini failure mode where end_call was called instead of save_lead).
    """
    machine = LeadQualificationStateMachine(session_id="test_sess_5")
    machine.process_user_utterance("My name is Anita Roy, we need outbound call automation.")
    machine.process_user_utterance("My number is 9876543210")
    machine.update_phone_state("9876543210", confirmed=True)
    machine.process_user_utterance("Yes, that is my number.")

    assert machine.state == QualificationState.QUALIFIED
    assert machine.save_status == "NOT_STARTED"

    # can_terminate_call should flag that save is pending
    can_term, reason = machine.can_terminate_call()
    assert can_term is False
    assert "pending save" in reason.lower()

    # When handle_end_call_request is executed, it MUST automatically save the lead first!
    params = MockParams()
    end_res = await machine.handle_end_call_request(params=params)
    assert end_res["success"] is True
    assert machine.hangup_requested is True

    # The lead MUST now be saved!
    assert machine.state == QualificationState.SAVED
    assert machine.save_status == "SUCCESS"
    assert machine.saved_lead_data["name"] == "Anita Roy"
    assert machine.saved_lead_data["phone"] == "9876543210"


@pytest.mark.asyncio
async def test_save_failures_are_surfaced_honestly():
    """Requirement: Save failures are surfaced honestly without masking."""
    machine = LeadQualificationStateMachine(session_id="test_sess_6")
    machine.process_user_utterance("My name is Dave, need help with CRM.")
    machine.process_user_utterance("9876543210")
    machine.update_phone_state("9876543210", confirmed=True)

    # Mock save_lead to simulate disk write failure
    async def mock_failing_save(params, name, phone, details):
        raise IOError("Disk full or database connection timeout")

    params = MockParams()
    res = await machine.execute_save(save_lead_func=mock_failing_save, params=params)

    assert res["status"] == "error"
    assert "Disk full" in res["message"]
    assert machine.state == QualificationState.SAVE_FAILED
    assert machine.save_status == "FAILED"
    assert machine.save_error is not None


@pytest.mark.asyncio
async def test_duplicate_requests_do_not_create_duplicate_leads(clean_leads_file):
    """Requirement: Duplicate requests do not create duplicate leads (idempotency)."""
    machine = LeadQualificationStateMachine(session_id="test_sess_7")
    machine.process_user_utterance("My name is Vikram.")
    machine.process_user_utterance("We use Zoho CRM.")
    machine.process_user_utterance("9876543210")
    machine.update_phone_state("9876543210", confirmed=True)

    # First save
    res1 = await machine.execute_save()
    assert res1["status"] == "success"
    assert machine.state == QualificationState.SAVED

    # Second save (retry / duplicate tool call)
    params2 = MockParams()
    res2 = await machine.execute_save(params=params2)
    assert res2["status"] == "success"
    assert res2.get("idempotent") is True
    assert machine.save_attempts == 1  # Did not attempt second write


@pytest.mark.asyncio
async def test_critical_call_memory_integration():
    """Tests synchronization between CriticalCallMemory and LeadQualificationStateMachine."""
    mem = CriticalCallMemory(session_id="test_sess_mem")
    
    # Turn 1: Name and CRM
    mem.extract_from_user_utterance("Hi, my name is Sunita. We use HubSpot.")
    assert mem.confirmed_name == "Sunita"
    assert mem.crm == "HubSpot"
    assert mem.qualification_machine.confirmed_name == "Sunita"
    assert mem.qualification_machine.crm == "HubSpot"

    # Turn 2: Spoken phone digits
    mem.extract_from_user_utterance("My number is 9876543210")
    assert mem.phone_digits == "9876543210"
    assert mem.qualification_machine.verified_phone == "9876543210"
    assert mem.phone_confirmed is False
    assert mem.readback_given is False

    # Turn 2.5: Assistant delivers spoken readback
    mem.extract_from_assistant_utterance("Just to confirm, your number is 9 8 7 6 5 4 3 2 1 0. Is that correct?")
    assert mem.readback_given is True
    assert mem.qualification_machine.readback_given is True

    # Turn 3: Caller explicit confirmation
    mem.extract_from_user_utterance("Yes, that is correct. Please have sales call me.")
    assert mem.phone_confirmed is True
    assert mem.qualification_machine.phone_confirmed is True
    assert mem.qualification_machine.state == QualificationState.QUALIFIED
    assert mem.qualification_machine.prospect_intent == ProspectIntent.REQUESTED_FOLLOWUP


@pytest.mark.asyncio
async def test_same_utterance_digits_and_affirmative_rejected():
    """Requirement: The assistant must not mistake digits stated alongside conversational affirmations for caller confirmation."""
    mem = CriticalCallMemory(session_id="test_same_turn")
    mem.extract_from_user_utterance("My name is Karan.")

    # Caller speaks digits with 'right now' and 'ji' in the same utterance
    mem.extract_from_user_utterance("My number is 9876543210 right now ji.")
    assert mem.phone_digits == "9876543210"
    assert mem.phone_confirmed is False
    assert mem.readback_given is False
    assert mem.qualification_machine.phone_confirmed is False
    assert mem.qualification_machine.state == QualificationState.PHONE_PENDING_CONFIRMATION


@pytest.mark.asyncio
async def test_confirmation_deferred_until_assistant_spoken_readback():
    """Requirement: Caller saying 'yes' without assistant readback is deferred."""
    mem = CriticalCallMemory(session_id="test_no_readback")
    mem.extract_from_user_utterance("Hi, my name is Priya.")
    mem.extract_from_user_utterance("Contact is 9123456780.")

    # Caller says 'yes' but assistant never spoke readback
    mem.extract_from_user_utterance("Yes exactly.")
    assert mem.phone_confirmed is False
    assert mem.readback_given is False
    assert mem.qualification_machine.phone_confirmed is False


@pytest.mark.asyncio
async def test_digit_correction_after_readback_resets_confirmation():
    """Requirement: Caller correcting digits after readback resets confirmation and requires fresh readback."""
    mem = CriticalCallMemory(session_id="test_correction")
    mem.extract_from_user_utterance("My name is Aman.")
    mem.extract_from_user_utterance("9876543210")
    mem.extract_from_assistant_utterance("Just to confirm, is 9 8 7 6 5 4 3 2 1 0 correct?")
    assert mem.readback_given is True

    # Caller says 'no wrong, last digit is 1'
    mem.extract_from_user_utterance("No wrong, the last digit is one not zero, it is 9876543211.")
    assert mem.phone_digits == "9876543211"
    assert mem.phone_confirmed is False
    assert mem.readback_given is False
    assert mem.qualification_machine.phone_confirmed is False

    # Second readback
    mem.extract_from_assistant_utterance("Understood, let me confirm: 9 8 7 6 5 4 3 2 1 1. Is that right?")
    assert mem.readback_given is True

    # Explicit confirmation
    mem.extract_from_user_utterance("Haan sahi hai.")
    assert mem.phone_confirmed is True
    assert mem.qualification_machine.phone_confirmed is True


@pytest.mark.asyncio
async def test_invalid_indian_mobile_prefix_rejected(clean_leads_file):
    """Requirement: Enforce valid 10-digit Indian mobile validation (starting with 6, 7, 8, 9)."""
    machine = LeadQualificationStateMachine(session_id="test_invalid_prefix")
    machine.process_user_utterance("My name is John Doe, we use HubSpot.")
    # Number starting with 5 (invalid in India)
    machine.update_phone_state("5123456789", confirmed=True, readback_given=True)

    eligible, reason = machine.is_eligible_for_save()
    assert eligible is False
    assert "not a valid 10-digit indian mobile" in reason.lower()

    # Lead manager directly rejects as well
    from app.services.lead_manager import save_lead
    params = MockParams()
    await save_lead(params, "John Doe", "5123456789", "CRM inquiry")
    assert params.result["status"] == "error"
    assert "valid indian mobile" in params.result["message"].lower()


@pytest.mark.asyncio
async def test_consent_withdrawal_and_hangup_during_qualification():
    """Requirement: Caller refusal or consent withdrawal stops qualification and allows hangup."""
    machine = LeadQualificationStateMachine(session_id="test_consent_withdrawn")
    machine.process_user_utterance("My name is Sara.")
    machine.process_user_utterance("9876543210")
    machine.update_phone_state("9876543210", confirmed=True, readback_given=True)

    # Caller withdraws consent
    machine.process_user_utterance("Actually stop calling, koi zaroorat nahi hai, remove my number.")
    assert machine.state == QualificationState.DECLINED
    assert machine.follow_up_consent is False
    assert machine.prospect_intent == ProspectIntent.DECLINED

    can_term, reason = machine.can_terminate_call()
    assert can_term is True
    assert "declined" in reason.lower()

    # Attempting to save must be rejected
    res = await machine.execute_save()
    assert res["status"] == "error"


@pytest.mark.asyncio
async def test_durable_file_lock_concurrent_saves(clean_leads_file):
    """Requirement: Multi-worker durable idempotency and lock protection across concurrent save attempts."""
    from app.services.lead_manager import save_lead

    # Run 5 concurrent calls to save_lead for the exact same phone number
    tasks = []
    for i in range(5):
        params = MockParams()
        tasks.append(save_lead(params, f"Prospect {i}", "9876543210", f"Details {i}"))

    await asyncio.gather(*tasks)

    # Verify only ONE entry was written to LEADS_FILE
    with open(clean_leads_file, "r") as f:
        saved_leads = json.load(f)

    matching_leads = [lead for lead in saved_leads if lead.get("phone") == "9876543210"]
    assert len(matching_leads) == 1
    assert matching_leads[0]["phone"] == "9876543210"


def _worker_multiprocess_persist(leads_file: str, name: str, phone: str, q):
    """Multiprocessing worker function."""
    from app.services.lead_manager import _persist_lead_sync
    lead_entry = {"timestamp": "2026-10-11T00:00:00", "name": name, "phone": phone, "project_details": "concurrency test"}
    success, is_dup, err = _persist_lead_sync(lead_entry, phone, leads_file=leads_file)
    q.put((success, is_dup, err))


def test_cross_process_multiprocessing_locking_and_deduplication(clean_leads_file):
    """Requirement: Real cross-process fcntl.flock locking and duplicate prevention across OS processes."""
    import multiprocessing

    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()

    # 4 distinct OS processes trying to save the SAME phone number simultaneously
    processes = []
    for i in range(4):
        p = ctx.Process(
            target=_worker_multiprocess_persist,
            args=(clean_leads_file, f"Worker {i}", "9876543210", q)
        )
        processes.append(p)
        p.start()

    for p in processes:
        p.join(timeout=5)

    results = []
    while not q.empty():
        results.append(q.get())

    assert len(results) == 4
    # All must report success
    assert all(r[0] is True for r in results)
    # Exactly one process inserted, remaining 3 detected duplicate
    duplicates = [r for r in results if r[1] is True]
    inserted = [r for r in results if r[1] is False]
    assert len(inserted) == 1
    assert len(duplicates) == 3

    with open(clean_leads_file, "r") as f:
        saved = json.load(f)
    assert len(saved) == 1
    assert saved[0]["phone"] == "9876543210"


def test_cross_process_multiple_distinct_leads(clean_leads_file):
    """Requirement: Real cross-process fcntl.flock allows distinct leads without corruption."""
    import multiprocessing

    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()

    processes = []
    for i in range(4):
        phone = f"987654321{i}"
        p = ctx.Process(
            target=_worker_multiprocess_persist,
            args=(clean_leads_file, f"Client {i}", phone, q)
        )
        processes.append(p)
        p.start()

    for p in processes:
        p.join(timeout=5)

    results = []
    while not q.empty():
        results.append(q.get())

    assert len(results) == 4
    assert all(r[0] is True and r[1] is False for r in results)

    with open(clean_leads_file, "r") as f:
        saved = json.load(f)
    assert len(saved) == 4
    saved_phones = {l["phone"] for l in saved}
    assert saved_phones == {f"987654321{i}" for i in range(4)}


def test_corrupted_json_recovery_and_backup(clean_leads_file):
    """Requirement: If leads.json is corrupted, it backs up and self-heals rather than failing."""
    from app.services.lead_manager import _persist_lead_sync

    # Write corrupt data
    with open(clean_leads_file, "w") as f:
        f.write("{corrupted_json_data!!!")

    lead_entry = {"timestamp": "2026-10-11T00:00:00", "name": "Alice", "phone": "9876543210", "project_details": "Recovery"}
    success, is_dup, err = _persist_lead_sync(lead_entry, "9876543210", leads_file=clean_leads_file)
    assert success is True
    assert is_dup is False

    with open(clean_leads_file, "r") as f:
        saved = json.load(f)
    assert len(saved) == 1
    assert saved[0]["phone"] == "9876543210"


@pytest.mark.asyncio
async def test_readback_interruption_invalidates_confirmation():
    """Requirement: Assistant readback cancelled/interrupted by caller speech resets readback_given."""
    memory = CriticalCallMemory(session_id="test_readback_interrupt")
    
    # 1. Caller provides 10 digits
    memory.extract_from_user_utterance("My number is 9876543210", source="USER_SPEECH")
    assert memory.phone_digits == "9876543210"
    assert memory.readback_given is False
    assert memory.phone_confirmed is False

    # 2. Assistant starts reading back: "Just to confirm, is your number 9 8 7 6 5 4 3 2 1 0?"
    memory.extract_from_assistant_utterance("Just to confirm, your number is 9 8 7 6 5 4 3 2 1 0, is that correct?")
    assert memory.readback_given is True

    # 3. Caller barges in / interrupts assistant BEFORE confirmation completes
    memory.on_interruption()
    assert memory.readback_given is False  # Must be reset!

    # 4. Caller says "yes" immediately after interrupting
    memory.extract_from_user_utterance("Yes", source="USER_SPEECH")
    # Must NOT confirm because readback was interrupted
    assert memory.phone_confirmed is False

    # 5. Assistant properly re-reads back without interruption
    memory.extract_from_assistant_utterance("Let me read that back: 9 8 7 6 5 4 3 2 1 0. Is that correct?")
    assert memory.readback_given is True

    # 6. Caller confirms on subsequent turn
    memory.extract_from_user_utterance("Yes, that is correct", source="USER_SPEECH")
    assert memory.phone_confirmed is True


@pytest.mark.asyncio
async def test_corrected_number_invalidates_readback_and_confirmation():
    """Requirement: Corrected phone number invalidates stale readback and confirmation state."""
    memory = CriticalCallMemory(session_id="test_corrected_number")
    memory.extract_from_user_utterance("Call me on 9876543210", source="USER_SPEECH")
    memory.extract_from_assistant_utterance("Just to confirm, your number is 9876543210?")
    memory.extract_from_user_utterance("Yes, that is right", source="USER_SPEECH")
    assert memory.phone_confirmed is True

    # Caller changes their mind: "Wait, no, my new number is 9811122233"
    memory.extract_from_user_utterance("Wait, actually my number is 9811122233", source="USER_SPEECH")
    assert memory.phone_digits == "9811122233"
    assert memory.phone_confirmed is False  # Must be invalidated
    assert memory.readback_given is False   # Must be invalidated

