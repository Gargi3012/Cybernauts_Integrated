import time
import json
import csv
import math
import os
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Union, Dict, Any
from loguru import logger


@dataclass
class TurnLatency:
    turn_number: Union[int, str]
    vad_start: Optional[float] = None
    stt_first_transcript: Optional[float] = None
    vad_stop: Optional[float] = None
    llm_first_token: Optional[float] = None
    tts_first_text: Optional[float] = None
    llm_complete: Optional[float] = None
    tts_first_audio: Optional[float] = None

    # Precise production latency timestamps (T0 - T8)
    t0_user_speech_end: Optional[float] = None  # T0: User speech end / VAD stop
    t1_interim_transcript: Optional[float] = None  # T1: Deepgram interim transcript
    t2_final_transcript: Optional[float] = None  # T2: Deepgram final transcript
    t3_turn_finalized: Optional[float] = None  # T3: User turn finalized by strategy
    t4_llm_request_started: Optional[float] = None  # T4: LLM request dispatched downstream
    t5_llm_first_token: Optional[float] = None  # T5: LLM first token received
    t6_first_tts_text: Optional[float] = None  # T6: First text chunk delivered to TTS
    t7_first_tts_audio: Optional[float] = None  # T7: First TTS audio chunk emitted
    t8_transport_audio: Optional[float] = None  # T8: Audio frame delivered to transport output

    # High-resolution monotonic nanoseconds for micro-benchmarking
    t0_ns: Optional[int] = None
    t2_ns: Optional[int] = None
    t3_ns: Optional[int] = None
    t4_ns: Optional[int] = None
    t5_ns: Optional[int] = None
    t6_ns: Optional[int] = None
    t7_ns: Optional[int] = None
    t8_ns: Optional[int] = None

    # Correlation identifiers
    session_id: str = ""
    call_uuid: str = ""
    dispatch_id: str = ""
    generation_id: str = ""
    sequence_number: int = 0
    is_cold: bool = False

    # Turn context and phone state
    configured_timeout: Optional[float] = None
    is_phone_turn: bool = False
    phone_digits_count: int = 0
    phone_status: str = ""
    utterance_text: str = ""

    # Context Token Breakdown Instrumentation
    system_prompt_tokens: Optional[int] = None
    call_script_tokens: Optional[int] = None
    faq_tokens: Optional[int] = None
    lead_profile_tokens: Optional[int] = None
    memory_tokens: Optional[int] = None
    recent_history_tokens: Optional[int] = None
    tool_schema_tokens: Optional[int] = None
    total_input_tokens: Optional[int] = None
    is_tokens_approximate: bool = True

    def is_complete(self) -> bool:
        if self.turn_number == "Greeting":
            return (self.llm_first_token is not None and
                    self.tts_first_audio is not None)
        return (self.vad_start is not None and
                self.stt_first_transcript is not None and
                self.vad_stop is not None and
                self.llm_first_token is not None and
                self.tts_first_audio is not None and
                self.llm_complete is not None)

    @property
    def stt_finalization_latency(self) -> Optional[float]:
        t0 = self.t0_user_speech_end or self.vad_stop
        t2 = self.t2_final_transcript or self.stt_first_transcript
        return (t2 - t0) if (t0 and t2 and t2 >= t0) else None

    @property
    def turn_aggregation_latency(self) -> Optional[float]:
        t2 = self.t2_final_transcript or self.stt_first_transcript
        t3 = self.t3_turn_finalized
        return (t3 - t2) if (t2 and t3 and t3 >= t2) else None

    @property
    def llm_dispatch_latency(self) -> Optional[float]:
        t3 = self.t3_turn_finalized
        t4 = self.t4_llm_request_started
        return (t4 - t3) if (t3 and t4 and t4 >= t3) else None

    @property
    def groq_ttft(self) -> Optional[float]:
        t4 = self.t4_llm_request_started
        t5 = self.t5_llm_first_token or self.llm_first_token
        return (t5 - t4) if (t4 and t5 and t5 >= t4) else None

    @property
    def llm_ttft(self) -> Optional[float]:
        t4 = self.t4_llm_request_started
        t5 = self.t5_llm_first_token or self.llm_first_token
        return (t5 - t4) if (t4 and t5 and t5 >= t4) else None

    @property
    def clause_aggregation_latency(self) -> Optional[float]:
        t5 = self.t5_llm_first_token or self.llm_first_token
        t6 = self.t6_first_tts_text or self.tts_first_text
        return (t6 - t5) if (t5 and t6 and t6 >= t5) else None

    @property
    def cartesia_ttfb(self) -> Optional[float]:
        t6 = self.t6_first_tts_text or self.tts_first_text
        t7 = self.t7_first_tts_audio or self.tts_first_audio
        return (t7 - t6) if (t6 and t7 and t7 >= t6) else None

    @property
    def user_stop_to_first_llm_token(self) -> Optional[float]:
        t0 = self.t0_user_speech_end or self.vad_stop
        t5 = self.t5_llm_first_token or self.llm_first_token
        return (t5 - t0) if (t0 and t5 and t5 >= t0) else None

    @property
    def user_stop_to_first_tts_audio(self) -> Optional[float]:
        t0 = self.t0_user_speech_end or self.vad_stop
        t7 = self.t7_first_tts_audio or self.tts_first_audio
        if t0 and t7 and t7 >= t0:
            return t7 - t0
        elif self.t4_llm_request_started and t7 and t7 >= self.t4_llm_request_started:
            return t7 - self.t4_llm_request_started
        return None

    @property
    def application_ttfa(self) -> Optional[float]:
        """T7: First application-generated TTS audio."""
        return self.user_stop_to_first_tts_audio

    @property
    def outbound_media_ttfa(self) -> Optional[float]:
        """T8: First outbound media payload handed to WebSocket transport."""
        t0 = self.t0_user_speech_end or self.vad_stop
        t8 = self.t8_transport_audio
        if t0 and t8 and t8 >= t0:
            return t8 - t0
        elif self.t4_llm_request_started and t8 and t8 >= self.t4_llm_request_started:
            return t8 - self.t4_llm_request_started
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn_number": str(self.turn_number),
            "session_id": self.session_id,
            "call_uuid": self.call_uuid,
            "dispatch_id": self.dispatch_id,
            "generation_id": self.generation_id,
            "is_cold": self.is_cold,
            "configured_timeout_s": self.configured_timeout,
            "is_phone_turn": self.is_phone_turn,
            "phone_digits_count": self.phone_digits_count,
            "phone_status": self.phone_status,
            "stt_finalization_s": self.stt_finalization_latency,
            "turn_aggregation_s": self.turn_aggregation_latency,
            "llm_dispatch_s": self.llm_dispatch_latency,
            "llm_ttft_s": self.llm_ttft,
            "clause_aggregation_s": self.clause_aggregation_latency,
            "cartesia_ttfb_s": self.cartesia_ttfb,
            "application_ttfa_s": self.application_ttfa,
            "outbound_media_ttfa_s": self.outbound_media_ttfa,
            "total_turn_latency_s": self.user_stop_to_first_tts_audio,
            "total_input_tokens": self.total_input_tokens,
        }

    def print_benchmark(self):
        if not self.is_complete():
            return

        print("-" * 36)
        if self.turn_number == "Greeting":
            print("Greeting")
        else:
            print(f"Turn {self.turn_number}")
        print("-" * 36)

        if self.turn_number != "Greeting" and self.vad_start and self.vad_stop:
            speech_dur = self.vad_stop - self.vad_start
            stt_lat = (self.stt_first_transcript - self.vad_start) if self.stt_first_transcript else 0.0
            print(f"Speech Duration : {speech_dur:.2f} s")
            print(f"STT Latency     : {stt_lat:.2f} s")

            if self.stt_finalization_latency is not None:
                print(f"STT Finalization: {self.stt_finalization_latency:.3f} s (T2 - T0)")
            if self.turn_aggregation_latency is not None:
                print(f"Turn Aggregation: {self.turn_aggregation_latency:.3f} s (T3 - T2)")
            if self.llm_dispatch_latency is not None:
                print(f"LLM Dispatch    : {self.llm_dispatch_latency:.3f} s (T4 - T3)")
            if self.groq_ttft is not None:
                print(f"Groq/OpenAI TTFT: {self.groq_ttft:.3f} s (T5 - T4)")

            if self.total_input_tokens is not None:
                print(f"Context Tokens  : {self.total_input_tokens} (approx) [sys={self.system_prompt_tokens or 0}, script={self.call_script_tokens or 0}, faq={self.faq_tokens or 0}, lead={self.lead_profile_tokens or 0}, mem={self.memory_tokens or 0}, hist={self.recent_history_tokens or 0}, tools={self.tool_schema_tokens or 0}]")

            if self.llm_first_token:
                thinking_time = self.llm_first_token - self.vad_stop
                print(f"Thinking (TTFT) : {thinking_time:.2f} s")
            if self.tts_first_text:
                tts_text_lat = self.tts_first_text - self.vad_stop
                print(f"TTS Text Delay  : {tts_text_lat:.2f} s")
        else:
            thinking_time = None

        if self.llm_complete and self.llm_first_token:
            llm_gen = self.llm_complete - self.llm_first_token
            print(f"LLM Generation  : {llm_gen:.2f} s")

        if self.tts_first_audio and self.vad_stop:
            total_resp = self.tts_first_audio - self.vad_stop
            print(f"Total Response  : {total_resp:.2f} s")

        print("-" * 36)


