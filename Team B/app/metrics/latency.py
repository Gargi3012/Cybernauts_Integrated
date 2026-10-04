import time
from dataclasses import dataclass
from typing import Optional, List, Union


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

    # Precise production latency timestamps (T0 - T7)
    t0_user_speech_end: Optional[float] = None  # T0: User speech end / VAD stop
    t1_interim_transcript: Optional[float] = None  # T1: Deepgram interim transcript
    t2_final_transcript: Optional[float] = None  # T2: Deepgram final transcript
    t3_turn_finalized: Optional[float] = None  # T3: User turn finalized by strategy
    t4_llm_request_started: Optional[float] = None  # T4: LLM request dispatched downstream
    t5_llm_first_token: Optional[float] = None  # T5: LLM first token received
    t6_first_tts_text: Optional[float] = None  # T6: First text chunk delivered to TTS
    t7_first_tts_audio: Optional[float] = None  # T7: First TTS audio chunk emitted

    # Context Token Breakdown Instrumentation (Section 15)
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
        return (t2 - t0) if (t0 and t2) else None

    @property
    def turn_aggregation_latency(self) -> Optional[float]:
        t2 = self.t2_final_transcript or self.stt_first_transcript
        t3 = self.t3_turn_finalized
        return (t3 - t2) if (t2 and t3) else None

    @property
    def llm_dispatch_latency(self) -> Optional[float]:
        t3 = self.t3_turn_finalized
        t4 = self.t4_llm_request_started
        return (t4 - t3) if (t3 and t4) else None

    @property
    def groq_ttft(self) -> Optional[float]:
        t4 = self.t4_llm_request_started
        t5 = self.t5_llm_first_token or self.llm_first_token
        return (t5 - t4) if (t4 and t5) else None

    @property
    def llm_ttft(self) -> Optional[float]:
        t4 = self.t4_llm_request_started
        t5 = self.t5_llm_first_token or self.llm_first_token
        return (t5 - t4) if (t4 and t5) else None

    @property
    def user_stop_to_first_llm_token(self) -> Optional[float]:
        t0 = self.t0_user_speech_end or self.vad_stop
        t5 = self.t5_llm_first_token or self.llm_first_token
        return (t5 - t0) if (t0 and t5) else None

    @property
    def user_stop_to_first_tts_audio(self) -> Optional[float]:
        t0 = self.t0_user_speech_end or self.vad_stop
        t7 = self.t7_first_tts_audio or self.tts_first_audio
        return (t7 - t0) if (t0 and t7) else None

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
                print(f"Groq TTFT       : {self.groq_ttft:.3f} s (T5 - T4)")

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


