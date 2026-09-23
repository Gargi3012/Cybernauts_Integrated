"""
Factory for creating common pipeline templates.
"""

from app.events import EventBus

from .builder import PipelineBuilder
from .processors import ProcessorNode, ProcessorRole


class PipelineFactory:
    """Helper class to stamp out common pipeline configurations."""

    @staticmethod
    def create_voice_pipeline(event_bus: EventBus, session_id: str) -> PipelineBuilder:
        """Create a standard Real-Time Voice Pipeline builder.
        
        Transport -> STT -> LLM -> TTS -> Output
        """
        builder = PipelineBuilder(event_bus, session_id)
        
        builder.add_transport(ProcessorNode("transport_in", ProcessorRole.TRANSPORT_INPUT, "Microphone"))
        builder.add_processor(ProcessorNode("stt", ProcessorRole.STT, "SpeechToText"))
        builder.add_processor(ProcessorNode("llm", ProcessorRole.LLM, "LanguageModel"))
        builder.add_processor(ProcessorNode("tts", ProcessorRole.TTS, "TextToSpeech"))
        builder.add_transport(ProcessorNode("transport_out", ProcessorRole.TRANSPORT_OUTPUT, "Speaker"))
        
        (
            builder
            .connect("transport_in", "stt")
            .connect("stt", "llm")
            .connect("llm", "tts")
            .connect("tts", "transport_out")
        )
        
        return builder

    @staticmethod
    def create_text_pipeline(event_bus: EventBus, session_id: str) -> PipelineBuilder:
        """Create a standard Text Chat Pipeline builder.
        
        Transport -> LLM -> Output
        """
        builder = PipelineBuilder(event_bus, session_id)
        
        builder.add_transport(ProcessorNode("text_in", ProcessorRole.TRANSPORT_INPUT, "TextInput"))
        builder.add_processor(ProcessorNode("llm", ProcessorRole.LLM, "LanguageModel"))
        builder.add_transport(ProcessorNode("text_out", ProcessorRole.TRANSPORT_OUTPUT, "TextOutput"))
        
        (
            builder
            .connect("text_in", "llm")
            .connect("llm", "text_out")
        )
        
        return builder