@dataclass
class CallStartupLatency:
    """Measures precise call startup stages (Phase 2A)."""
    t_dispatch_initiated: Optional[float] = None
    t_plivo_request_started: Optional[float] = None
    t_plivo_request_completed: Optional[float] = None
    t_carrier_ringing_started: Optional[float] = None
    t_prospect_answered: Optional[float] = None
    t_plivo_webhook_received: Optional[float] = None
    t_websocket_connected: Optional[float] = None
    t_media_stream_usable: Optional[float] = None
    t_pipeline_init_started: Optional[float] = None
    t_pipeline_init_completed: Optional[float] = None
    t_deepgram_ready: Optional[float] = None
    t_cartesia_ready: Optional[float] = None
    t_greeting_llm_started: Optional[float] = None
    t_greeting_first_token: Optional[float] = None
    t_greeting_first_tts_text: Optional[float] = None
    t_greeting_first_tts_audio: Optional[float] = None
    t_greeting_transport_audio: Optional[float] = None

    @property
    def answer_to_first_audio_ms(self) -> Optional[float]:
        t_ans = self.t_prospect_answered or self.t_plivo_webhook_received
        t_aud = self.t_greeting_first_tts_audio or self.t_greeting_transport_audio
        if t_ans and t_aud:
            return round((t_aud - t_ans) * 1000, 1)
        return None

    def to_dict(self) -> Dict[str, Any]:
        d = {}
        if self.answer_to_first_audio_ms is not None:
            d["answer_to_first_audio_ms"] = self.answer_to_first_audio_ms
        if self.t_dispatch_initiated and self.t_plivo_webhook_received:
            d["dispatch_to_answer_webhook_ms"] = round((self.t_plivo_webhook_received - self.t_dispatch_initiated) * 1000, 1)
        if self.t_plivo_webhook_received and self.t_websocket_connected:
            d["webhook_to_websocket_connected_ms"] = round((self.t_websocket_connected - self.t_plivo_webhook_received) * 1000, 1)
        if self.t_websocket_connected and self.t_pipeline_init_completed:
            d["websocket_to_pipeline_ready_ms"] = round((self.t_pipeline_init_completed - self.t_websocket_connected) * 1000, 1)
        if self.t_pipeline_init_completed and self.t_greeting_first_token:
            d["pipeline_ready_to_greeting_first_token_ms"] = round((self.t_greeting_first_token - self.t_pipeline_init_completed) * 1000, 1)
        if self.t_greeting_first_token and self.t_greeting_first_tts_audio:
            d["greeting_first_token_to_audio_ms"] = round((self.t_greeting_first_tts_audio - self.t_greeting_first_token) * 1000, 1)
        if self.t_plivo_webhook_received and self.t_greeting_first_tts_audio:
            d["total_answer_to_first_audio_ms"] = round((self.t_greeting_first_tts_audio - self.t_plivo_webhook_received) * 1000, 1)
        return d