class LatencyTracker:
    def __init__(self):
        self.all_turns: List[TurnLatency] = []
        self.current_turn: Optional[TurnLatency] = None
        self.turn_count = 0
        self._pending_vad_start: Optional[float] = None
        self._pending_stt_interim: Optional[float] = None
        self._pending_vad_stop: Optional[float] = None

    def on_vad_start(self):
        """Called when UserStartedSpeakingFrame is received.
        Records pending start timestamp. Turn counter is only committed once verified.
        """
        self._pending_vad_start = time.perf_counter()
        if self.current_turn and (self.current_turn.stt_first_transcript or self.current_turn.tts_first_audio or self.current_turn.llm_complete):
            self.all_turns.append(self.current_turn)
            self.current_turn = None

    def on_stt_interim(self):
        """Called when an InterimTranscriptionFrame is received (T1)."""
        now = time.perf_counter()
        self._pending_stt_interim = now
        if self.current_turn and self.current_turn.t1_interim_transcript is None:
            self.current_turn.t1_interim_transcript = now

    def on_stt_transcript(self):
        """Called when the first TranscriptionFrame with text is received (T2)."""
        now = time.perf_counter()
        if self.current_turn is None:
            self.turn_count += 1
            vad_start = self._pending_vad_start or now
            self._pending_vad_start = None
            self.current_turn = TurnLatency(
                turn_number=self.turn_count,
                vad_start=vad_start,
                vad_stop=self._pending_vad_stop,
                t0_user_speech_end=self._pending_vad_stop,
                t1_interim_transcript=self._pending_stt_interim,
            )
            self._pending_vad_stop = None
            self._pending_stt_interim = None

        if self.current_turn:
            if self.current_turn.stt_first_transcript is None:
                self.current_turn.stt_first_transcript = now
            if self.current_turn.t2_final_transcript is None:
                self.current_turn.t2_final_transcript = now

    def on_vad_stop(self):
        """Called when UserStoppedSpeakingFrame is received (T0)."""
        now = time.perf_counter()
        self._pending_vad_stop = now
        if self.current_turn:
            if self.current_turn.vad_stop is None:
                self.current_turn.vad_stop = now
            if self.current_turn.t0_user_speech_end is None:
                self.current_turn.t0_user_speech_end = now
        # If no transcript arrived, clear pending VAD start (noise event ignored)
        self._pending_vad_start = None

    def on_turn_finalized(self):
        """Called when user turn is finalized by UserTurnStopStrategy (T3)."""
        now = time.perf_counter()
        if self.current_turn:
            if self.current_turn.t3_turn_finalized is None:
                self.current_turn.t3_turn_finalized = now

    def on_llm_request_started(self):
        """Called when LLMContextFrame is dispatched downstream to LLM (T4)."""
        now = time.perf_counter()
        if self.current_turn:
            if self.current_turn.t4_llm_request_started is None:
                self.current_turn.t4_llm_request_started = now

    def on_llm_context_tokens(self, breakdown):
        """Record context token breakdown for the current turn (Section 15)."""
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
        if self.current_turn is None:
            if self.turn_count == 0:
                self.current_turn = TurnLatency(turn_number="Greeting")
            else:
                self.turn_count += 1
                self.current_turn = TurnLatency(turn_number=self.turn_count)

        if self.current_turn:
            if self.current_turn.llm_first_token is None:
                self.current_turn.llm_first_token = now
            if self.current_turn.t5_llm_first_token is None:
                self.current_turn.t5_llm_first_token = now

    def on_tts_text(self):
        """Called when first TextFrame is delivered downstream to TTS (T6)."""
        now = time.perf_counter()
        if self.current_turn:
            if self.current_turn.tts_first_text is None:
                self.current_turn.tts_first_text = now
            if self.current_turn.t6_first_tts_text is None:
                self.current_turn.t6_first_tts_text = now

    def on_llm_complete(self):
        """Called when LLMFullResponseEndFrame is received."""
        if self.current_turn and self.current_turn.llm_complete is None:
            self.current_turn.llm_complete = time.perf_counter()
            self._check_turn_completion()

    def on_tts_start(self):
        """Called when TTSStartedFrame is received (T7)."""
        now = time.perf_counter()
        if self.current_turn:
            if self.current_turn.tts_first_audio is None:
                self.current_turn.tts_first_audio = now
            if self.current_turn.t7_first_tts_audio is None:
                self.current_turn.t7_first_tts_audio = now
            self._check_turn_completion()

    def _check_turn_completion(self):
        if self.current_turn and self.current_turn.is_complete():
            self.current_turn.print_benchmark()
            self.all_turns.append(self.current_turn)
            self.current_turn = None

    def print_summary(self):
        """Prints the summary table of all completed turns at the end of the call."""
        if not self.all_turns:
            print("\nNo complete turns to summarize.")
            return

        print("\n" + "-" * 63)
        print(f"{'Turn':<15}{'Thinking':<15}{'TTS':<15}{'Total Response':<15}")
        print("-" * 63)

        valid_thinking = []
        valid_tts = []
        valid_total = []

        for t in self.all_turns:
            turn_name = str(t.turn_number)
            if turn_name != "Greeting":
                turn_name = f"Turn {turn_name}"

            tts_lat = t.tts_first_audio - t.llm_complete
            valid_tts.append(tts_lat)

            if t.turn_number == "Greeting":
                thinking_str = "--"
                total_str = "--"
            else:
                thinking = t.llm_first_token - t.vad_stop
                total = t.tts_first_audio - t.vad_stop
                thinking_str = f"{thinking:.2f} s"
                total_str = f"{total:.2f} s"
                valid_thinking.append(thinking)
                valid_total.append(total)

            tts_str = f"{tts_lat:.2f} s"
            print(f"{turn_name:<15}{thinking_str:<15}{tts_str:<15}{total_str:<15}")

        print("-" * 63)

        avg_thinking = sum(valid_thinking) / len(valid_thinking) if valid_thinking else 0.0
        avg_tts = sum(valid_tts) / len(valid_tts) if valid_tts else 0.0
        avg_total = sum(valid_total) / len(valid_total) if valid_total else 0.0

        avg_thinking_str = f"{avg_thinking:.2f} s" if valid_thinking else "--"
        avg_tts_str = f"{avg_tts:.2f} s" if valid_tts else "--"
        avg_total_str = f"{avg_total:.2f} s" if valid_total else "--"

        print(f"{'Average':<15}{avg_thinking_str:<15}{avg_tts_str:<15}{avg_total_str:<15}")
        print("-" * 63)
