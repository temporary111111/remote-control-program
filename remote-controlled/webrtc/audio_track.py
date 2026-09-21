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
        self._frame_count = 0
        self._diag_start = time.time()
        self._total_silence = 0
        self._total_audio = 0

    async def recv(self) -> AudioFrame:
        if self._start_time is None:
            self._start_time = time.time()
            logger.info("AudioCaptureTrack: first recv() call")
        
        was_silence = False
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
                if self._frame_count < 5:
                    rms = float(np.sqrt(np.mean(data.astype(np.float32) ** 2)))
                    logger.info(
                        f"AudioTrack recv got {source_type}: shape={data.shape} "
                        f"rms={rms:.6f} buffer_now={len(self._buffer)}"
                    )
            else:
                remaining = self.frame_size - len(self._buffer)
                if remaining > 0:
                    silence = np.zeros((remaining, self.channels), dtype=np.float32)
                    self._buffer = np.vstack([self._buffer, silence])
                was_silence = True
                break
        
        frame_data = self._buffer[:self.frame_size]
        self._buffer = self._buffer[self.frame_size:]
        
        frame_data = np.clip(frame_data, -1.0, 1.0)
        frame_data_int = (frame_data * 32767).astype(np.int16)
        
        pts = self._timestamp
        time_base = fractions.Fraction(1, self.sample_rate)
        self._timestamp += self.frame_size
        
        self._frame_count += 1
        if was_silence:
            self._total_silence += 1
        else:
            self._total_audio += 1

        elapsed = time.time() - self._diag_start
        if elapsed >= 5.0:
            mean_amp = float(np.mean(np.abs(frame_data)))
            peak_amp = float(np.max(np.abs(frame_data)))
            rms = float(np.sqrt(np.mean(frame_data.astype(np.float32) ** 2)))
            logger.info(
                f"AudioTrack diag: frames={self._frame_count} audio={self._total_audio} "
                f"silence={self._total_silence} mean_amp={mean_amp:.6f} "
                f"peak_amp={peak_amp:.6f} rms={rms:.6f} "
                f"buffered={len(self._buffer)} timestamp={self._timestamp}"
            )
            self._frame_count = 0
            self._total_silence = 0
            self._total_audio = 0
            self._diag_start = time.time()
        
        audio_frame = AudioFrame.from_ndarray(frame_data_int.T, format="s16", layout="stereo" if self.channels == 2 else "mono")
        audio_frame.sample_rate = self.sample_rate
        audio_frame.pts = pts
        audio_frame.time_base = time_base
        
        return audio_frame