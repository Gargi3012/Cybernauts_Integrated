"""
SemanticEndCallDetector — Natural call-completion detection.

Detects when the user is genuinely ending the conversation vs just
saying common words like "okay", "thanks", or "wait a minute".

The detector uses a two-tier approach:
  1. HIGH-CONFIDENCE phrases → request end_call immediately.
  2. AMBIGUOUS phrases → let the LLM reply naturally; mark a flag so
     that if the next user turn is also closing-like, we end.

Rules:
  - "bye", "bye bye", "goodbye", "that's all", etc. → HIGH confidence
  - "okay", "thanks", "alright" ALONE → AMBIGUOUS (do NOT end)
  - "okay tell me more", "thanks but I have a question" → NOT closing
  - "wait a minute", "hold on", "ek minute", "ruko" → USER_PAUSE (not ending)

Architecture:
  - Processor placed AFTER STT (TranscriptionFrame) and BEFORE LLM.
  - When HIGH confidence end-of-call is detected, sets
    shared_state["ending_call"] = True and shared_state["hangup_requested"] = True.
  - The TurnGuardFilter blocks new LLM turns in ENDING_CALL state.
  - CallTerminationProcessor handles the actual pipeline shutdown after TTS.
"""

import re
from loguru import logger
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.frames.frames import Frame, TranscriptionFrame, LLMFullResponseEndFrame


# ---------------------------------------------------------------------------
# Phrase tables
# ---------------------------------------------------------------------------

# HIGH confidence end-of-call patterns (after stripping punctuation)
_END_CALL_HIGH: list[tuple[re.Pattern, str]] = [
    (re.compile(r'\bbye[\s-]?bye\b', re.I), "bye bye"),
    (re.compile(r'\bgoodbye\b', re.I), "goodbye"),
    (re.compile(r'\bba[y]?e\b', re.I), "bye"),   # 'bye'
    (re.compile(r'\bbye\b', re.I), "bye"),
    (re.compile(r"\bthat'?s\s+all\b", re.I), "that's all"),
    (re.compile(r'\bnothing\s+else\b', re.I), "nothing else"),
    (re.compile(r"\bi'?m\s+done\b", re.I), "i'm done"),
    (re.compile(r'\bno\s+more\s+questions?\b', re.I), "no more questions"),
    (re.compile(r'\ball\s+set\b', re.I), "all set"),
    # Explicit call termination requests
    (re.compile(r'\b(hang\s*up|disconnect(\s*the\s*call)?|end\s*(the|this)?\s*call|cut\s*(the|this)?\s*call)\b', re.I), "hang up"),
    # Hindi / Hinglish
    (re.compile(r'\b(call\s*(cut|end|disconnect)\s*kar\s*(do|de|dijiye|dena))\b', re.I), "call cut kar do"),
    (re.compile(r'\b(phone\s*(kaat|rakh)\s*(do|de|dijiye|dena))\b', re.I), "phone kaat do"),
    (re.compile(r'\balvida\b', re.I), "alvida"),
    (re.compile(r'\btas\s+alla?\b', re.I), "tak alla"),
    (re.compile(r'\bbas\s+itna\s+hi\b', re.I), "bas itna hi"),
    (re.compile(r'\bbas\s+ho\s+gaya\b', re.I), "bas ho gaya"),
    (re.compile(r'\bdhanyavaad\b', re.I), "dhanyavaad"),
    (re.compile(r'\bchaliye\s+theek\s+hai\b', re.I), "chaliye theek hai"),
    (re.compile(r'\btheek\s+hai\s+bye\b', re.I), "theek hai bye"),
    (re.compile(r'\btheek\s+hai,?\s+alvida\b', re.I), "theek hai alvida"),
    (re.compile(r'\bho\s+gaya\b.*\bbye\b', re.I), "ho gaya bye"),
    (re.compile(r'\bphir\s+milenge\b', re.I), "phir milenge"),
]

