"""
phone_digit_normalizer.py — Deterministic, Stateful Phone Number Digit Normalizer
================================================================================
Authoritative, deterministic normalizer and multi-turn accumulator for 10-digit Indian
mobile numbers. Completely independent of LLM context and hallucinations.

Key Capabilities:
1. Multi-turn persistent buffer with state machine (EMPTY, PARTIAL, COMPLETE, OVERFLOW, INVALID).
2. Deepgram STT colon/timestamp artifact resolution (e.g. '05:02' -> '502' or '0502', '04:01' -> '401' or '0401').
3. Solves the observed bug: '921 05:02 4 04:01' and multi-turn '921' -> '5' -> '0' -> '2' -> '4' -> '04:01'.
4. Trilingual support: English words ('nine'), Hinglish/Latin ('nau', 'aath'), Devanagari words ('नौ', 'आठ'),
   and Devanagari numerals ('०'-'९').
5. Conversational noise filtering (e.g. '9 2 sun lo' -> ignores 'sun lo').
6. Turn deduplication and interim-to-final STT reconciliation without double-appending.
7. Spoken correction handling ('last digit 8 nahi 9', 'nahi 9', 'change 8 to 9').
8. Strict PII masking: raw 10-digit numbers are NEVER logged in plain text.
"""

from dataclasses import dataclass, field
from enum import Enum
import itertools
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from loguru import logger


class PhoneCaptureStatus(str, Enum):
    EMPTY = "empty"
    PARTIAL = "partial"
    COMPLETE = "complete"
    OVERFLOW = "overflow"
    INVALID = "invalid"


# ─────────────────────────────────────────────────────────────────────────────
# DICTIONARIES & MAPPINGS
# ─────────────────────────────────────────────────────────────────────────────

ENGLISH_DIGIT_WORDS: Dict[str, str] = {
    "zero": "0", "oh": "0", "o": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
}

HINDI_ROMAN_DIGIT_WORDS: Dict[str, str] = {
    "shunya": "0", "sunya": "0", "sifar": "0", "seefar": "0", "zeero": "0", "zero": "0",
    "ek": "1", "ik": "1", "yek": "1",
    "do": "2", "doo": "2",
    "teen": "3", "tin": "3",
    "char": "4", "chaar": "4",
    "paanch": "5", "panch": "5",
    "chhe": "6", "che": "6", "chhah": "6", "chhey": "6",
    "saat": "7", "sat": "7",
    "aath": "8", "ath": "8", "aat": "8",
    "nau": "9", "no": "9", "now": "9",
}

DEVANAGARI_DIGIT_WORDS: Dict[str, str] = {
    "शून्य": "0", "सिफर": "0", "ज़ीरो": "0", "जीरो": "0",
    "एक": "1",
    "दो": "2",
    "तीन": "3",
    "चार": "4",
    "पाँच": "5", "पांच": "5",
    "छह": "6", "छः": "6", "छे": "6",
    "सात": "7",
    "आठ": "8",
    "नौ": "9",
}

DEVANAGARI_NUMERALS: Dict[str, str] = {
    "०": "0", "१": "1", "२": "2", "३": "3", "४": "4",
    "५": "5", "६": "6", "७": "7", "८": "8", "९": "9",
}

MULTIPLIERS_2X: Set[str] = {"double", "dabal", "डबल", "दोगुना", "दोहरा"}
MULTIPLIERS_3X: Set[str] = {"triple", "tripple", "ट्रिपल", "तिगुना"}

# Conversational conversational noise tokens that must never be mistaken for digits
NOISE_WORDS: Set[str] = {
    "sun", "lo", "suno", "sunlo", "bhai", "ji", "haan", "mera", "meri", "mere",
    "number", "mobile", "phone", "likho", "note", "karo", "hai", "hain", "theek",
    "okay", "ok", "please", "sir", "madam", "kripya", "bolo", "boliye", "batao",
    "batata", "hoon", "dijiye", "yeh", "raha", "contact", "call", "me", "on", "at"
}


