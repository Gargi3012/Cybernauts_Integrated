"""phone_digit_normalizer.py — Deterministic Phone Digit Normalizer, Persistent Buffer, and Validator.
from enum import Enum
import itertools
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from loguru import logger


class PhoneCaptureStatus(str, Enum):
    EMPTY = "empty"
    COLLECTING = "collecting"
    PARTIAL = "partial"
    AMBIGUOUS = "ambiguous"
    COMPLETE = "complete"
    OVERFLOW = "overflow"
    INVALID = "invalid"


# Alias for compatibility with prompt specifications
PhoneCaptureState = PhoneCaptureStatus


class TokenType(str, Enum):
    DIGIT = "digit"
    MULTIPLIER = "multiplier"
    TIME_LIKE_AMBIGUOUS = "time_like_ambiguous"
    NOISE = "noise"
    CORRECTION = "correction"
    FINAL_PHRASE = "final_phrase"


@dataclass
class NormalizedToken:
    token_type: TokenType
    raw_text: str
    digit_value: str
    is_ambiguous: bool = False
    candidates: List[str] = field(default_factory=list)


@dataclass
class PhoneValidationResult:
    is_valid: bool
    status: PhoneCaptureStatus
    digits: str
    digits_collected: int
    digits_remaining: int
    has_ambiguity: bool = False
    ambiguous_count: int = 0
    message_hindi: str = ""
    message_english: str = ""
    error_reason: Optional[str] = None


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
    "batata", "hoon", "dijiye", "yeh", "raha", "contact", "call", "me", "on", "at",
    "and", "aur", "toh", "ka", "ki", "ke"
}

# Explicit final number declaration phrases
FINAL_PHRASES: List[str] = [
    "that's my number",
    "that is my number",
    "that's my final number",
    "that is my final number",
    "my final number is",
    "my number is",
    "that is all",
    "that's all",
    "बस यही मेरा नंबर है",
    "यही मेरा नंबर है",
    "बस यही नंबर है",
    "यही नंबर है",
    "mera number yahi hai",
    "yahi mera number hai",
    "yahi number hai",
    "bas itna hi hai",
]


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


def redact_text_for_diagnostics(text: str) -> str:
    """Redacts numeric sequences from text for safe diagnostic logging."""
    if not text:
        return ""
    # Replace any sequence of 2 or more digits with <REDACTED_NUMERIC>
    redacted = re.sub(r"\b\d{2,}\b", "<REDACTED_NUMERIC>", text)
    # Also redact colon sequences like 05:02, 04:01
    redacted = re.sub(r"\b\d{1,2}:\d{2}\b", "<REDACTED_NUMERIC>", redacted)
    return redacted


def is_valid_indian_mobile(digits: str) -> bool:
    """Validates if digits form an exact 10-digit Indian mobile number."""
    if len(digits) != 10 or not digits.isdigit():
        return False
    return digits[0] in ("6", "7", "8", "9")


# ─────────────────────────────────────────────────────────────────────────────
# PHONE VALIDATOR
# ─────────────────────────────────────────────────────────────────────────────

class PhoneValidator:
    """Deterministic validator and context-aware messaging for phone numbers."""

    @staticmethod
    def validate(digits: str, ambiguous_count: int = 0) -> PhoneValidationResult:
        count = len(digits)
        remaining = max(0, 10 - count)

        if ambiguous_count > 0:
            status = PhoneCaptureStatus.AMBIGUOUS
            msg_hi = f"आखिरी कुछ digits clear नहीं मिले। कृपया सिर्फ आखिरी {ambiguous_count} digits एक-एक करके बोलिए।"
            msg_en = f"The last few digits weren't completely clear. Please repeat just the last {ambiguous_count} digits one by one."
            return PhoneValidationResult(
                is_valid=False,
                status=status,
                digits=digits,
                digits_collected=count,
                digits_remaining=remaining,
                has_ambiguity=True,
                ambiguous_count=ambiguous_count,
                message_hindi=msg_hi,
                message_english=msg_en,
                error_reason="ambiguous_time_like_token",
            )

        if count == 0:
            return PhoneValidationResult(
                is_valid=False,
                status=PhoneCaptureStatus.EMPTY,
                digits="",
                digits_collected=0,
                digits_remaining=10,
                message_hindi="कृपया अपना 10-digit mobile number एक-एक करके बोलिए।",
                message_english="Please say your 10-digit mobile number one digit at a time.",
            )

        if count < 10:
            msg_hi = f"मुझे अभी {count} digits मिले हैं। बाकी {remaining} digits भी बता दीजिए।"
            msg_en = f"I have received {count} digits so far. Please tell me the remaining {remaining} digits."
            return PhoneValidationResult(
                is_valid=False,
                status=PhoneCaptureStatus.PARTIAL,
                digits=digits,
                digits_collected=count,
                digits_remaining=remaining,
                message_hindi=msg_hi,
                message_english=msg_en,
            )

        if count == 10:
            if is_valid_indian_mobile(digits):
                msg_hi = "धन्यवाद। मैंने आपका mobile number note कर लिया है।"
                msg_en = "Thank you. I have noted your mobile number."
                return PhoneValidationResult(
                    is_valid=True,
                    status=PhoneCaptureStatus.COMPLETE,
                    digits=digits,
                    digits_collected=10,
                    digits_remaining=0,
                    message_hindi=msg_hi,
                    message_english=msg_en,
                )
            else:
                msg_hi = "यह number मान्य भारतीय mobile number नहीं लग रहा है (6, 7, 8 या 9 से शुरू होना चाहिए)। कृपया दोबारा बोलिए।"
                msg_en = "This does not seem to be a valid Indian mobile number (it should start with 6, 7, 8, or 9). Please say it again."
                return PhoneValidationResult(
                    is_valid=False,
                    status=PhoneCaptureStatus.INVALID,
                    digits=digits,
                    digits_collected=10,
                    digits_remaining=0,
                    message_hindi=msg_hi,
                    message_english=msg_en,
                    error_reason="invalid_starting_digit",
                )

        # count > 10 (Overflow)
        msg_hi = f"यह number 10 digits से ज़्यादा लग रहा है ({count} digits मिले)। कृपया अपना 10-digit mobile number दोबारा बोलिए।"
        msg_en = f"That sounds like more than 10 digits ({count} digits detected). Please say your 10-digit mobile number again."
        return PhoneValidationResult(
            is_valid=False,
            status=PhoneCaptureStatus.OVERFLOW,
            digits=digits,
            digits_collected=count,
            digits_remaining=0,
            message_hindi=msg_hi,
            message_english=msg_en,
            error_reason=f"overflow_{count}_digits",
        )


# ─────────────────────────────────────────────────────────────────────────────
# PHONE DIGIT NORMALIZER (TOKEN PARSER)
# ─────────────────────────────────────────────────────────────────────────────

class PhoneDigitNormalizer:
    """
    Deterministic normalizer extracting and managing phone digits across turns.
    Trilingual (English, Hindi Roman, Devanagari numerals and words),
    handles speech multipliers ('double four' -> '44'), colon time tokens,
    spoken corrections, and explicit final phrases.
    """

    def __init__(self, session_id: str = ""):
        self.session_id: str = session_id
        self._buffer: PhoneCaptureBuffer = PhoneCaptureBuffer(session_id=session_id)

    @property
    def digits(self) -> str:
        return self._buffer.digits

    @property
    def status(self) -> PhoneCaptureStatus:
        return self._buffer.status

    @property
    def last_action(self) -> str:
        return self._buffer.last_action

    @property
    def masked_digits(self) -> str:
        return mask_phone_number(self._buffer.digits)

    def get_raw_digits(self) -> str:
        return self._buffer.digits

    def reset(self) -> None:
        self._buffer.reset()

    @classmethod
    def _map_single_token(cls, token: str) -> Optional[str]:
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
    def _parse_time_token(cls, token: str) -> Tuple[List[str], bool]:
        """
        Parses time-like colon tokens (e.g. '05:02', '04:01', '12:30').
        Returns (candidates, is_ambiguous).
        """
        m = re.match(r"^(\d{1,2}):(\d{2})$", token)
        if not m:
            return ([], False)
        hour, minute = m.group(1), m.group(2)
        full_digits = f"{hour}{minute}"
        candidates = [full_digits]
        is_ambiguous = True

        if hour.startswith("0") and len(hour) == 2:
            unpadded = f"{hour[1:]}{minute}"
            if unpadded not in candidates:
                candidates.append(unpadded)

        return (candidates, is_ambiguous)

    @classmethod
    def detect_final_phrase(cls, text: str) -> bool:
        """Detects if user explicitly signals this is their complete/final number."""
        if not text:
            return False
        clean = text.lower().strip()
        for phrase in FINAL_PHRASES:
            if phrase in clean:
                return True
        return False

    @classmethod
    def extract_tokens(cls, text: str) -> List[NormalizedToken]:
        """Extracts structured NormalizedToken objects from text."""
        if not text:
            return []

        cleaned = text.replace(",", " ").replace("-", " ").replace("—", " ").replace("/", " ")
        cleaned = re.sub(r"[.?!;]", " ", cleaned)
        tokens = cleaned.split()

        result: List[NormalizedToken] = []
        i = 0
        n = len(tokens)

        while i < n:
            raw_tok = tokens[i]
            tok_lower = raw_tok.lower()

            # 1. Multipliers: double / triple
            if tok_lower in MULTIPLIERS_2X and i + 1 < n:
                next_digit = cls._map_single_token(tokens[i + 1])
                if next_digit:
                    result.append(NormalizedToken(
                        token_type=TokenType.MULTIPLIER,
                        raw_text=f"{raw_tok} {tokens[i + 1]}",
                        digit_value=next_digit * 2,
                    ))
                    i += 2
                    continue
            if tok_lower in MULTIPLIERS_3X and i + 1 < n:
                next_digit = cls._map_single_token(tokens[i + 1])
                if next_digit:
                    result.append(NormalizedToken(
                        token_type=TokenType.MULTIPLIER,
                        raw_text=f"{raw_tok} {tokens[i + 1]}",
                        digit_value=next_digit * 3,
                    ))
                    i += 2
                    continue

            # 2. Time-like colon tokens (e.g. 05:02, 04:01)
            if ":" in raw_tok:
                cands, is_amb = cls._parse_time_token(raw_tok)
                if cands:
                    result.append(NormalizedToken(
                        token_type=TokenType.TIME_LIKE_AMBIGUOUS,
                        raw_text=raw_tok,
                        digit_value=cands[0],
                        is_ambiguous=is_amb,
                        candidates=cands,
                    ))
                    i += 1
                    continue

            # 3. Noise words
            if tok_lower in NOISE_WORDS:
                i += 1
                continue

            # 4. Devanagari numerals
            dev_digits = [DEVANAGARI_NUMERALS[c] for c in raw_tok if c in DEVANAGARI_NUMERALS]
            if dev_digits and len(dev_digits) == len(raw_tok):
                result.append(NormalizedToken(
                    token_type=TokenType.DIGIT,
                    raw_text=raw_tok,
                    digit_value="".join(dev_digits),
                ))
                i += 1
                continue

            # 5. Single digit words
            d = cls._map_single_token(raw_tok)
            if d:
                result.append(NormalizedToken(
                    token_type=TokenType.DIGIT,
                    raw_text=raw_tok,
                    digit_value=d,
                ))
                i += 1
                continue

            # 6. Embedded multi-digit sequences
            embedded_digits = re.findall(r"\d", raw_tok)
            if embedded_digits:
                result.append(NormalizedToken(
                    token_type=TokenType.DIGIT,
                    raw_text=raw_tok,
                    digit_value="".join(embedded_digits),
                ))
                i += 1
                continue

            i += 1

        return result

    @classmethod
    def extract_turn_candidates(cls, text: str) -> List[str]:
        tokens = cls.extract_tokens(text)
        if not tokens:
            return [""]

        branches: List[List[str]] = []
        for t in tokens:
            if t.candidates:
                branches.append(t.candidates)
            elif t.digit_value:
                branches.append([t.digit_value])

        if not branches:
            return [""]

        combinations = list(itertools.product(*branches))[:16]
        candidates = ["".join(c) for c in combinations]
        unique_cands = []
        for c in candidates:
            if c not in unique_cands:
                unique_cands.append(c)
        return unique_cands or [""]

    @classmethod
    def _normalize_complete_number(cls, raw: str) -> Optional[str]:
        d = re.sub(r"\D", "", raw)
        if len(d) == 12 and d.startswith("91"):
            d = d[2:]
        elif len(d) == 11 and d.startswith("0"):
            d = d[1:]
        return d if len(d) == 10 else None

    @classmethod
    def _find_overlap(cls, existing: str, incoming: str) -> int:
        if not existing or not incoming:
            return 0
        max_overlap = min(len(existing), len(incoming))
        for size in range(max_overlap, 0, -1):
            if existing.endswith(incoming[:size]):
                return size
        return 0

    def detect_and_apply_correction(self, text: str) -> Optional[Tuple[str, str, str]]:
        return self._buffer.detect_and_apply_correction(text)

    def process_utterance(
        self,
        text: str,
        is_interim: bool = False,
        utterance_id: Optional[str] = None
    ) -> PhoneCaptureStatus:
        return self._buffer.process_utterance(text, is_interim=is_interim)

    def to_dict(self) -> Dict[str, Any]:
        return self._buffer.to_dict()

    def render_prompt_guidance(self) -> str:
        return self._buffer.render_prompt_guidance()


# ─────────────────────────────────────────────────────────────────────────────
# PHONE CAPTURE BUFFER (PERSISTENT MULTI-TURN BUFFER)
# ─────────────────────────────────────────────────────────────────────────────

class PhoneCaptureBuffer:
    """
    Persistent state & multi-turn accumulator for phone number capture.
    Guarantees:
    - Never resets buffer merely because a new turn started.
    - Handles interim vs final reconciliation without double-counting.
    - Resolves time-like tokens safely without blindingly stripping colons.
    - Freezes buffer on explicit final phrases ("that's my number", "यही मेरा नंबर है").
    """

    def __init__(self, session_id: str = ""):
        self.session_id: str = session_id
        self._digits: str = ""
        self._last_raw_transcript: str = ""
        self._last_extracted_turn_digits: str = ""
        self._last_action: str = "init"
        self._turn_history: List[Dict[str, Any]] = []
        self._status: PhoneCaptureStatus = PhoneCaptureStatus.EMPTY
        self._is_frozen: bool = False
        self._ambiguous_tokens: List[Dict[str, Any]] = []

    @property
    def digits(self) -> str:
        return self._digits

    @property
    def status(self) -> PhoneCaptureStatus:
        return self._status

    @property
    def last_action(self) -> str:
        return self._last_action

    @property
    def is_frozen(self) -> bool:
        return self._is_frozen

    def reset(self) -> None:
        self._digits = ""
        self._last_raw_transcript = ""
        self._last_extracted_turn_digits = ""
        self._last_action = "reset"
        self._turn_history = []
        self._status = PhoneCaptureStatus.EMPTY
        self._is_frozen = False
        self._ambiguous_tokens = []
        logger.info(f"[PHONE_BUFFER] Reset buffer for session={self.session_id}")

    def detect_and_apply_correction(self, text: str) -> Optional[Tuple[str, str, str]]:
        if not text or not self._digits:
            return None

        lower = text.lower().strip()

        def to_digit(w: str) -> Optional[str]:
            return PhoneDigitNormalizer._map_single_token(w)

        # 1. 'last digit 8 nahi 9' / '8 nahi 9' / '8 not 9' / '8 ki jagah 9'
        p1 = re.search(r"(?:last|aakhri|antim)?\s*(?:digit|number)?\s*(\S+)\s+(?:nahi|not|ke badle|ki jagah|instead of)\s+(\S+)", lower)
        if p1:
            old_w, new_w = p1.group(1), p1.group(2)
            old_d, new_d = to_digit(old_w), to_digit(new_w)
            if old_d and new_d:
                if self._digits.endswith(old_d):
                    self._digits = self._digits[:-1] + new_d
                    self._last_action = f"corrected_{old_d}_to_{new_d}"
                    self._update_status()
                    return (old_d, new_d, self._digits)
                idx = self._digits.rfind(old_d)
                if idx != -1:
                    self._digits = self._digits[:idx] + new_d + self._digits[idx + 1:]
                    self._last_action = f"corrected_{old_d}_to_{new_d}"
                    self._update_status()
                    return (old_d, new_d, self._digits)

        # 2. 'change 8 to 9' / 'replace 8 with 9'
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

        # 3. 'last digit 9' / 'last number 9'
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

        # 4. 'nahi 9' / 'sorry 9'
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

    def _update_status(self) -> None:
        length = len(self._digits)
        if length == 0:
            self._status = PhoneCaptureStatus.EMPTY
        elif self._ambiguous_tokens and length != 10:
            self._status = PhoneCaptureStatus.AMBIGUOUS
        elif length < 10:
            self._status = PhoneCaptureStatus.PARTIAL
        elif length == 10:
            if is_valid_indian_mobile(self._digits):
                self._status = PhoneCaptureStatus.COMPLETE
            else:
                self._status = PhoneCaptureStatus.INVALID
        else:
            self._status = PhoneCaptureStatus.OVERFLOW

    def process_utterance(
        self,
        text: str,
        is_interim: bool = False,
    ) -> PhoneCaptureStatus:
        if not text:
            return self._status

        clean_text = text.strip()
        lower_text = clean_text.lower()

        # Guard: financial/unrelated queries
        if any(k in lower_text for k in ["budget", "dollar", "$", "price", "pricing", "cost", "/mo", "/month"]) and not any(p in lower_text for p in ["phone", "number", "mobile", "contact", "+91"]):
            return self._status

        # 1. Check for explicit final number phrase ("that's my number", "यही मेरा नंबर है")
        has_final_phrase = PhoneDigitNormalizer.detect_final_phrase(clean_text)
        if has_final_phrase:
            self._is_frozen = True
            self._last_action = "final_phrase_declared"
            logger.info(f"[PHONE_BUFFER] Final number declaration detected | session={self.session_id}")

        # 2. Deduplication check
        if not is_interim and clean_text == self._last_raw_transcript:
            logger.debug(f"[PHONE_BUFFER] Duplicate turn text ignored: '{clean_text}'")
            self._last_action = "duplicate_ignored"
            return self._status

        # 3. Correction detection
        correction = self.detect_and_apply_correction(clean_text)
        if correction:
            old_d, new_d, _ = correction
            logger.info(
                f"[PHONE_BUFFER] Applied correction | old={old_d} new={new_d} | "
                f"session={self.session_id} | buffer={mask_phone_number(self._digits)} | count={len(self._digits)}"
            )
            self._last_raw_transcript = clean_text
            return self._status

        # 4. Token extraction & time-like token handling
        tokens = PhoneDigitNormalizer.extract_tokens(clean_text)
        for tok in tokens:
            if tok.token_type == TokenType.TIME_LIKE_AMBIGUOUS:
                self._ambiguous_tokens.append({
                    "raw": tok.raw_text,
                    "candidates": tok.candidates,
                    "session_id": self.session_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

        candidates = PhoneDigitNormalizer.extract_turn_candidates(clean_text)
        if not candidates or candidates == [""]:
            logger.debug(f"[PHONE_BUFFER] No phone digits in: '{clean_text}'")
            return self._status

        # 5. Evaluate best candidate
        best_candidate = candidates[0]
        selected_target: Optional[str] = None

        # Check full standalone replacement first
        for cand in candidates:
            norm = PhoneDigitNormalizer._normalize_complete_number(cand)
            if norm and is_valid_indian_mobile(norm):
                selected_target = norm
                best_candidate = cand
                break

        # Check accumulation with current buffer
        if not selected_target:
            current_len = len(self._digits)
            needed = 10 - current_len

            for cand in candidates:
                combined = self._digits + cand
                norm = PhoneDigitNormalizer._normalize_complete_number(combined)
                if norm and is_valid_indian_mobile(norm):
                    selected_target = norm
                    best_candidate = cand
                    break

            # Cross-turn combination resolution (e.g. earlier unpadded candidate from 05:02)
            if not selected_target and self._turn_history:
                past_cands = [
                    t["candidates"] for t in self._turn_history[-3:]
                    if t.get("candidates") and t["candidates"] != [""]
                ]
                if past_cands:
                    all_comb_branches = past_cands + [candidates]
                    for comb in itertools.islice(itertools.product(*all_comb_branches), 32):
                        merged = "".join(comb)
                        norm = PhoneDigitNormalizer._normalize_complete_number(merged)
                        if norm and is_valid_indian_mobile(norm):
                            selected_target = norm
                            best_candidate = comb[-1]
                            break

            if not selected_target:
                for cand in candidates:
                    if len(cand) == needed:
                        best_candidate = cand
                        break

        # Interim-to-final deduplication check
        if not is_interim and self._last_extracted_turn_digits and best_candidate == self._last_extracted_turn_digits:
            logger.debug(f"[PHONE_BUFFER] Skipping re-append of identical turn digits: {best_candidate}")
            self._last_raw_transcript = clean_text
            self._last_action = "duplicate_ignored"
            return self._status

        # Apply to buffer
        if selected_target:
            self._digits = selected_target
            self._last_action = "completed"
            self._ambiguous_tokens = []  # Resolved cleanly to 10 digits
        else:
            overlap = PhoneDigitNormalizer._find_overlap(self._digits, best_candidate)
            new_addition = best_candidate[overlap:] if overlap > 0 else best_candidate

            combined = self._digits + new_addition
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
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "text": redact_text_for_diagnostics(clean_text),
            "candidates": candidates,
            "selected": best_candidate
        })
        if len(self._turn_history) > 10:
            self._turn_history = self._turn_history[-10:]

        self._update_status()

        logger.info(
            f"[PHONE_BUFFER] Processed turn | action={self._last_action} | "
            f"session={self.session_id} | count={len(self._digits)} | "
            f"status={self._status.value} | masked={mask_phone_number(self._digits)}"
        )
        return self._status

    def _attempt_overflow_recovery(self, existing: str, incoming: str) -> Optional[str]:
        combined = existing + incoming
        if len(combined) == 12 and combined.startswith("91") and combined[2] in ("6", "7", "8", "9"):
            return combined[2:]
        if len(combined) == 11 and combined.startswith("0") and combined[1] in ("6", "7", "8", "9"):
            return combined[1:]
        for size in range(min(len(existing), len(incoming)), 0, -1):
            if existing.endswith(incoming[:size]):
                cand = existing + incoming[size:]
                if len(cand) == 10 and is_valid_indian_mobile(cand):
                    return cand
        return None

    def to_dict(self) -> Dict[str, Any]:
        count = len(self._digits)
        return {
            "digits_collected": count,
            "digits_remaining": max(0, 10 - count),
            "capture_status": self._status.value,
            "last_action": self._last_action,
            "is_complete": self._status == PhoneCaptureStatus.COMPLETE,
            "is_valid": is_valid_indian_mobile(self._digits),
            "masked_digits": mask_phone_number(self._digits),
            "is_frozen": self._is_frozen,
            "has_ambiguity": len(self._ambiguous_tokens) > 0,
        }

    def render_prompt_guidance(self) -> str:
        if self._status == PhoneCaptureStatus.EMPTY:
            return ""

        count = len(self._digits)
        remaining = max(0, 10 - count)
        validation = PhoneValidator.validate(self._digits, len(self._ambiguous_tokens))

        lines = [
            "<phone_capture_state>",
            f"Status: {self._status.value}",
            f"Digits Collected: {count} / 10",
            f"Digits Remaining: {remaining}",
        ]

        if self._status == PhoneCaptureStatus.COMPLETE:
            lines.append("Instruction: All 10 digits collected. Read the number back digit by digit to confirm: say each digit spaced out, then ask if it is correct.")
        elif self._status == PhoneCaptureStatus.AMBIGUOUS:
            lines.append(f"Instruction: {validation.message_hindi} (or English: {validation.message_english})")
        elif self._status == PhoneCaptureStatus.PARTIAL:
            lines.append(f"Instruction: {validation.message_hindi} (or English: {validation.message_english}) DO NOT fabricate phone numbers.")
        elif self._status == PhoneCaptureStatus.OVERFLOW:
            lines.append(f"Instruction: {validation.message_hindi}")
        elif self._status == PhoneCaptureStatus.INVALID:
            lines.append("Instruction: The 10 digits do not form a valid Indian mobile number (must start with 6, 7, 8, or 9). Ask the user to re-state their number.")

        lines.append("</phone_capture_state>")
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# DIAGNOSTIC OBSERVABILITY LOGGER
# ─────────────────────────────────────────────────────────────────────────────

def log_deepgram_diagnostic_event(
    session_id: str,
    turn_id: int,
    transcript: str,
    is_final: bool,
    speech_final: bool,
    confidence: float = 0.0,
    words: Optional[List[Dict[str, Any]]] = None,
    model: str = "nova-2",
    language: str = "hi",
    smart_format: bool = False,
    numerals: bool = True,
    segment_type: str = "final",
    buffer_before: str = "",
    buffer_after: str = "",
    validation_status: str = "collecting",
) -> Dict[str, Any]:
    """
    Logs raw Deepgram events safely during PHONE_CAPTURE turns.
    Strictly redacts full phone digits using <REDACTED_NUMERIC> and masked digits.
    Never logs authorization headers or API keys.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    redacted_transcript = redact_text_for_diagnostics(transcript)

    sanitized_words = []
    if words:
        for w in words:
            word_str = w.get("word", "") if isinstance(w, dict) else str(w)
            sanitized_word = "<REDACTED_NUMERIC>" if any(c.isdigit() for c in word_str) else word_str
            start = w.get("start", 0.0) if isinstance(w, dict) else 0.0
            end = w.get("end", 0.0) if isinstance(w, dict) else 0.0
            sanitized_words.append({"word": sanitized_word, "start": start, "end": end})

    diag_record = {
        "timestamp": now_iso,
        "session_id": session_id,
        "turn_id": turn_id,
        "segment_type": segment_type,
        "is_final": is_final,
        "speech_final": speech_final,
        "transcript": redacted_transcript,
        "confidence": round(confidence, 3),
        "words": sanitized_words,
        "model": model,
        "language": language,
        "smart_format": smart_format,
        "numerals": numerals,
        "buffer_before": mask_phone_number(buffer_before),
        "buffer_after": mask_phone_number(buffer_after),
        "validation_status": validation_status,
    }

    logger.info(
        f"DG_FINAL | turn={turn_id} | is_final={is_final} | speech_final={speech_final} | "
        f"type={segment_type} | transcript='{redacted_transcript}' | "
        f"confidence={confidence:.2f} | buffer={mask_phone_number(buffer_after)} | "
        f"status={validation_status}"
    )
    return diag_record
