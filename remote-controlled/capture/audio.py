import asyncio
import sys
import threading
from typing import Optional

import numpy as np

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

        self._p = None
        self._system_stream = None
        self._mic_stream = None
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=50)
        self._running = False
        self._task: asyncio.Task | None = None
        self._use_wasapi = False

    def _system_callback(self, indata, frames, time_info, status):
        if status:
            logger.warning(f"System audio status: {status}")
        if self._running:
            try:
                self._queue.put_nowait(("system", indata.copy()))
            except asyncio.QueueFull:
                pass

    def _mic_callback(self, indata, frames, time_info, status):
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

        if self.include_system:
            if await self._start_wasapi_loopback():
                self._use_wasapi = True
            elif not self._start_sounddevice_loopback():
                logger.warning("No audio capture method available. Desktop audio will not be captured.")

        if self.include_mic:
            self._start_mic_sounddevice()

        self._task = asyncio.create_task(self._monitor_streams())
        logger.info("Audio capture started")

    async def _start_wasapi_loopback(self) -> bool:
        try:
            import pyaudiowpatch as pyaudio
            self._p = pyaudio.PyAudio()
        except Exception as e:
            logger.debug(f"pyaudiowpatch not available: {e}")
            return False

        try:
            wasapi_info = self._p.get_host_api_info_by_type(pyaudio.paWASAPI)
        except Exception:
            logger.debug("WASAPI not available")
            return False

        default_speakers = None
        try:
            default_speakers = self._p.get_device_info_by_index(
                wasapi_info["defaultOutputDevice"]
            )
        except Exception:
            logger.debug("No default WASAPI output device")
            return False

        if not default_speakers:
            return False

        try:
            loopback_info = self._p.get_device_info_by_index(default_speakers["loopbackDevice"])
        except Exception:
            logger.debug(f"No loopback device for: {default_speakers['name']}")
            return False

        logger.info(f"WASAPI loopback device: [{loopback_info['index']}] {loopback_info['name']}")
        logger.info(f"Default speakers: {default_speakers['name']}")

        channels = min(self.channels, int(loopback_info["maxInputChannels"]))
        if channels == 0:
            channels = 1

        try:
            self._system_stream = self._p.open(
                format=pyaudio.paFloat32,
                channels=channels,
                rate=int(loopback_info["defaultSampleRate"]),
                input=True,
                input_device_index=loopback_info["index"],
                frames_per_buffer=self.block_size,
                stream_callback=self._wasapi_callback,
            )
            self._system_stream.start_stream()
            logger.info(f"WASAPI loopback capture started (channels={channels}, rate={int(loopback_info['defaultSampleRate'])})")
            return True
        except Exception as e:
            logger.error(f"Failed to start WASAPI loopback: {e}")
            return False

    def _wasapi_callback(self, in_data, frame_count, time_info, status):
        if status:
            logger.warning(f"WASAPI status: {status}")
        if self._running:
            import pyaudiowpatch as pyaudio
            import numpy as np
            data = np.frombuffer(in_data, dtype=np.float32).reshape(-1, self.channels)
            try:
                self._queue.put_nowait(("system", data.copy()))
            except asyncio.QueueFull:
                pass
        return (None, pyaudio.paContinue)

    def _start_sounddevice_loopback(self) -> bool:
        try:
            import sounddevice as sd
        except ImportError:
            logger.debug("sounddevice not available")
            return False

        devices = sd.query_devices()
        logger.info("Available audio devices:")
        for i, d in enumerate(devices):
            logger.info(f"  [{i}] {d['name']} (in={d['max_input_channels']}, out={d['max_output_channels']})")

        loopback_idx = None
        for i, d in enumerate(devices):
            if d["max_input_channels"] > 0:
                name = d["name"].lower()
                if any(kw in name for kw in ["stereo mix", "loopback", "wave", "what u hear", "monitor"]):
                    loopback_idx = i
                    break

        if loopback_idx is None:
            return False

        device_info = sd.query_devices(loopback_idx, 'input')
        sys_channels = min(self.channels, device_info['max_input_channels'])
        if sys_channels == 0:
            sys_channels = 1

        try:
            self._system_stream = sd.InputStream(
                device=loopback_idx,
                samplerate=self.sample_rate,
                channels=sys_channels,
                dtype="float32",
                blocksize=self.block_size,
                callback=self._system_callback,
            )
            self._system_stream.start()
            logger.info(f"Sounddevice fallback capture started (channels={sys_channels})")
            return True
        except Exception as e:
            logger.error(f"Failed to start sounddevice fallback: {e}")
            return False

    def _start_mic_sounddevice(self):
        try:
            import sounddevice as sd
        except ImportError:
            return

        devices = sd.query_devices()
        default_input = sd.default.device[0]
        mic_idx = None

        if default_input is not None and default_input >= 0:
            mic_idx = default_input
        else:
            for i, d in enumerate(devices):
                if d["max_input_channels"] > 0:
                    name = d["name"].lower()
                    if any(kw in name for kw in ["microphone", "mic ", "headset", "webcam"]):
                        mic_idx = i
                        break

        if mic_idx is None:
            logger.warning("No microphone device found.")
            return

        device_info = sd.query_devices(mic_idx, 'input')
        mic_channels = min(self.channels, device_info['max_input_channels'])
        if mic_channels == 0:
            mic_channels = 1

        try:
            self._mic_stream = sd.InputStream(
                device=mic_idx,
                samplerate=self.sample_rate,
                channels=mic_channels,
                dtype="float32",
                blocksize=self.block_size,
                callback=self._mic_callback,
            )
            self._mic_stream.start()
            logger.info(f"Microphone capture started (channels={mic_channels})")
        except Exception as e:
            logger.error(f"Failed to start microphone: {e}")

    async def stop(self):
        self._running = False

        if self._use_wasapi and self._system_stream:
            try:
                self._system_stream.stop_stream()
                self._system_stream.close()
            except Exception:
                pass
        elif self._system_stream:
            try:
                self._system_stream.stop()
                self._system_stream.close()
            except Exception:
                pass

        if self._mic_stream:
            try:
                self._mic_stream.stop()
                self._mic_stream.close()
            except Exception:
                pass

        if self._p:
            try:
                self._p.terminate()
            except Exception:
                pass
            self._p = None

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.info("Audio capture stopped")

    async def _monitor_streams(self):
        while self._running:
            await asyncio.sleep(5.0)
            if self._use_wasapi and self._system_stream:
                if not self._system_stream.is_active():
                    logger.warning("WASAPI loopback stream became inactive")
            elif self._system_stream:
                if not self._system_stream.active:
                    logger.warning("System audio stream became inactive")

    async def get_mixed_audio(self):
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            return None
