"""
test_voice_scenarios_phone_capture.py — Execution of 12 Real Voice Scenarios
============================================================================
Executes and measures the 12 specified voice/STT scenarios:
1. Slow individual digits
2. Fast individual digits
3. Groups of 2-3 digits
4. Full number in one sentence
5. Hindi (Devanagari speech)
6. Hinglish
7. Number with pauses
8. User repeats a digit
9. User corrects a digit
10. Noisy environment with background speech
11. STT outputs colon-separated time-like tokens
12. User speaks conversational words between digits

Measures required metrics (Step 20):
- raw STT transcript
- normalized digits
- buffer before turn
- extracted digits
- buffer after turn
- duplicate detection
- overflow detection
- validation result
"""

import json
from app.services.phone_digit_normalizer import (
    PhoneDigitNormalizer,
    PhoneCaptureStatus,
    mask_phone_number,
    is_valid_indian_mobile,
)


def run_scenario(scenario_num: int, scenario_name: str, utterances: list) -> dict:
    normalizer = PhoneDigitNormalizer(session_id=f"voice_scen_{scenario_num}")
    results = []

    for turn_idx, text in enumerate(utterances, 1):
        buf_before = normalizer.digits
        status = normalizer.process_utterance(text)
        buf_after = normalizer.digits
        action = normalizer.last_action

        results.append({
            "turn": turn_idx,
            "raw_stt": text,
            "buffer_before_masked": mask_phone_number(buf_before),
            "buffer_after_masked": mask_phone_number(buf_after),
            "digits_count": len(buf_after),
            "action": action,
            "status": status.value,
        })

    is_valid = is_valid_indian_mobile(normalizer.digits)
    return {
        "scenario": scenario_num,
        "name": scenario_name,
        "final_digits_masked": normalizer.masked_digits,
        "final_digits_count": len(normalizer.digits),
        "is_valid": is_valid,
        "final_status": normalizer.status.value,
        "turns": results,
    }


def test_12_voice_scenarios():
    scenarios = [
        (1, "Slow individual digits", ["9", "8", "7", "6", "5", "4", "3", "2", "1", "0"]),
        (2, "Fast individual digits", ["9 8 7 6 5 4 3 2 1 0"]),
        (3, "Groups of 2-3 digits", ["987", "654", "32", "10"]),
        (4, "Full number in one sentence", ["Please note down my phone number 9876543210 thank you"]),
        (5, "Hindi Devanagari speech", ["नौ आठ सात छह पाँच", "चार तीन दो एक शून्य"]),
        (6, "Hinglish speech", ["mera number hai nau aath saat", "chhah paanch chaar teen do ek zero"]),
        (7, "Number with pauses", ["98765", "", "43210"]),
        (8, "User repeats a digit intentionally", ["98765", "543210"]),
        (9, "User corrects a digit", ["9876543218", "last digit 8 nahi 9"]),
        (10, "Noisy environment with background speech", ["987 wait hold on 654", "yes sir 3210"]),
        (11, "STT outputs colon-separated time-like tokens", ["921 05:02", "4 04:01"]),
        (12, "Conversational words between digits", ["92 sun lo", "then 150", "and last 24 401"]),
    ]

    all_reports = []
    for num, name, utts in scenarios:
        report = run_scenario(num, name, utts)
        all_reports.append(report)
        assert report["is_valid"] is True, f"Scenario {num} failed: {report}"
        assert report["final_digits_count"] == 10, f"Scenario {num} expected 10 digits: {report}"

    print(json.dumps(all_reports, indent=2))


if __name__ == "__main__":
    test_12_voice_scenarios()