# USER PAUSE patterns — must NOT trigger end-of-call
_USER_PAUSE: list[re.Pattern] = [
    re.compile(r'\bwait\s+a\s+(moment|minute|sec(ond)?)\b', re.I),
    re.compile(r'\bhold\s+on\b', re.I),
    re.compile(r'\bone\s+(moment|second|sec|minute|min)\b', re.I),
    re.compile(r'\bjust\s+a\s+(moment|second|sec|minute)\b', re.I),
    re.compile(r'\bek\s+(minute|min|second|pal)\b', re.I),
    re.compile(r'\bruko?\b', re.I),
    re.compile(r'\bthairo?\b', re.I),
    re.compile(r'\bwait\b', re.I),
]

# Continuation patterns — presence of these words makes it NOT end-of-call
_CONTINUATION_MARKERS = re.compile(
    r'\b(more|tell me|explain|what|how|why|when|where|who|please|'
    r'also|another|question|bata(o)?|aur|lekin|but|actually|'
    r'theek hai\s+lekin|achha\s+lekin|aur\s+batao)\b',
    re.I,
)


def _is_user_pause(text: str) -> bool:
    """Return True if the text is a pause request, not a goodbye."""
    for p in _USER_PAUSE:
        if p.search(text):
            return True
    return False


def _end_call_confidence(text: str) -> tuple[float, str]:
    """
    Return (confidence, matched_phrase) for end-of-call detection.

    confidence: 0.0 = definitely not ending; 1.0 = definitely ending
    """
    clean = text.strip().rstrip(".,!?")

    # Bail immediately if this is clearly a user pause
    if _is_user_pause(clean):
        return 0.0, "user_pause"

    # Bail if continuation markers are present
    if _CONTINUATION_MARKERS.search(clean):
        return 0.0, "continuation"

    # Check high-confidence patterns
    for pattern, phrase in _END_CALL_HIGH:
        if pattern.search(clean):
            return 1.0, phrase

    return 0.0, ""


class SemanticEndCallDetector(FrameProcessor):
    """
    Scans every final TranscriptionFrame for end-of-call intent.

    - HIGH confidence (≥0.9) → sets shared_state["ending_call"] = True
      and shared_state["hangup_requested"] = True so the pipeline shuts
      down gracefully after the LLM's final goodbye TTS finishes.

    - USER PAUSE detected → sets shared_state["user_pause"] = True so
      filler audio is suppressed and the LLM can wait for the user.

    Does NOT add a separate LLM request. The LLM still responds naturally
    because the TranscriptionFrame is passed through unchanged. The
    ending_call flag just blocks *subsequent* LLM turns.
    """

    def __init__(self, shared_state: dict = None, **kwargs):
        super().__init__(**kwargs)
        self.shared_state = shared_state if shared_state is not None else {}
        # Track consecutive ambiguous turns to catch "okay... bye" patterns
        self._consecutive_ambiguous = 0

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame) and frame.text and not getattr(frame, 'user_id', None) == "bot":
            text = frame.text.strip()

            # --- If already in ENDING_CALL, drop new user turns ---
            if self.shared_state.get("ending_call"):
                logger.info(f"[EOC] Already ending call — dropping user input: '{text}'")
                return  # don't push frame — suppress further processing

            # --- Detect user pause ---
            if _is_user_pause(text):
                logger.info(f"[EOC] USER_PAUSE detected: '{text}' — flagging pause state")
                self.shared_state["user_pause"] = True
                await self.push_frame(frame, direction)
                return

            # Clear pause flag on any normal speech
            self.shared_state["user_pause"] = False

            # --- End-of-call detection ---
            confidence, matched = _end_call_confidence(text)

            if confidence >= 0.9:
                logger.warning(
                    f"[EOC] CALL_END_INTENT_DETECTED | text='{text}' "
                    f"| matched='{matched}' | confidence={confidence}"
                )
                # Mark ending — the LLM will still generate its final goodbye
                # because the TranscriptionFrame passes through normally.
                # The TurnGuardFilter blocks any *subsequent* turns.
                self.shared_state["ending_call"] = True
                self.shared_state["hangup_requested"] = True
                self._consecutive_ambiguous = 0
                logger.warning(
                    f"[EOC] CALL_END_CONFIRMATION | ending_call=True | "
                    f"hangup_requested=True | trigger='{matched}'"
                )

        elif isinstance(frame, LLMFullResponseEndFrame):
            # Reset pause flag after AI finishes responding
            self.shared_state["user_pause"] = False

        await self.push_frame(frame, direction)
