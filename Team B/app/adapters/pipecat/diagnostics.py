from loguru import logger
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.frames.frames import Frame

class DiagnosticsProcessor(FrameProcessor):
    async def process_frame(self, frame: Frame, direction: FrameDirection):
        logger.info(f"[DIAGNOSTICS] Frame: {type(frame).__name__} | Direction: {direction}")
        await self.push_frame(frame, direction)
