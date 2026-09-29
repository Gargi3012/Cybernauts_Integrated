"""
TurnGuard — Stale-response cancellation and turn-id management.

Problem: When the user speaks multiple times in rapid succession, multiple
LLM requests can be in-flight simultaneously. If an older LLM response
finishes *after* a newer user turn has started, its audio would play on
top of the new conversation turn, producing confusing overlapping speech.

Solution: A monotonically-incrementing `turn_id` is stamped on every
LLMContextFrame.  If a LLMFullResponseStartFrame arrives for a turn_id
that is older than the current turn, the entire response (all TextFrames
and downstream audio) is suppressed until the next valid LLMFullResponseStartFrame.

Architecture notes:
  - Placed in pipeline between user_agg and LLM (upstream side).
  - Also placed between LLM output and TTS (downstream side) via the same
    shared `_current_turn` counter, inspected by a companion filter.
  - Uses shared_state so CallTerminationProcessor can also read turn state.
"""

import asyncio
from loguru import logger
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.frames.frames import (
    Frame,
    LLMContextFrame,
    LLMRunFrame,
    LLMFullResponseStartFrame,
    LLMFullResponseEndFrame,
    TextFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    UserStartedSpeakingFrame,
)


class TurnGuardProcessor(FrameProcessor):
    """
    Injects a turn_id into every LLMContextFrame and discards stale
    LLM responses (TextFrame / TTSStartedFrame / TTSStoppedFrame chains)
    that belong to a superseded turn.

    Place this processor BEFORE the LLM in the pipeline.
    A companion TurnGuardFilter (same shared state) sits AFTER the LLM.
    """

    def __init__(self, shared_state: dict = None, **kwargs):
        super().__init__(**kwargs)
        self.shared_state = shared_state if shared_state is not None else {}
        # Start at 0 — incremented on every new user context frame
        self.shared_state.setdefault("current_turn_id", 0)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, (LLMContextFrame, LLMRunFrame)):
            # New user turn — bump the counter
            self.shared_state["current_turn_id"] += 1
            turn_id = self.shared_state["current_turn_id"]
            # Stamp the frame so downstream filter knows which turn this is
            frame._turn_id = turn_id  # type: ignore[attr-defined]
            logger.info(
                f"[TURN] New turn_id={turn_id} stamped on {type(frame).__name__}"
            )

        elif isinstance(frame, UserStartedSpeakingFrame):
            # User started speaking — the current in-flight LLM response (if any)
            # is now stale once a new transcript arrives.  We don't bump turn_id
            # here yet because we wait for the TranscriptionFrame / LLMContextFrame,
            # but we record that new speech is starting.
            logger.debug("[TURN] UserStartedSpeaking — next LLMContextFrame will bump turn_id")

        await self.push_frame(frame, direction)


class TurnGuardFilter(FrameProcessor):
    """
    Sits AFTER the LLM (between LLM and TTS).  Suppresses TextFrames and
    TTS frames that belong to a stale turn_id.

    When a LLMFullResponseStartFrame arrives:
      - Read its _turn_id attribute (stamped by TurnGuardProcessor).
      - Compare against shared_state["current_turn_id"].
      - If older → mark _suppressing = True and discard until LLMFullResponseEndFrame.
      - If current → pass through normally.

    This prevents old queued audio from playing after new user speech.
    """

    def __init__(self, shared_state: dict = None, **kwargs):
        super().__init__(**kwargs)
        self.shared_state = shared_state if shared_state is not None else {}
        self._suppressing = False
        self._suppressed_turn_id = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        # --- Check if ENDING_CALL — block new LLM responses ---
        if self.shared_state.get("ending_call"):
            if isinstance(frame, (LLMFullResponseStartFrame, TextFrame,
                                  TTSStartedFrame, TTSStoppedFrame,
                                  LLMFullResponseEndFrame)):
                logger.info(
                    f"[TURN] ENDING_CALL: suppressing {type(frame).__name__}"
                )
                # Still push LLMFullResponseEndFrame so aggregators don't get stuck
                if isinstance(frame, LLMFullResponseEndFrame):
                    await self.push_frame(frame, direction)
                return
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, LLMFullResponseStartFrame):
            frame_turn_id = getattr(frame, "_turn_id", None)
            current_turn_id = self.shared_state.get("current_turn_id", 0)

            if frame_turn_id is not None and frame_turn_id < current_turn_id:
                self._suppressing = True
                self._suppressed_turn_id = frame_turn_id
                logger.warning(
                    f"[TURN] STALE response turn_id={frame_turn_id} < "
                    f"current_turn_id={current_turn_id} — suppressing"
                )
                self.shared_state["stale_responses_discarded"] = (
                    self.shared_state.get("stale_responses_discarded", 0) + 1
                )
                return  # swallow the StartFrame entirely
            else:
                self._suppressing = False
                self._suppressed_turn_id = None
                logger.debug(
                    f"[TURN] Valid response turn_id={frame_turn_id} passing through"
                )

        elif isinstance(frame, LLMFullResponseEndFrame) and self._suppressing:
            logger.warning(
                f"[TURN] STALE_RESPONSE_DISCARDED | turn_id={self._suppressed_turn_id}"
            )
            logger.warning(
                f"[FILLER] FILLER_DISCARDED_AS_STALE | turn_id={self._suppressed_turn_id}"
            )
            self._suppressing = False
            self._suppressed_turn_id = None
            await self.push_frame(frame, direction)  # End frame must pass so aggregator doesn't stall
            return

        elif self._suppressing and isinstance(frame, (TextFrame, TTSStartedFrame, TTSStoppedFrame)):
            if getattr(frame, "is_filler", False):
                logger.warning(
                    f"[FILLER] FILLER_DISCARDED_AS_STALE | turn_id={self._suppressed_turn_id}"
                )
            # Drop stale audio/text frames
            return

        await self.push_frame(frame, direction)