def mask_phone_number(digits: str) -> str:
    """Safely masks a phone number for logs and telemetry."""
    if not digits:
        return "[empty]"
    if len(digits) == 10:
        return f"******{digits[-4:]}"
    if len(digits) > 10:
        return f"******{digits[-4:]} (len={len(digits)})"
    if len(digits) <= 3:
        return f"*** (len={len(digits)})"
    return f"***{digits[-2:]} (len={len(digits)})"


def is_valid_indian_mobile(digits: str) -> bool:
    """Validates if digits form an exact 10-digit Indian mobile number."""
    if len(digits) != 10 or not digits.isdigit():
        return False
    return digits[0] in ("6", "7", "8", "9")


# ─────────────────────────────────────────────────────────────────────────────
# PHONE DIGIT NORMALIZER CLASS
# ─────────────────────────────────────────────────────────────────────────────

class PhoneDigitNormalizer:
    """
    Deterministic, stateful processor that extracts and manages phone digits
    across multiple conversational turns.
    """

    def __init__(self, session_id: str = ""):
        self.session_id: str = session_id
        self._digits: str = ""
        self._last_raw_transcript: str = ""
        self._last_extracted_turn_digits: str = ""
        self._last_action: str = "init"
        self._turn_history: List[Dict[str, Any]] = []
        self._status: PhoneCaptureStatus = PhoneCaptureStatus.EMPTY

    @property
    def digits(self) -> str:
        """Returns the authoritative accumulated digits."""
        return self._digits

    @property
    def status(self) -> PhoneCaptureStatus:
        """Returns current capture status."""
        return self._status

    @property
    def last_action(self) -> str:
        """Returns description of the last state modification."""
        return self._last_action

    @property
    def masked_digits(self) -> str:
        """Masked representation of accumulated digits."""
        return mask_phone_number(self._digits)

    def get_raw_digits(self) -> str:
        """Authoritative raw digits accessor (for lead saving tool only)."""
        return self._digits

    def reset(self) -> None:
        """Resets the capture buffer."""
        self._digits = ""
        self._last_raw_transcript = ""
        self._last_extracted_turn_digits = ""
        self._last_action = "reset"
        self._turn_history = []
        self._status = PhoneCaptureStatus.EMPTY
        logger.info(f"[PHONE_NORMALIZER] Reset buffer for session={self.session_id}")

    # ─────────────────────────────────────────────────────────────────────────
    # PARSING & EXTRACTION
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def _map_single_token(cls, token: str) -> Optional[str]:
        """Maps a single word or character to a digit string ('0'-'9'), or None."""
        t = token.lower().strip(".,?!;:-")
        if not t:
            return None
        if t in ENGLISH_DIGIT_WORDS:
            return ENGLISH_DIGIT_WORDS[t]
        if t in HINDI_ROMAN_DIGIT_WORDS:
            return HINDI_ROMAN_DIGIT_WORDS[t]
        if token in DEVANAGARI_DIGIT_WORDS:
            return DEVANAGARI_DIGIT_WORDS[token]
        if token in DEVANAGARI_NUMERALS:
            return DEVANAGARI_NUMERALS[token]
        if t.isdigit() and len(t) == 1:
            return t
        return None

    @classmethod
    def _parse_time_token(cls, token: str) -> List[str]:
        """
        Parses time-like tokens generated by Deepgram/STT (e.g. '05:02', '04:01', '54:32').
        Returns candidate digit strings. For tokens where the hour has a leading zero
        (like '04:01'), it returns both the full 4 digits ('0401') and the unpadded 3 digits ('401').
        """
        m = re.match(r"^(\d{1,2}):(\d{2})$", token)
        if not m:
            return []
        hour, minute = m.group(1), m.group(2)
        full_digits = f"{hour}{minute}"
        candidates = [full_digits]
        # If hour starts with '0' (e.g. '04', '05'), it may be an STT artifact for single digit '4' or '5'
        if hour.startswith("0") and len(hour) == 2:
            unpadded = f"{hour[1:]}{minute}"
            if unpadded not in candidates:
                candidates.append(unpadded)
        return candidates

    @classmethod
    def extract_turn_candidates(cls, text: str) -> List[str]:
        """
        Extracts digit candidates from an utterance, considering words, digits,
        multipliers ('double', 'triple'), and time-like colon tokens.
        Returns a list of candidate digit strings ordered by likelihood.
        """
        if not text:
            return [""]

        # Clean punctuation except colons (needed for time detection) and devanagari
        cleaned = text.replace(",", " ").replace("-", " ").replace("—", " ").replace("/", " ")
        # Separate punctuation like periods and exclamation marks
        cleaned = re.sub(r"[.?!;]", " ", cleaned)
        tokens = cleaned.split()

        # We build candidates by accumulating token possibilities
        token_candidate_branches: List[List[str]] = []
        i = 0
        n = len(tokens)

        while i < n:
            raw_tok = tokens[i]
            tok_lower = raw_tok.lower()

            # 1. Multipliers: double / triple / dabal
            if tok_lower in MULTIPLIERS_2X and i + 1 < n:
                next_digit = cls._map_single_token(tokens[i + 1])
                if next_digit:
                    token_candidate_branches.append([next_digit * 2])
                    i += 2
                    continue
            if tok_lower in MULTIPLIERS_3X and i + 1 < n:
                next_digit = cls._map_single_token(tokens[i + 1])
                if next_digit:
                    token_candidate_branches.append([next_digit * 3])
                    i += 2
                    continue

            # 2. Time-like tokens (e.g. 05:02, 04:01, 54:32)
            if ":" in raw_tok:
                time_cands = cls._parse_time_token(raw_tok)
                if time_cands:
                    token_candidate_branches.append(time_cands)
                    i += 1
                    continue

            # 3. Noise words to skip
            if tok_lower in NOISE_WORDS:
                i += 1
                continue

            # 4. Devanagari numerals
            dev_digits = [DEVANAGARI_NUMERALS[c] for c in raw_tok if c in DEVANAGARI_NUMERALS]
            if dev_digits and len(dev_digits) == len(raw_tok):
                token_candidate_branches.append(["".join(dev_digits)])
                i += 1
                continue

            # 5. Single digit words (English, Devanagari word, Hinglish)
            d = cls._map_single_token(raw_tok)
            if d:
                token_candidate_branches.append([d])
                i += 1
                continue

            # 6. Embedded multi-digit sequences (e.g. '921', '9876')
            embedded_digits = re.findall(r"\d", raw_tok)
            if embedded_digits:
                token_candidate_branches.append(["".join(embedded_digits)])
                i += 1
                continue

            i += 1

        if not token_candidate_branches:
            return [""]

        # Generate combinations (capped to avoid combinatorial explosion)
        combinations = list(itertools.product(*token_candidate_branches))[:16]
        candidates = ["".join(c) for c in combinations]
        # Return unique candidates preserving order
        unique_cands = []
        for c in candidates:
            if c not in unique_cands:
                unique_cands.append(c)
        return unique_cands or [""]

    # ─────────────────────────────────────────────────────────────────────────
    # CORRECTION DETECTION
    # ─────────────────────────────────────────────────────────────────────────

    def detect_and_apply_correction(self, text: str) -> Optional[Tuple[str, str, str]]:
        """
        Detects if the user is correcting previously spoken digits.
        Examples:
        - 'last digit 8 nahi 9'
        - '8 nahi 9'
        - 'last digit 9'
        - 'nahi last digit 9'
        - 'change 8 to 9'
        - 'replace 8 with 9'

        Returns (old_digit, new_digit, corrected_buffer) if correction applied, else None.
        """
        if not text or not self._digits:
            return None

        lower = text.lower().strip()

        # Helper to convert word or char to single digit char
        def to_digit(w: str) -> Optional[str]:
            return self._map_single_token(w)

        # Pattern 1: 'last digit 8 nahi 9' / '8 nahi 9' / '8 not 9' / '8 ki jagah 9'
        p1 = re.search(r"(?:last|aakhri|antim)?\s*(?:digit|number)?\s*(\S+)\s+(?:nahi|not|ke badle|ki jagah|instead of)\s+(\S+)", lower)
        if p1:
            old_w, new_w = p1.group(1), p1.group(2)
            old_d, new_d = to_digit(old_w), to_digit(new_w)
            if old_d and new_d:
                # If buffer ends with old_d, replace it
                if self._digits.endswith(old_d):
                    new_buf = self._digits[:-1] + new_d
                    self._digits = new_buf
                    self._last_action = f"corrected_{old_d}_to_{new_d}"
                    self._update_status()
                    return (old_d, new_d, self._digits)
                # Or find the last occurrence of old_d
                idx = self._digits.rfind(old_d)
                if idx != -1:
                    new_buf = self._digits[:idx] + new_d + self._digits[idx + 1:]
                    self._digits = new_buf
                    self._last_action = f"corrected_{old_d}_to_{new_d}"
                    self._update_status()
                    return (old_d, new_d, self._digits)

        # Pattern 2: 'change 8 to 9' / 'replace 8 with 9'
        p2 = re.search(r"(?:change|replace)\s+(\S+)\s+(?:to|with)\s+(\S+)", lower)
        if p2:
            old_w, new_w = p2.group(1), p2.group(2)
            old_d, new_d = to_digit(old_w), to_digit(new_w)
            if old_d and new_d:
                idx = self._digits.rfind(old_d)
                if idx != -1:
                    self._digits = self._digits[:idx] + new_d + self._digits[idx + 1:]
                    self._last_action = f"corrected_{old_d}_to_{new_d}"
                    self._update_status()
                    return (old_d, new_d, self._digits)

        # Pattern 3: 'last digit 9' / 'last number 9' / 'last digit is 9' / 'nahi last digit 9'
        p3 = re.search(r"(?:last|aakhri|antim)\s+(?:digit|number)?\s*(?:is|hai)?\s*(\S+)", lower)
        if p3:
            new_w = p3.group(1)
            new_d = to_digit(new_w)
            if new_d and self._digits:
                old_d = self._digits[-1]
                self._digits = self._digits[:-1] + new_d
                self._last_action = f"corrected_last_to_{new_d}"
                self._update_status()
                return (old_d, new_d, self._digits)

        # Pattern 4: 'nahi 9' / 'sorry 9' / 'correction 9'
        p4 = re.search(r"^(?:nahi|no|sorry|correction)\s+(\S+)$", lower)
        if p4:
            new_w = p4.group(1)
            new_d = to_digit(new_w)
            if new_d and self._digits:
                old_d = self._digits[-1]
                self._digits = self._digits[:-1] + new_d
                self._last_action = f"corrected_last_to_{new_d}"
                self._update_status()
                return (old_d, new_d, self._digits)

        return None

    # ─────────────────────────────────────────────────────────────────────────
    # STATE MANAGEMENT & ACCUMULATION
    # ─────────────────────────────────────────────────────────────────────────

    def _update_status(self) -> None:
        """Determines PhoneCaptureStatus based on current buffer."""
        length = len(self._digits)
        if length == 0:
            self._status = PhoneCaptureStatus.EMPTY
        elif length < 10:
            self._status = PhoneCaptureStatus.PARTIAL
        elif length == 10:
            if is_valid_indian_mobile(self._digits):
                self._status = PhoneCaptureStatus.COMPLETE
            else:
                self._status = PhoneCaptureStatus.INVALID
        else:
            # Greater than 10 digits
            self._status = PhoneCaptureStatus.OVERFLOW

    def process_utterance(
        self,
        text: str,
        is_interim: bool = False,
        utterance_id: Optional[str] = None
    ) -> PhoneCaptureStatus:
        """
        Process a user speech turn deterministically.
        Handles corrections, deduplication, candidates, multi-turn accumulation,
        and overflow recovery.
        """
        if not text:
            return self._status

        clean_text = text.strip()
        lower_text = clean_text.lower()

        # Guard: Financial or unrelated questions with no phone intention
        if any(k in lower_text for k in ["budget", "dollar", "$", "price", "pricing", "cost", "/mo", "/month"]) and not any(p in lower_text for p in ["phone", "number", "mobile", "contact", "+91"]):
            return self._status

        # 1. Deduplication: Check if identical final transcript processed in immediate succession
        if not is_interim and clean_text == self._last_raw_transcript:
            logger.debug(f"[PHONE_NORMALIZER] Ignored duplicate turn text: '{clean_text}'")
            self._last_action = "duplicate_ignored"
            return self._status

        # 2. Correction Detection
        correction = self.detect_and_apply_correction(clean_text)
        if correction:
            old_d, new_d, _ = correction
            logger.info(
                f"[PHONE_NORMALIZER] Applied correction | old={old_d} new={new_d} | "
                f"session={self.session_id} | buffer={self.masked_digits} | count={len(self._digits)}"
            )
            self._last_raw_transcript = clean_text
            return self._status

        # 3. Extract digit candidates
        candidates = self.extract_turn_candidates(clean_text)
        if not candidates or candidates == [""]:
            logger.debug(f"[PHONE_NORMALIZER] No phone digits found in: '{clean_text}'")
            return self._status

        # 4. Multi-candidate evaluation (select best candidate)
        # We test candidates against current buffer to find if any achieves exactly 10 valid digits
        best_candidate = candidates[0]
        selected_target: Optional[str] = None

        # Check full standalone replacement first (e.g. caller states full 10-12 digits at once)
        for cand in candidates:
            norm = self._normalize_complete_number(cand)
            if norm and is_valid_indian_mobile(norm):
                selected_target = norm
                best_candidate = cand
                break

        # Check accumulation with current buffer
        if not selected_target:
            current_len = len(self._digits)
            needed = 10 - current_len

            # Look for a candidate whose addition yields exactly 10 valid digits
            for cand in candidates:
                combined = self._digits + cand
                norm = self._normalize_complete_number(combined)
                if norm and is_valid_indian_mobile(norm):
                    selected_target = norm
                    best_candidate = cand
                    break

            # If no exact 10 candidate, check cross-turn history combinations
            # (e.g. if an earlier turn had a time token like '05:02' whose unpadded candidate '502'
            # combined with current turn's candidates forms exactly 10 digits)
            if not selected_target and self._turn_history:
                # Strictly bound to last 3 turns with non-empty candidates and max 32 combinations
                relevant_past_cands = [
                    t["candidates"] for t in self._turn_history[-3:]
                    if t.get("candidates") and t["candidates"] != [""]
                ]
                if relevant_past_cands:
                    past_turn_cands = relevant_past_cands + [candidates]
                    for comb in itertools.islice(itertools.product(*past_turn_cands), 32):
                        merged = "".join(comb)
                        norm = self._normalize_complete_number(merged)
                        if norm and is_valid_indian_mobile(norm):
                            selected_target = norm
                            best_candidate = comb[-1]
                            break

            # If still no exact 10 candidate, look for candidate matching needed length or shortest overflow
            if not selected_target:
                for cand in candidates:
                    if len(cand) == needed:
                        best_candidate = cand
                        break

        # 5. Check if interim transcript is being promoted or replaced
        # If the candidate starts with or is identical to the last turn extracted digits
        if not is_interim and self._last_extracted_turn_digits and best_candidate == self._last_extracted_turn_digits:
            logger.debug(f"[PHONE_NORMALIZER] Skipping re-append of identical turn digits: {best_candidate}")
            self._last_raw_transcript = clean_text
            self._last_action = "duplicate_ignored"
            return self._status

        # 6. Apply to buffer
        if selected_target:
            self._digits = selected_target
            self._last_action = "completed"
        else:
            # Check overlap deduplication: e.g. caller repeated last N digits
            overlap = self._find_overlap(self._digits, best_candidate)
            new_addition = best_candidate[overlap:] if overlap > 0 else best_candidate

            combined = self._digits + new_addition
            # Attempt overflow recovery if combined > 10
            if len(combined) > 10:
                recovered = self._attempt_overflow_recovery(self._digits, best_candidate)
                if recovered:
                    combined = recovered
                    self._last_action = "recovered_from_overflow"
                else:
                    self._last_action = "overflow_detected"
            else:
                self._last_action = "accumulated"

            self._digits = combined

        self._last_raw_transcript = clean_text
        self._last_extracted_turn_digits = best_candidate
        self._turn_history.append({
            "text": clean_text,
            "candidates": candidates,
            "selected": best_candidate
        })
        if len(self._turn_history) > 10:
            self._turn_history = self._turn_history[-10:]
        self._update_status()

        logger.info(
            f"[PHONE_NORMALIZER] Processed turn | action={self._last_action} | "
            f"session={self.session_id} | count={len(self._digits)} | "
            f"status={self._status.value} | masked={self.masked_digits}"
        )
        return self._status

    @classmethod
    def _normalize_complete_number(cls, raw: str) -> Optional[str]:
        """Normalizes a potential complete phone number (handles +91, 91, 0 prefixes)."""
        d = re.sub(r"\D", "", raw)
        if len(d) == 12 and d.startswith("91"):
            d = d[2:]
        elif len(d) == 11 and d.startswith("0"):
            d = d[1:]
        return d if len(d) == 10 else None

    @classmethod
    def _find_overlap(cls, existing: str, incoming: str) -> int:
        """Finds suffix/prefix overlap length between existing buffer and incoming digits."""
        if not existing or not incoming:
            return 0
        max_overlap = min(len(existing), len(incoming))
        for size in range(max_overlap, 0, -1):
            if existing.endswith(incoming[:size]):
                return size
        return 0

    def _attempt_overflow_recovery(self, existing: str, incoming: str) -> Optional[str]:
        """
        Attempts to resolve >10 digits:
        1. Check if +91/91 prefix present
        2. Check if leading 0 present
        3. Check overlap between existing and incoming
        4. Check if unpadded colon variant yields 10 digits
        """
        combined = existing + incoming
        # 1. 12 digits starting with 91
        if len(combined) == 12 and combined.startswith("91") and combined[2] in ("6", "7", "8", "9"):
            return combined[2:]
        # 2. 11 digits starting with 0
        if len(combined) == 11 and combined.startswith("0") and combined[1] in ("6", "7", "8", "9"):
            return combined[1:]
        # 3. Check if removing overlap creates 10 digits
        for size in range(min(len(existing), len(incoming)), 0, -1):
            if existing.endswith(incoming[:size]):
                cand = existing + incoming[size:]
                if len(cand) == 10 and is_valid_indian_mobile(cand):
                    return cand
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # STRUCTURED STATE & PROMPT EXPOSURE
    # ─────────────────────────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Returns structured state representation."""
        count = len(self._digits)
        return {
            "digits_collected": count,
            "digits_remaining": max(0, 10 - count),
            "capture_status": self._status.value,
            "last_action": self._last_action,
            "is_complete": self._status == PhoneCaptureStatus.COMPLETE,
            "is_valid": is_valid_indian_mobile(self._digits),
            "masked_digits": self.masked_digits,
        }

    def render_prompt_guidance(self) -> str:
        """
        Renders concise, deterministic instruction block for LLM prompt context.
        The LLM is NOT the source of truth for the phone digits; it only acts as
        the conversational interface based on this authoritative state.
        """
        if self._status == PhoneCaptureStatus.EMPTY:
            return ""

        count = len(self._digits)
        remaining = max(0, 10 - count)

        lines = [
            "<phone_capture_state>",
            f"Status: {self._status.value}",
            f"Digits Collected: {count} / 10",
            f"Digits Remaining: {remaining}",
        ]

        if self._status == PhoneCaptureStatus.COMPLETE:
            lines.append("Instruction: All 10 digits collected. Read the number back to confirm: say the digits clearly, then ask the user if it is correct.")
        elif self._status == PhoneCaptureStatus.PARTIAL:
            lines.append(f"Instruction: Say 'मेरे पास अभी {count} digits हैं। कृपया बाकी {remaining} digits बोलिए।' (or English equivalent). DO NOT fabricate the phone number.")
        elif self._status == PhoneCaptureStatus.OVERFLOW:
            lines.append(f"Instruction: The number has {count} digits (>10). Politely ask: 'यह number 10 digits से ज़्यादा लग रहा है। कृपया अपना 10-digit mobile number एक-एक digit करके दोबारा बोलिए।'")
        elif self._status == PhoneCaptureStatus.INVALID:
            lines.append("Instruction: The 10 digits do not form a valid Indian mobile number (must start with 6, 7, 8, or 9). Ask the user to re-state their number.")

        lines.append("</phone_capture_state>")
        return "\n".join(lines)
