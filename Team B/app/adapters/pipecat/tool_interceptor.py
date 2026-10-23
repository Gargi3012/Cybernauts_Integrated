import re
import json
import asyncio
from loguru import logger

from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.frames.frames import Frame, TextFrame, LLMFullResponseEndFrame

class ToolInterceptionProcessor(FrameProcessor):
    """
    Intercepts streaming TextFrames from the LLM, detects text-based function calls
    like (function=save_lead>...) and (function=end_call>), runs/flags the tools, 
    and filters out the tool call text so the user never hears it spoken.
    """
    def __init__(self, shared_state=None, **kwargs):
        kwargs.setdefault("enable_direct_mode", True)
        super().__init__(**kwargs)
        self._buffer = ""
        self.shared_state = shared_state if shared_state is not None else {}
        self._current_gen_id = None
        self._current_turn_id = None

    def _create_text_frame(self, text: str, source_frame: Frame = None) -> TextFrame:
        tf = TextFrame(text=text)
        gen = getattr(source_frame, "_generation_id", None) or self._current_gen_id or self.shared_state.get("active_generation_id")
        turn = getattr(source_frame, "_turn_id", None) or self._current_turn_id or self.shared_state.get("current_turn_id")
        if gen is not None:
            tf._generation_id = gen
        if turn is not None:
            tf._turn_id = turn
        return tf

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if hasattr(frame, "_generation_id") and getattr(frame, "_generation_id") is not None:
            self._current_gen_id = frame._generation_id
        if hasattr(frame, "_turn_id") and getattr(frame, "_turn_id") is not None:
            self._current_turn_id = frame._turn_id

        if isinstance(frame, TextFrame):
            text = frame.text
            self._buffer += text
            
            # If we see potential function tags/blocks, we buffer and wait to parse
            if "function=" in self._buffer or "save_lead" in self._buffer or "end_call" in self._buffer or (len(self._buffer) < 20 and any(self._buffer.startswith(x) for x in ["(", "<", "function", "func"])):
                # 1. Match save_lead tool call block
                pattern_save = r'(?:\(|<)?\s*function=save_lead\s*>?\s*({.*?})(?:\s*<\/function>|\s*\)|>)?'
                match_save = re.search(pattern_save, self._buffer, re.DOTALL)
                if match_save:
                    try:
                        args_str = match_save.group(1)
                        args = json.loads(args_str)
                        name = args.get("name", "")
                        phone = args.get("phone", "")
                        # Deterministic phone number override: The LLM must NOT determine the digits
                        if self.shared_state and "phone_normalizer" in self.shared_state:
                            norm = self.shared_state["phone_normalizer"]
                            if hasattr(norm, "digits") and len(norm.digits) == 10:
                                phone = norm.digits
                        project_details = args.get("project_details", "")
                        if name or phone:
                            logger.info(f"ToolInterceptionProcessor: Intercepted text tool call! name='{name}', phone='{phone}', project='{project_details}'")
                            if self.shared_state and "qualification_machine" in self.shared_state:
                                qm = self.shared_state["qualification_machine"]
                                asyncio.create_task(qm.execute_save(custom_name=name, custom_phone=phone, custom_details=project_details))
                            else:
                                from app.services.lead_manager import save_lead
                                asyncio.create_task(save_lead(None, name, phone, project_details))
                    except Exception as e:
                        logger.error(f"ToolInterceptionProcessor: Failed to parse save_lead args: {e}")
                    
                    matched_str = match_save.group(0)
                    self._buffer = self._buffer.replace(matched_str, "")

                # 2. Match end_call tool call block
                pattern_end = r'(?:\(|<)?\s*function=end_call\s*>?\s*({.*?})?(?:\s*<\/function>|\s*\)|>)?'
                match_end = re.search(pattern_end, self._buffer, re.DOTALL)
                if match_end:
                    logger.info("ToolInterceptionProcessor: Intercepted text tool call for end_call!")
                    if self.shared_state and "qualification_machine" in self.shared_state:
                        qm = self.shared_state["qualification_machine"]
                        asyncio.create_task(qm.handle_end_call_request())
                    else:
                        self.shared_state["hangup_requested"] = True
                    matched_str = match_end.group(0)
                    self._buffer = self._buffer.replace(matched_str, "")
                
                # Push whatever non-tool text remains in the buffer downstream if we aren't accumulating
                # a tag.
                if not any(x in self._buffer for x in ["function=", "save_lead", "end_call"]):
                    if self._buffer.strip():
                        await self.push_frame(self._create_text_frame(self._buffer, frame), direction)
                    self._buffer = ""
            else:
                # Normal text, push immediately
                if self._buffer:
                    await self.push_frame(self._create_text_frame(self._buffer, frame), direction)
                    self._buffer = ""
                    
        elif isinstance(frame, LLMFullResponseEndFrame):
            # Clean any remaining partial tool tags at the end of the response
            if self._buffer:
                clean_text = re.sub(r'(?:\(|<)?\s*function=save_lead.*$', '', self._buffer, flags=re.DOTALL).strip()
                clean_text = re.sub(r'(?:\(|<)?\s*function=end_call.*$', '', clean_text, flags=re.DOTALL).strip()
                # Remove loose closing tags if any
                clean_text = clean_text.replace("</function>", "").replace("</function", "").strip()
                if clean_text:
                    await self.push_frame(self._create_text_frame(clean_text, frame), direction)
            self._buffer = ""
            await self.push_frame(frame, direction)
            
        else:
            await self.push_frame(frame, direction)
