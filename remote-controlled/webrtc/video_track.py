import asyncio
import fractions
import time
from typing import Optional

import numpy as np
from aiortc import VideoStreamTrack
from av import VideoFrame

from utils.logger import logger


class ScreenVideoTrack(VideoStreamTrack):
    kind = "video"

    def __init__(self, frame_queue: asyncio.Queue, fps: int = 30):
        super().__init__()
        self.frame_queue = frame_queue
        self.fps = fps
        self._timestamp = 0
        self._start_time: Optional[float] = None
        self._frame_interval = 1.0 / fps
        self._last_frame: Optional[np.ndarray] = None

    async def recv(self) -> VideoFrame:
        if self._start_time is None:
            self._start_time = time.time()
        
        try:
            frame = await asyncio.wait_for(self.frame_queue.get(), timeout=1.0)
            self._last_frame = frame
        except asyncio.TimeoutError:
            if self._last_frame is not None:
                frame = self._last_frame
            else:
                frame = np.zeros((720, 1280, 4), dtype=np.uint8)
        
        pts = self._timestamp
        time_base = fractions.Fraction(1, self.fps)
        self._timestamp += 1
        
        video_frame = VideoFrame.from_ndarray(frame, format="rgba")
        video_frame.pts = pts
        video_frame.time_base = time_base
        
        return video_frame