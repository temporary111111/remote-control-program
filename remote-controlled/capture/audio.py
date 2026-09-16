import asyncio
import sys
from typing import Optional

import numpy as np
import sounddevice as sd

from utils.logger import logger


class AudioCapturer:
    def __init__(
        self,
        sample_rate: int = 48000,
        channels: int = 2,
        include_system: bool = True,
        include_mic: bool = True,
        block_size: int = 1024,
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.include_system = include_system
        self.include_mic = include_mic
        self.block_size = block_size
        
        self._system_stream: Optional[sd.InputStream] = None
        self._mic_stream: Optional[sd.InputStream] = None
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=50)
        self._running = False
        self._task: asyncio.Task | None = None

    def _list_devices(self):
        devices = sd.query_devices()
        logger.info("Available audio devices:")
        for i, d in enumerate(devices):
            logger.info(f"  [{i}] {d['name']} (in={d['max_input_channels']}, out={d['max_output_channels']})")

    def _find_loopback_device(self) -> Optional[int]:
        devices = sd.query_devices()
        for i, d in enumerate(devices):
            if d["max_input_channels"] > 0:
                name = d["name"].lower()
                if any(kw in name for kw in ["stereo mix", "loopback", "wave", "what u hear", "monitor"]):
                    logger.info(f"Found loopback device: [{i}] {d['name']}")
                    return i
        return None

    def _find_mic_device(self) -> Optional[int]:
        devices = sd.query_devices()
        default_input = sd.default.device[0]
        if default_input is not None and default_input >= 0:
            logger.info(f"Using default mic: [{default_input}] {devices[default_input]['name']}")
            return default_input
        for i, d in enumerate(devices):
            if d["max_input_channels"] > 0:
                name = d["name"].lower()
                if any(kw in name for kw in ["microphone", "mic ", "headset", "webcam"]):
                    logger.info(f"Found mic device: [{i}] {d['name']}")
                    return i
        return None

    def _system_callback(self, indata, frames, time, status):
        if status:
            logger.warning(f"System audio status: {status}")
        if self._running:
            try:
                self._queue.put_nowait(("system", indata.copy()))
            except asyncio.QueueFull:
                pass

    def _mic_callback(self, indata, frames, time, status):
        if status:
            logger.warning(f"Mic audio status: {status}")
        if self._running:
            try:
                self._queue.put_nowait(("mic", indata.copy()))
            except asyncio.QueueFull:
                pass

    async def start(self, queue: asyncio.Queue):
        self._queue = queue
        self._running = True
        
        self._list_devices()
        
        if self.include_system:
            loopback_idx = self._find_loopback_device()
            if loopback_idx is not None:
                try:
                    self._system_stream = sd.InputStream(
                        device=loopback_idx,
                        samplerate=self.sample_rate,
                        channels=self.channels,
                        dtype="float32",
                        blocksize=self.block_size,
                        callback=self._system_callback,
                    )
                    self._system_stream.start()
                    logger.info("System audio capture started")
                except Exception as e:
                    logger.error(f"Failed to start system audio: {e}")
            else:
                logger.warning("No loopback device found. System audio will not be captured.")

        if self.include_mic:
            mic_idx = self._find_mic_device()
            if mic_idx is not None:
                try:
                    self._mic_stream = sd.InputStream(
                        device=mic_idx,
                        samplerate=self.sample_rate,
                        channels=self.channels,
                        dtype="float32",
                        blocksize=self.block_size,
                        callback=self._mic_callback,
                    )
                    self._mic_stream.start()
                    logger.info("Microphone capture started")
                except Exception as e:
                    logger.error(f"Failed to start microphone: {e}")
            else:
                logger.warning("No microphone device found.")

        self._task = asyncio.create_task(self._monitor_streams())
        logger.info("Audio capture started")

    async def stop(self):
        self._running = False
        
        if self._system_stream:
            self._system_stream.stop()
            self._system_stream.close()
        if self._mic_stream:
            self._mic_stream.stop()
            self._mic_stream.close()
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        logger.info("Audio capture stopped")

    async def _monitor_streams(self):
        while self._running:
            await asyncio.sleep(1.0)
            if self._system_stream and not self._system_stream.active:
                logger.warning("System audio stream became inactive")
            if self._mic_stream and not self._mic_stream.active:
                logger.warning("Microphone stream became inactive")

    async def get_mixed_audio(self) -> Optional[np.ndarray]:
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            return None