@dataclass
class CallTerminationLatency:
    """Measures precise call termination stages (Phase 2D)."""
    t_ending_call_detected: Optional[float] = None
    t_final_goodbye_completed: Optional[float] = None
    t_carrier_hangup_dispatched: Optional[float] = None
    t_carrier_hangup_completed: Optional[float] = None
    hangup_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        d = {"hangup_count": self.hangup_count}
        if self.t_ending_call_detected and self.t_final_goodbye_completed:
            d["goodbye_detection_to_speech_end_ms"] = round((self.t_final_goodbye_completed - self.t_ending_call_detected) * 1000, 1)
        if self.t_final_goodbye_completed and self.t_carrier_hangup_dispatched:
            d["speech_end_to_hangup_dispatch_ms"] = round((self.t_carrier_hangup_dispatched - self.t_final_goodbye_completed) * 1000, 1)
        if self.t_ending_call_detected and self.t_carrier_hangup_completed:
            d["total_goodbye_to_carrier_hangup_ms"] = round((self.t_carrier_hangup_completed - self.t_ending_call_detected) * 1000, 1)
        return d


@dataclass
class InterruptionEvent:
    turn_id: int
    timestamp: float
    decision: str  # "accepted", "rejected", "vad_noise_ignored"
    reason: str
    text: str = ""
    cancellation_duration_ms: Optional[float] = None


@dataclass
class PhoneCaptureTurnMetric:
    turn_id: int
    timestamp: float
    digit_count: int
    status: str
    active_timeout_s: float
    is_complete: bool
    source_provenance: str = "user_speech"
    is_confirmed: bool = False


