import asyncio
import fractions
import time
from typing import Optional

import numpy as np
from aiortc import AudioStreamTrack
from av import AudioFrame

from utils.logger import logger


class AudioCaptureTrack(AudioStreamTrack):
    kind = "audio"

    def __init__(
        self,
        audio_capturer,
        sample_rate: int = 48000,
        channels: int = 2,
        frame_size: int = 960,
    ):
        super().__init__()
        self.audio_capturer = audio_capturer
        self.sample_rate = sample_rate
        self.channels = channels
        self.frame_size = frame_size
        self._timestamp = 0
        self._start_time: Optional[float] = None
        self._buffer = np.zeros((0, channels), dtype=np.float32)

    async def recv(self) -> AudioFrame:
        if self._start_time is None:
            self._start_time = time.time()
        
        while len(self._buffer) < self.frame_size:
            audio_data = await self.audio_capturer.get_mixed_audio()
            if audio_data is not None:
                source_type, data = audio_data
                if data.ndim == 1:
                    data = data.reshape(-1, 1)
                if data.shape[1] != self.channels:
                    if data.shape[1] == 1 and self.channels == 2:
                        data = np.repeat(data, 2, axis=1)
                    elif data.shape[1] == 2 and self.channels == 1:
                        data = data.mean(axis=1, keepdims=True)
                self._buffer = np.vstack([self._buffer, data])
            else:
                silence = np.zeros((self.frame_size, self.channels), dtype=np.float32)
                self._buffer = np.vstack([self._buffer, silence])
                break
        
        frame_data = self._buffer[:self.frame_size]
        self._buffer = self._buffer[self.frame_size:]
        
        frame_data = np.clip(frame_data, -1.0, 1.0)
        frame_data_int = (frame_data * 32767).astype(np.int16)
        
        pts = self._timestamp
        time_base = fractions.Fraction(1, self.sample_rate)
        self._timestamp += self.frame_size
        
        audio_frame = AudioFrame.from_ndarray(frame_data_int.T, format="s16", layout="stereo" if self.channels == 2 else "mono")
        audio_frame.sample_rate = self.sample_rate
        audio_frame.pts = pts
        audio_frame.time_base = time_base
        
        return audio_frame