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
    llm_complete: Optional[float] = None
    tts_first_audio: Optional[float] = None

    def is_complete(self) -> bool:
        if self.turn_number == "Greeting":
            return (self.llm_first_token is not None and
                    self.llm_complete is not None and
                    self.tts_first_audio is not None)
        return (self.vad_start is not None and
                self.stt_first_transcript is not None and
                self.vad_stop is not None and
                self.llm_first_token is not None and
                self.llm_complete is not None and
                self.tts_first_audio is not None)

    def print_benchmark(self):
        if not self.is_complete():
            return

        print("-" * 36)
        if self.turn_number == "Greeting":
            print("Greeting")
        else:
            print(f"Turn {self.turn_number}")
        print("-" * 36)

        if self.turn_number != "Greeting":
            speech_dur = self.vad_stop - self.vad_start
            stt_lat = self.stt_first_transcript - self.vad_start
            print(f"Speech Duration : {speech_dur:.2f} s")
            print(f"STT Latency     : {stt_lat:.2f} s")
            
            thinking_time = self.llm_first_token - self.vad_stop
            print(f"Thinking Time   : {thinking_time:.2f} s")
        else:
            thinking_time = None

        llm_gen = self.llm_complete - self.llm_first_token
        tts_lat = self.tts_first_audio - self.llm_complete
        print(f"LLM Generation  : {llm_gen:.2f} s")
        print(f"TTS Latency     : {tts_lat:.2f} s")

        if self.turn_number != "Greeting":
            total_resp = self.tts_first_audio - self.vad_stop
            print(f"Total Response  : {total_resp:.2f} s")

        print("-" * 36)


class LatencyTracker:
    def __init__(self):
        self.all_turns: List[TurnLatency] = []
        self.current_turn: Optional[TurnLatency] = None
        self.turn_count = 0

    def on_vad_start(self):
        """Called when UserStartedSpeakingFrame is received."""
        self.turn_count += 1
        self.current_turn = TurnLatency(turn_number=self.turn_count, vad_start=time.perf_counter())

    def on_stt_transcript(self):
        """Called when the first TranscriptionFrame with text is received."""
        if self.current_turn and self.current_turn.stt_first_transcript is None:
            self.current_turn.stt_first_transcript = time.perf_counter()

    def on_vad_stop(self):
        """Called when UserStoppedSpeakingFrame is received."""
        if self.current_turn and self.current_turn.vad_stop is None:
            self.current_turn.vad_stop = time.perf_counter()

    def on_llm_first_token(self):
        """Called when LLMFullResponseStartFrame is received."""
        if self.current_turn is None and self.turn_count == 0:
            # Assumed to be the initial greeting if no speech has occurred yet
            self.current_turn = TurnLatency(turn_number="Greeting")

        if self.current_turn and self.current_turn.llm_first_token is None:
            self.current_turn.llm_first_token = time.perf_counter()

    def on_llm_complete(self):
        """Called when LLMFullResponseEndFrame is received."""
        if self.current_turn and self.current_turn.llm_complete is None:
            self.current_turn.llm_complete = time.perf_counter()

    def on_tts_start(self):
        """Called when TTSStartedFrame is received."""
        if self.current_turn and self.current_turn.tts_first_audio is None:
            self.current_turn.tts_first_audio = time.perf_counter()

            if self.current_turn.is_complete():
                self.current_turn.print_benchmark()
                self.all_turns.append(self.current_turn)
            
            # Reset current turn so the next vad_start correctly initializes a new turn
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