class LatencyTracker:
    def __init__(
        self,
        session_id: str = "",
        call_uuid: str = "",
        dispatch_id: str = "",
    ):
        self.session_id: str = session_id
        self.call_uuid: str = call_uuid
        self.dispatch_id: str = dispatch_id
        self.sequence_number: int = 0

        self.startup: CallStartupLatency = CallStartupLatency()
        self.termination: CallTerminationLatency = CallTerminationLatency()
        self.all_turns: List[TurnLatency] = []
        self.current_turn: Optional[TurnLatency] = None
        self.turn_count: int = 0
        self.interruptions: List[InterruptionEvent] = []
        self.phone_events: List[PhoneCaptureTurnMetric] = []

        self._pending_vad_start: Optional[float] = None
        self._pending_stt_interim: Optional[float] = None
        self._pending_vad_stop: Optional[float] = None
        self._pending_vad_stop_ns: Optional[int] = None
        self._last_interruption_ts: Optional[float] = None
        self.is_warmed_up: bool = False

        # Regression thresholds (in seconds)
        self.thresholds = {
            "normal_turn_timeout_max": 0.55,
            "complete_phone_timeout_max": 0.25,
            "partial_phone_timeout_max": 2.50,
            "llm_ttft_max": 2.00,
            "clause_aggregation_max": 0.07,
            "cartesia_ttfb_max": 0.35,
            "pipeline_dispatch_max": 0.010,
        }

    @property
    def startup_metrics(self) -> CallStartupLatency:
        return self.startup

    @property
    def termination_metrics(self) -> CallTerminationLatency:
        return self.termination

    def _next_seq(self) -> int:
        self.sequence_number += 1
        return self.sequence_number

    def set_correlation_context(self, session_id: str = "", call_uuid: str = "", dispatch_id: str = ""):
        """Sets correlation IDs across tracker and sub-metrics."""
        if session_id:
            self.session_id = session_id
            self.startup.session_id = session_id
            self.termination.session_id = session_id
        if call_uuid:
            self.call_uuid = call_uuid
            self.startup.call_uuid = call_uuid
            self.termination.call_uuid = call_uuid
        if dispatch_id:
            self.dispatch_id = dispatch_id
            self.startup.dispatch_id = dispatch_id
            self.termination.dispatch_id = dispatch_id

    def mark_connection_warmed(self):
        """Explicitly flags that the client connection/pool has finished its handshake and is warm."""
        self.is_warmed_up = True

    def mark_connection_cold(self):
        """Explicitly flags that the connection requires cold-start setup (TLS/DNS)."""
        self.is_warmed_up = False

    # ── Phase 2A: Startup Hooks ──────────────────────────────────────────

    def record_dispatch_initiated(self, ts: Optional[float] = None):
        self.startup.t_dispatch_initiated = ts or time.perf_counter()

    def on_dispatch_initiated(self, ts: Optional[float] = None):
        self.record_dispatch_initiated(ts)

    def record_plivo_request(self, start_ts: float, end_ts: float):
        self.startup.t_plivo_request_started = start_ts
        self.startup.t_plivo_request_completed = end_ts

    def on_plivo_request(self, success: bool = True, duration_ms: float = 50.0):
        now = time.perf_counter()
        self.record_plivo_request(now - (duration_ms / 1000.0), now)

    def on_carrier_dialing(self, ts: Optional[float] = None):
        self.startup.t_carrier_dialing = ts or time.perf_counter()

    def on_call_answered(self, ts: Optional[float] = None):
        self.startup.t_prospect_answered = ts or time.perf_counter()

    def record_webhook_received(self, ts: Optional[float] = None):
        self.startup.t_plivo_webhook_received = ts or time.perf_counter()

    def record_websocket_connected(self, ts: Optional[float] = None):
        self.startup.t_websocket_connected = ts or time.perf_counter()

    def on_websocket_connected(self, ts: Optional[float] = None):
        self.record_websocket_connected(ts)

    def on_media_stream_usable(self, ts: Optional[float] = None):
        self.startup.t_media_stream_usable = ts or time.perf_counter()

    def record_pipeline_init(self, start_ts: float, end_ts: float):
        self.startup.t_pipeline_init_started = start_ts
        self.startup.t_pipeline_init_completed = end_ts

    def on_pipeline_ready(self, ts: Optional[float] = None):
        now = ts or time.perf_counter()
        self.record_pipeline_init(now - 0.01, now)

    def record_deepgram_ready(self, ts: Optional[float] = None):
        self.startup.t_deepgram_ready = ts or time.perf_counter()

    def record_cartesia_ready(self, ts: Optional[float] = None):
        self.startup.t_cartesia_ready = ts or time.perf_counter()

    def record_greeting_llm_start(self, ts: Optional[float] = None):
        self.startup.t_greeting_llm_started = ts or time.perf_counter()

    def on_greeting_llm_start(self, ts: Optional[float] = None):
        self.record_greeting_llm_start(ts)

    def record_greeting_first_token(self, ts: Optional[float] = None):
        self.startup.t_greeting_first_token = ts or time.perf_counter()

    def on_first_greeting_token(self, ts: Optional[float] = None):
        self.record_greeting_first_token(ts)

    def on_first_tts_text(self, ts: Optional[float] = None):
        self.startup.t_greeting_first_text_to_tts = ts or time.perf_counter()

    def record_greeting_tts_audio(self, ts: Optional[float] = None):
        self.startup.t_greeting_first_tts_audio = ts or time.perf_counter()

    def on_first_tts_audio(self, ts: Optional[float] = None):
        self.record_greeting_tts_audio(ts)

    def on_first_audio_played(self, ts: Optional[float] = None):
        self.startup.t_greeting_first_audio_played = ts or time.perf_counter()

    def on_turn_started(self, turn_id: Optional[int] = None):
        if self.current_turn:
            if self.current_turn.is_complete() or self.current_turn.tts_first_audio is not None or self.current_turn.llm_first_token is not None:
                self.all_turns.append(self.current_turn)
            self.current_turn = None
        self._pending_vad_start = None
        self._pending_stt_interim = None
        self._pending_vad_stop = None
        self._pending_vad_stop_ns = None
        now = time.perf_counter()
        self.turn_count = turn_id or (self.turn_count + 1)
        self.current_turn = TurnLatency(
            turn_number=self.turn_count,
            session_id=self.session_id,
            call_uuid=self.call_uuid,
            dispatch_id=self.dispatch_id,
            sequence_number=self._next_seq(),
            vad_start=now,
            is_cold=(self.turn_count <= 1),
        )

    # ── Phase 2B: Conversational Turn Hooks ──────────────────────────────

    def on_vad_start(self):
        """Called when UserStartedSpeakingFrame is received (from VADProcessor)."""
        now = time.perf_counter()
        self._pending_vad_start = now
        # If previous turn had completed speech (vad_stop) with transcript, or was actively generating/playing:
        if self.current_turn and (
            self.current_turn.tts_first_audio is not None
            or self.current_turn.llm_complete is not None
            or self.current_turn.llm_first_token is not None
            or (self.current_turn.vad_stop is not None and self.current_turn.t2_final_transcript is not None)
        ):
            self.all_turns.append(self.current_turn)
            self.current_turn = None
            self._pending_vad_stop = None
            self._pending_vad_stop_ns = None

    def on_stt_interim(self):
        """Called when an InterimTranscriptionFrame is received (T1)."""
        now = time.perf_counter()
        self._pending_stt_interim = now
        if self.current_turn and self.current_turn.t1_interim_transcript is None:
            self.current_turn.t1_interim_transcript = now

    def on_stt_transcript(self, text: str = ""):
        """Called when the first TranscriptionFrame with text is received (T2)."""
        now = time.perf_counter()
        now_ns = time.perf_counter_ns()
        if self.current_turn is None:
            self.turn_count += 1
            vad_start = self._pending_vad_start or now
            self._pending_vad_start = None
            # Only use _pending_vad_stop if it occurred after or with vad_start (same speech turn)
            valid_vad_stop = self._pending_vad_stop if (self._pending_vad_stop and self._pending_vad_stop >= vad_start) else None
            valid_vad_stop_ns = self._pending_vad_stop_ns if (self._pending_vad_stop and self._pending_vad_stop >= vad_start) else None
            valid_interim = self._pending_stt_interim if (self._pending_stt_interim and self._pending_stt_interim >= vad_start) else None

            self.current_turn = TurnLatency(
                turn_number=self.turn_count,
                session_id=self.session_id,
                call_uuid=self.call_uuid,
                dispatch_id=self.dispatch_id,
                sequence_number=self._next_seq(),
                vad_start=vad_start,
                vad_stop=valid_vad_stop,
                t0_user_speech_end=valid_vad_stop,
                t0_ns=valid_vad_stop_ns,
                t1_interim_transcript=valid_interim,
                utterance_text=text,
                is_cold=(not self.is_warmed_up),
            )
            self._pending_vad_stop = None
            self._pending_vad_stop_ns = None
            self._pending_stt_interim = None

        if self.current_turn:
            if self.current_turn.stt_first_transcript is None:
                self.current_turn.stt_first_transcript = now
            if self.current_turn.t2_final_transcript is None:
                self.current_turn.t2_final_transcript = now
                self.current_turn.t2_ns = now_ns
            if text and not self.current_turn.utterance_text:
                self.current_turn.utterance_text = text

    def on_vad_stop(self):
        """Called when UserStoppedSpeakingFrame is received (from VADProcessor) (T0)."""
        now = time.perf_counter()
        now_ns = time.perf_counter_ns()
        self._pending_vad_stop = now
        self._pending_vad_stop_ns = now_ns
        if self.current_turn:
            self.current_turn.vad_stop = now
            self.current_turn.t0_user_speech_end = now
            self.current_turn.t0_ns = now_ns

    def on_turn_finalized(self, timeout: Optional[float] = None, is_phone_turn: Optional[bool] = None):
        """Called when user turn is finalized by UserTurnStopStrategy (T3)."""
        now = time.perf_counter()
        now_ns = time.perf_counter_ns()
        if self.current_turn:
            if self.current_turn.t3_turn_finalized is None:
                self.current_turn.t3_turn_finalized = now
                self.current_turn.t3_ns = now_ns
            if timeout is not None:
                self.current_turn.configured_timeout = timeout
            if is_phone_turn is not None:
                self.current_turn.is_phone_turn = is_phone_turn
            elif timeout is not None and (timeout > self.thresholds["normal_turn_timeout_max"] or timeout == 0.15):
                self.current_turn.is_phone_turn = True

    def on_llm_request_started(self):
        """Called when LLMContextFrame is dispatched downstream to LLM (T4)."""
        now = time.perf_counter()
        now_ns = time.perf_counter_ns()
        if self.current_turn:
            if self.current_turn.t4_llm_request_started is None:
                self.current_turn.t4_llm_request_started = now
                self.current_turn.t4_ns = now_ns

    def on_llm_context_tokens(self, breakdown):
        """Record context token breakdown for the current turn."""
        if self.current_turn and breakdown:
            self.current_turn.system_prompt_tokens = getattr(breakdown, "system_prompt_tokens", None)
            self.current_turn.call_script_tokens = getattr(breakdown, "call_script_tokens", None)
            self.current_turn.faq_tokens = getattr(breakdown, "faq_tokens", None)
            self.current_turn.lead_profile_tokens = getattr(breakdown, "lead_profile_tokens", None)
            self.current_turn.memory_tokens = getattr(breakdown, "memory_tokens", None)
            self.current_turn.recent_history_tokens = getattr(breakdown, "recent_history_tokens", None)
            self.current_turn.tool_schema_tokens = getattr(breakdown, "tool_schema_tokens", None)
            self.current_turn.total_input_tokens = getattr(breakdown, "total_input_tokens", None)
            self.current_turn.is_tokens_approximate = getattr(breakdown, "is_approximate", True)

    def on_llm_first_token(self):
        """Called when LLMFullResponseStartFrame is received (T5)."""
        now = time.perf_counter()
        now_ns = time.perf_counter_ns()
        if self.current_turn is None:
            if self.turn_count == 0:
                self.current_turn = TurnLatency(
                    turn_number="Greeting",
                    session_id=self.session_id,
                    call_uuid=self.call_uuid,
                    dispatch_id=self.dispatch_id,
                    is_cold=(not self.is_warmed_up),
                )
            else:
                self.turn_count += 1
                self.current_turn = TurnLatency(
                    turn_number=self.turn_count,
                    session_id=self.session_id,
                    call_uuid=self.call_uuid,
                    dispatch_id=self.dispatch_id,
                    is_cold=(not self.is_warmed_up),
                )

        if self.current_turn:
            if self.current_turn.llm_first_token is None:
                self.current_turn.llm_first_token = now
            if self.current_turn.t5_llm_first_token is None:
                self.current_turn.t5_llm_first_token = now
                self.current_turn.t5_ns = now_ns

    def on_tts_text(self):
        """Called when first TextFrame is delivered downstream to TTS (T6)."""
        now = time.perf_counter()
        now_ns = time.perf_counter_ns()
        if self.current_turn:
            if self.current_turn.tts_first_text is None:
                self.current_turn.tts_first_text = now
            if self.current_turn.t6_first_tts_text is None:
                self.current_turn.t6_first_tts_text = now
                self.current_turn.t6_ns = now_ns

    def on_llm_complete(self):
        """Called when LLMFullResponseEndFrame is received."""
        if self.current_turn and self.current_turn.llm_complete is None:
            self.current_turn.llm_complete = time.perf_counter()
            self._check_turn_completion()

    def on_tts_start(self):
        """Called when TTSStartedFrame is received (T7)."""
        now = time.perf_counter()
        now_ns = time.perf_counter_ns()
        if self.current_turn:
            if self.current_turn.tts_first_audio is None:
                self.current_turn.tts_first_audio = now
            if self.current_turn.t7_first_tts_audio is None:
                self.current_turn.t7_first_tts_audio = now
                self.current_turn.t7_ns = now_ns
            self._check_turn_completion()

    def on_transport_audio(self, generation_id: Optional[str] = None):
        """Called when AudioRawFrame is handed to transport output (T8)."""
        now = time.perf_counter()
        now_ns = time.perf_counter_ns()
        if self.current_turn:
            if self.current_turn.t8_transport_audio is None:
                self.current_turn.t8_transport_audio = now
                self.current_turn.t8_ns = now_ns
            if generation_id and not self.current_turn.generation_id:
                self.current_turn.generation_id = str(generation_id)

    def _check_turn_completion(self):
        if self.current_turn and self.current_turn.is_complete():
            self.current_turn.print_benchmark()
            self.all_turns.append(self.current_turn)
            self.is_warmed_up = True
            self.current_turn = None
            self._pending_vad_start = None
            self._pending_stt_interim = None
            self._pending_vad_stop = None
            self._pending_vad_stop_ns = None

    # ── Phase 2C: Phone Capture Hooks ────────────────────────────────────

    def on_phone_event(
        self,
        digit_count: int = 0,
        status: str = "collecting",
        timeout: float = 0.45,
        provenance: str = "user_speech",
        is_complete: bool = False,
        is_confirmed: bool = False,
        **kwargs,
    ):
        turn_id = self.turn_count if self.turn_count > 0 else 1
        metric = PhoneCaptureTurnMetric(
            turn_id=turn_id,
            timestamp=time.perf_counter(),
            digit_count=digit_count,
            source_provenance=provenance,
            status="confirmed" if is_confirmed else ("complete" if is_complete else status),
            active_timeout_s=timeout,
            is_complete=(is_complete or status == "complete" or digit_count == 10),
            is_confirmed=is_confirmed,
        )
        self.phone_events.append(metric)
        if self.current_turn:
            self.current_turn.is_phone_turn = True
            self.current_turn.phone_digits_count = digit_count
            self.current_turn.phone_status = metric.status
            self.current_turn.configured_timeout = timeout

    # ── Phase 2D: Interruption & Termination Hooks ────────────────────────

    def on_interruption_event(
        self,
        decision: str = "accepted",
        reason: str = "",
        text: str = "",
        turn_id: Optional[int] = None,
        accepted: Optional[bool] = None,
        cancellation_duration_ms: Optional[float] = None,
        **kwargs,
    ):
        now = time.perf_counter()
        if accepted is not None:
            decision = "accepted" if accepted else "rejected"
        cancellation_ms = cancellation_duration_ms
        if cancellation_ms is None and decision == "accepted" and self._last_interruption_ts:
            cancellation_ms = (now - self._last_interruption_ts) * 1000
        self._last_interruption_ts = now if decision == "accepted" else None

        t_id = turn_id or (self.turn_count if self.turn_count > 0 else 1)
        event = InterruptionEvent(
            turn_id=t_id,
            timestamp=now,
            decision=decision,
            reason=reason,
            text=text,
            cancellation_duration_ms=cancellation_ms,
        )
        self.interruptions.append(event)

    def record_ending_call_detected(self, ts: Optional[float] = None):
        self.termination.t_ending_call_detected = ts or time.perf_counter()

    def on_goodbye_detected(self, ts: Optional[float] = None):
        self.record_ending_call_detected(ts)

    def record_final_goodbye_completed(self, ts: Optional[float] = None):
        self.termination.t_final_goodbye_completed = ts or time.perf_counter()

    def on_bot_stopped_speaking(self, ts: Optional[float] = None):
        self.record_final_goodbye_completed(ts)

    def record_carrier_hangup_dispatched(self, ts: Optional[float] = None):
        self.termination.t_carrier_hangup_dispatched = ts or time.perf_counter()
        self.termination.hangup_count += 1

    def on_hangup_requested(self, ts: Optional[float] = None):
        self.record_carrier_hangup_dispatched(ts)

    def record_carrier_hangup_completed(self, ts: Optional[float] = None):
        self.termination.t_carrier_hangup_completed = ts or time.perf_counter()

    def on_carrier_hangup(self, ts: Optional[float] = None):
        self.record_carrier_hangup_completed(ts)

    # ── Phase 3: Statistics, Percentiles & Regression Detection ──────────

    def compute_statistics(self) -> Dict[str, Any]:
        """Calculates p50, p90, p95, min, max, samples for all key metrics using linear interpolation."""
        def _percentile(s: List[float], p: float) -> float:
            """Documented linear interpolation percentile method (p in [0.0, 1.0]).
            
            Follows standard linear interpolation between closest ranks:
            rank = p * (N - 1)
            lower = floor(rank), upper = ceil(rank)
            value = s[lower] + (rank - lower) * (s[upper] - s[lower])
            Correctly calculates percentiles for both small (N=1, 2, 5) and large sample sizes.
            """
            if not s:
                return 0.0
            if len(s) == 1:
                return s[0]
            rank = p * (len(s) - 1)
            lower = math.floor(rank)
            upper = math.ceil(rank)
            if lower == upper:
                return s[int(rank)]
            weight = rank - lower
            return s[lower] * (1.0 - weight) + s[upper] * weight

        def _calc_stats(values: List[float]) -> Dict[str, Any]:
            if not values:
                return {"count": 0, "p50": None, "p90": None, "p95": None, "min": None, "max": None}
            s = sorted(values)
            n = len(s)
            p50 = _percentile(s, 0.50)
            p90 = _percentile(s, 0.90)
            p95 = _percentile(s, 0.95)
            return {
                "count": n,
                "p50": round(p50, 4),
                "p90": round(p90, 4),
                "p95": round(p95, 4),
                "min": round(s[0], 4),
                "max": round(s[-1], 4),
            }

        stt_finals = [t.stt_finalization_latency for t in self.all_turns if t.stt_finalization_latency is not None]
        turn_aggs = [t.turn_aggregation_latency for t in self.all_turns if t.turn_aggregation_latency is not None]
        llm_dispatches = [t.llm_dispatch_latency for t in self.all_turns if t.llm_dispatch_latency is not None]
        llm_ttfts = [t.llm_ttft for t in self.all_turns if t.llm_ttft is not None]
        clause_aggs = [t.clause_aggregation_latency for t in self.all_turns if t.clause_aggregation_latency is not None]
        cartesia_ttfbs = [t.cartesia_ttfb for t in self.all_turns if t.cartesia_ttfb is not None]
        total_latencies = [t.user_stop_to_first_tts_audio for t in self.all_turns if t.user_stop_to_first_tts_audio is not None]
        app_ttfas = [t.application_ttfa for t in self.all_turns if t.application_ttfa is not None]
        outbound_ttfas = [t.outbound_media_ttfa for t in self.all_turns if t.outbound_media_ttfa is not None]

        # Warm vs Cold classification: Lifecycle-based. Cold turns occur before connection pool warming; warm turns occur once connections are pooled.
        cold_turns = [t for t in self.all_turns if getattr(t, "is_cold", False)]
        warm_turns = [t for t in self.all_turns if not getattr(t, "is_cold", False)]
        if not cold_turns and not warm_turns and self.all_turns:
            cold_turns = [t for t in self.all_turns if t.turn_number in ("Greeting", 1, "1")]
            warm_turns = [t for t in self.all_turns if t.turn_number not in ("Greeting", 1, "1")]

        llm_ttfts_cold = [t.llm_ttft for t in cold_turns if t.llm_ttft is not None]
        llm_ttfts_warm = [t.llm_ttft for t in warm_turns if t.llm_ttft is not None]
        total_latencies_cold = [t.user_stop_to_first_tts_audio for t in cold_turns if t.user_stop_to_first_tts_audio is not None]
        total_latencies_warm = [t.user_stop_to_first_tts_audio for t in warm_turns if t.user_stop_to_first_tts_audio is not None]

        normal_turns = [t for t in self.all_turns if not t.is_phone_turn and t.turn_number != "Greeting"]
        phone_turns = [t for t in self.all_turns if t.is_phone_turn]

        normal_timeouts = [t.configured_timeout for t in normal_turns if t.configured_timeout is not None]
        phone_timeouts = [t.configured_timeout for t in phone_turns if t.configured_timeout is not None]

        return {
            "session_id": self.session_id,
            "call_uuid": self.call_uuid,
            "dispatch_id": self.dispatch_id,
            "turn_count": len(self.all_turns),
            "startup": self.startup.to_dict(),
            "termination": self.termination.to_dict(),
            "stt_finalization": _calc_stats(stt_finals),
            "turn_aggregation": _calc_stats(turn_aggs),
            "llm_dispatch": _calc_stats(llm_dispatches),
            "llm_ttft": _calc_stats(llm_ttfts),
            "llm_ttft_cold": _calc_stats(llm_ttfts_cold),
            "llm_ttft_warm": _calc_stats(llm_ttfts_warm),
            "clause_aggregation": _calc_stats(clause_aggs),
            "cartesia_ttfb": _calc_stats(cartesia_ttfbs),
            "application_ttfa": _calc_stats(app_ttfas),
            "outbound_media_ttfa": _calc_stats(outbound_ttfas),
            "total_turn_response": _calc_stats(total_latencies),
            "total_turn_response_cold": _calc_stats(total_latencies_cold),
            "total_turn_response_warm": _calc_stats(total_latencies_warm),
            "normal_timeouts": _calc_stats(normal_timeouts),
            "phone_timeouts": _calc_stats(phone_timeouts),
            "audible_pstn_response_note": "Application TTFA measured locally. True audible PSTN latency includes ~120-250ms carrier jitter buffer & network transit (requires live PSTN acceptance).",
        }

    def detect_regressions(self) -> Dict[str, Any]:
        """Detects whether any metric violates latency thresholds."""
        stats = self.compute_statistics()
        regressions = []

        # 1. Normal turn timeout check (Must be ~0.45s, not 2.2s)
        norm_to = stats["normal_timeouts"]
        if norm_to["count"] > 0 and norm_to["max"] > self.thresholds["normal_turn_timeout_max"]:
            regressions.append(
                f"NORMAL_TURN_TIMEOUT_REGRESSION: observed max {norm_to['max']}s > threshold {self.thresholds['normal_turn_timeout_max']}s"
            )

        # 2. LLM TTFT check (Must be < 2.0s)
        ttft = stats["llm_ttft"]
        if ttft["count"] > 0 and ttft["p90"] and ttft["p90"] > self.thresholds["llm_ttft_max"]:
            regressions.append(
                f"LLM_TTFT_REGRESSION: observed p90 {ttft['p90']}s > threshold {self.thresholds['llm_ttft_max']}s"
            )

        # 3. Clause aggregation delay (Must be < 70ms)
        clause = stats["clause_aggregation"]
        if clause["count"] > 0 and clause["p90"] and clause["p90"] > self.thresholds["clause_aggregation_max"]:
            regressions.append(
                f"CLAUSE_AGGREGATION_REGRESSION: observed p90 {clause['p90']}s > threshold {self.thresholds['clause_aggregation_max']}s"
            )

        # 4. Cartesia TTFB (Must be < 350ms)
        ttfb = stats["cartesia_ttfb"]
        if ttfb["count"] > 0 and ttfb["p90"] and ttfb["p90"] > self.thresholds["cartesia_ttfb_max"]:
            regressions.append(
                f"CARTESIA_TTFB_REGRESSION: observed p90 {ttfb['p90']}s > threshold {self.thresholds['cartesia_ttfb_max']}s"
            )

        # 5. Multiple carrier hangups
        if self.termination.hangup_count > 1:
            regressions.append(
                f"DUPLICATE_HANGUP_REGRESSION: {self.termination.hangup_count} carrier hangups issued"
            )

        return {
            "has_regression": len(regressions) > 0,
            "regressions": regressions,
            "summary": "PASS" if len(regressions) == 0 else f"FAIL ({len(regressions)} violations)",
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "call_uuid": self.call_uuid,
            "dispatch_id": self.dispatch_id,
            "startup": self.startup.to_dict(),
            "termination": self.termination.to_dict(),
            "turns": [t.to_dict() for t in self.all_turns],
            "phone_events": [asdict(e) for e in self.phone_events],
            "interruptions": [asdict(e) for e in self.interruptions],
            "statistics": self.compute_statistics(),
            "regression_analysis": self.detect_regressions(),
        }

    def export_json(self, filepath: Optional[str] = None) -> Dict[str, Any]:
        """Export machine-readable telemetry as JSON or return the dictionary if no filepath given."""
        data = self.to_dict()
        if filepath:
            os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            logger.info(f"[LATENCY_TELEMETRY] Exported JSON telemetry to {filepath}")
        return data

    def export_csv(self, filepath: Optional[str] = None) -> str:
        """Export turn-by-turn latency data as CSV or return the string if no filepath given."""
        import io
        turns_data = [t.to_dict() for t in self.all_turns]
        if not turns_data:
            return ""
        keys = list(turns_data[0].keys())
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=keys)
        writer.writeheader()
        writer.writerows(turns_data)
        csv_content = out.getvalue()

        if filepath:
            os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
            with open(filepath, "w", newline="", encoding="utf-8") as f:
                f.write(csv_content)
            logger.info(f"[LATENCY_TELEMETRY] Exported CSV telemetry to {filepath}")
        return csv_content

    def print_summary(self):
        """Prints the summary table of all completed turns at the end of the call."""
        turns_to_show = [
            t for t in self.all_turns
            if t.turn_number == "Greeting" or t.llm_first_token is not None or t.tts_first_audio is not None or t.llm_complete is not None
        ]
        if not turns_to_show:
            print("\nNo complete turns to summarize.")
            return

        print("\n" + "=" * 70)
        print(f" FLOWIZ PIPELINE LATENCY BENCHMARK — {self.session_id or 'Call Summary'}")
        print("=" * 70)
        print(f"{'Turn':<12}{'Timeout':<10}{'Thinking (TTFT)':<18}{'TTS (TTFB)':<14}{'Total Latency':<16}")
        print("-" * 70)

        valid_thinking = []
        valid_tts = []
        valid_total = []

        for t in turns_to_show:
            turn_name = str(t.turn_number)
            if turn_name != "Greeting":
                turn_name = f"Turn {turn_name}"

            # Calculate TTS latency safely
            tts_lat = None
            if t.tts_first_audio is not None:
                if t.tts_first_text is not None:
                    tts_lat = t.tts_first_audio - t.tts_first_text
                elif t.llm_complete is not None:
                    tts_lat = t.tts_first_audio - t.llm_complete
                elif t.llm_first_token is not None:
                    tts_lat = t.tts_first_audio - t.llm_first_token

            if tts_lat is not None:
                valid_tts.append(tts_lat)
                tts_str = f"{tts_lat:.2f} s"
            else:
                tts_str = "--"

            to_str = f"{t.configured_timeout:.2f}s" if t.configured_timeout is not None else "--"

            if t.turn_number == "Greeting":
                thinking_str = "--"
                total_str = "--"
            else:
                if t.llm_ttft is not None:
                    thinking = t.llm_ttft
                    thinking_str = f"{thinking:.2f} s"
                    valid_thinking.append(thinking)
                elif t.llm_first_token is not None and t.vad_stop is not None:
                    thinking = t.llm_first_token - t.vad_stop
                    thinking_str = f"{thinking:.2f} s"
                    valid_thinking.append(thinking)
                else:
                    thinking_str = "--"

                if t.user_stop_to_first_tts_audio is not None:
                    total = t.user_stop_to_first_tts_audio
                    total_str = f"{total:.2f} s"
                    valid_total.append(total)
                elif t.tts_first_audio is not None and t.vad_stop is not None:
                    total = t.tts_first_audio - t.vad_stop
                    total_str = f"{total:.2f} s"
                    valid_total.append(total)
                else:
                    total_str = "--"

            print(f"{turn_name:<12}{to_str:<10}{thinking_str:<18}{tts_str:<14}{total_str:<16}")

        print("-" * 70)

        avg_thinking = sum(valid_thinking) / len(valid_thinking) if valid_thinking else 0.0
        avg_tts = sum(valid_tts) / len(valid_tts) if valid_tts else 0.0
        avg_total = sum(valid_total) / len(valid_total) if valid_total else 0.0

        avg_thinking_str = f"{avg_thinking:.2f} s" if valid_thinking else "--"
        avg_tts_str = f"{avg_tts:.2f} s" if valid_tts else "--"
        avg_total_str = f"{avg_total:.2f} s" if valid_total else "--"

        print(f"{'Average':<12}{'--':<10}{avg_thinking_str:<18}{avg_tts_str:<14}{avg_total_str:<16}")
        print("=" * 70)

        # Print regression analysis status
        reg_analysis = self.detect_regressions()
        print(f"Regression Status: {reg_analysis['summary']}")
        if reg_analysis["has_regression"]:
            for r in reg_analysis["regressions"]:
                print(f"  [!] {r}")
        print("=" * 70 + "\n")
