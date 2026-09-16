import asyncio
import ctypes
import sys
from pathlib import Path

import mss
import numpy as np
from PIL import Image

from utils.logger import logger


def resource_path(relative_path: str) -> Path:
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).parent.parent
    return base / relative_path


class ScreenCapturer:
    def __init__(self, monitor: int = 1, fps: int = 30):
        self.monitor_index = monitor
        self.fps = fps
        self.sct = mss.mss()
        self.monitor = self.sct.monitors[monitor]
        
        cursor_path = resource_path("assets/cursor.png")
        if cursor_path.exists():
            self.cursor_img = Image.open(cursor_path).convert("RGBA")
        else:
            self.cursor_img = self._create_default_cursor()
        
        self._running = False
        self._task: asyncio.Task | None = None

    def _create_default_cursor(self) -> Image.Image:
        img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        draw = Image.Draw(img)
        draw.polygon([(0, 0), (16, 16), (0, 32)], fill=(255, 255, 255, 255), outline=(0, 0, 0, 255))
        return img

    def _get_cursor_pos(self) -> tuple[int, int]:
        pt = ctypes.wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return pt.x - self.monitor["left"], pt.y - self.monitor["top"]

    async def start(self, queue: asyncio.Queue):
        self._running = True
        self._task = asyncio.create_task(self._capture_loop(queue))
        logger.info(f"Screen capture started: monitor={self.monitor_index}, fps={self.fps}")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Screen capture stopped")

    async def _capture_loop(self, queue: asyncio.Queue):
        frame_time = 1.0 / self.fps
        
        while self._running:
            loop_start = asyncio.get_event_loop().time()
            
            try:
                frame = await asyncio.get_event_loop().run_in_executor(None, self._grab_frame)
                await queue.put(frame)
            except Exception as e:
                logger.error(f"Screen capture error: {e}")
                await asyncio.sleep(0.1)
                continue
            
            elapsed = asyncio.get_event_loop().time() - loop_start
            sleep_time = max(0, frame_time - elapsed)
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)

    def _grab_frame(self) -> np.ndarray:
        screenshot = self.sct.grab(self.monitor)
        # mss returns BGRA, convert to RGBA by swapping R and B channels
        frame = np.array(screenshot)[:, :, [2, 1, 0, 3]]
        
        cx, cy = self._get_cursor_pos()
        if 0 <= cx < frame.shape[1] and 0 <= cy < frame.shape[0]:
            cursor_w, cursor_h = self.cursor_img.size
            x = max(0, min(cx, frame.shape[1] - cursor_w))
            y = max(0, min(cy, frame.shape[0] - cursor_h))
            
            pil_frame = Image.fromarray(frame, "RGBA")
            pil_frame.paste(self.cursor_img, (x, y), self.cursor_img)
            frame = np.array(pil_frame)
        
        return frame