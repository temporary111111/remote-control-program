import asyncio
import queue
import sys
import threading
import time
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
        self._queue: queue.Queue = queue.Queue(maxsize=200)
        self._running = False
        self._monitor_task: asyncio.Task | None = None
        self._use_wasapi = False

        self._wasapi_callback_count = 0
        self._wasapi_diag_start = time.time()
        self._sd_callback_count = 0
        self._sd_diag_start = time.time()
        self._mic_callback_count = 0
        self._mic_diag_start = time.time()
        self._queue_put_ok = 0
        self._queue_put_fail = 0

    def _system_callback(self, indata, frames, time_info, status):
        if status:
            logger.warning(f"Sounddevice audio status: {status}")
        if self._running:
            self._sd_callback_count += 1
            elapsed = time.time() - self._sd_diag_start
            if elapsed >= 5.0:
                rms = float(np.sqrt(np.mean(indata.astype(np.float32) ** 2)))
                logger.info(
                    f"Sounddevice callback: count={self._sd_callback_count} "
                    f"rms={rms:.6f} shape={indata.shape} dtype={indata.dtype}"
                )
                self._sd_callback_count = 0
                self._sd_diag_start = time.time()
            try:
                self._queue.put_nowait(("system", indata.copy()))
                self._queue_put_ok += 1
            except queue.Full:
                self._queue_put_fail += 1
            except Exception as e:
                logger.error(f"Sounddevice queue put error: {e}")

    def _mic_callback(self, indata, frames, time_info, status):
        if status:
            logger.warning(f"Mic audio status: {status}")
        if self._running:
            self._mic_callback_count += 1
            elapsed = time.time() - self._mic_diag_start
            if elapsed >= 5.0:
                rms = float(np.sqrt(np.mean(indata.astype(np.float32) ** 2)))
                logger.info(
                    f"Mic callback: count={self._mic_callback_count} rms={rms:.6f}"
                )
                self._mic_callback_count = 0
                self._mic_diag_start = time.time()
            try:
                self._queue.put_nowait(("mic", indata.copy()))
            except queue.Full:
                pass
            except Exception as e:
                logger.error(f"Mic queue put error: {e}")

    async def start(self, queue_async: asyncio.Queue):
        self._async_queue = queue_async
        self._running = True

        if self.include_system:
            if await self._start_wasapi_loopback():
                self._use_wasapi = True
            elif not self._start_sounddevice_loopback():
                logger.warning("No audio capture method available. Desktop audio will not be captured.")

        if self.include_mic:
            self._start_mic_sounddevice()

        self._monitor_task = asyncio.create_task(self._monitor_streams())
        logger.info("Audio capture started")

    async def _start_wasapi_loopback(self) -> bool:
        try:
            import pyaudiowpatch as pyaudio
            self._p = pyaudio.PyAudio()
        except Exception as e:
            logger.error(f"pyaudiowpatch import failed: {e}")
            return False

        try:
            wasapi_info = self._p.get_host_api_info_by_type(pyaudio.paWASAPI)
        except Exception as e:
            logger.error(f"WASAPI host API not available: {e}")
            return False

        default_speakers = None
        try:
            default_speakers = self._p.get_device_info_by_index(
                wasapi_info["defaultOutputDevice"]
            )
        except Exception as e:
            logger.error(f"No default WASAPI output device: {e}")
            return False

        if not default_speakers:
            return False

        loopback_info = None
        default_name = default_speakers["name"]
        for i in range(self._p.get_device_count()):
            d = self._p.get_device_info_by_index(i)
            if d.get("isLoopbackDevice") and d["name"] == default_name:
                loopback_info = d
                break

        if not loopback_info:
            for i in range(self._p.get_device_count()):
                d = self._p.get_device_info_by_index(i)
                if d.get("isLoopbackDevice") and default_name in d["name"]:
                    loopback_info = d
                    break

        if not loopback_info:
            logger.error(f"No loopback device found for: {default_name}")
            logger.info("Listing all WASAPI loopback devices:")
            for i in range(self._p.get_device_count()):
                d = self._p.get_device_info_by_index(i)
                if d.get("isLoopbackDevice"):
                    logger.info(f"  Loopback [{i}]: {d['name']} (in={d['maxInputChannels']})")
            return False

        logger.info(f"WASAPI loopback device: [{loopback_info['index']}] {loopback_info['name']}")
        logger.info(f"Default speakers: {default_speakers['name']}")
        logger.info(f"Loopback info: channels={loopback_info['maxInputChannels']}, rate={loopback_info['defaultSampleRate']}")

        channels = min(self.channels, int(loopback_info["maxInputChannels"]))
        if channels == 0:
            channels = 1

        logger.info(f"WASAPI opening stream: channels={channels}, rate={int(loopback_info['defaultSampleRate'])}, blocksize={self.block_size}")

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
            logger.info(f"WASAPI loopback stream started successfully (channels={channels}, rate={int(loopback_info['defaultSampleRate'])})")
            logger.info(f"WASAPI stream is_active: {self._system_stream.is_active()}")
            return True
        except Exception as e:
            logger.error(f"Failed to start WASAPI loopback stream: {e}")
            return False

    def _wasapi_callback(self, in_data, frame_count, time_info, status):
        import pyaudiowpatch as pyaudio

        self._wasapi_callback_count += 1
        elapsed = time.time() - self._wasapi_diag_start

        if status:
            logger.warning(f"WASAPI callback status: {status} (count={self._wasapi_callback_count})")

        if self._running:
            data = np.frombuffer(in_data, dtype=np.float32).reshape(-1, self.channels)
            rms = float(np.sqrt(np.mean(data ** 2)))
            peak = float(np.max(np.abs(data)))

            if elapsed >= 5.0:
                logger.info(
                    f"WASAPI callback: count={self._wasapi_callback_count} "
                    f"rms={rms:.6f} peak={peak:.6f} frames={frame_count} "
                    f"queue_ok={self._queue_put_ok} queue_fail={self._queue_put_fail} "
                    f"queue_size={self._queue.qsize()}"
                )
                self._wasapi_callback_count = 0
                self._queue_put_ok = 0
                self._queue_put_fail = 0
                self._wasapi_diag_start = time.time()
            elif self._wasapi_callback_count <= 3:
                logger.info(f"WASAPI callback #{self._wasapi_callback_count}: rms={rms:.6f} peak={peak:.6f} shape={data.shape}")

            try:
                self._queue.put_nowait(("system", data.copy()))
                self._queue_put_ok += 1
            except queue.Full:
                self._queue_put_fail += 1
            except Exception as e:
                logger.error(f"WASAPI queue put error: {e}")

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
            logger.warning("No sounddevice loopback device found")
            return False

        device_info = sd.query_devices(loopback_idx, 'input')
        sys_channels = min(self.channels, device_info['max_input_channels'])
        if sys_channels == 0:
            sys_channels = 1

        logger.info(f"Sounddevice fallback: [{loopback_idx}] {devices[loopback_idx]['name']} channels={sys_channels}")

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
            logger.info(f"Microphone capture started: [{mic_idx}] {devices[mic_idx]['name']} channels={mic_channels}")
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

        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        logger.info("Audio capture stopped")

    async def _monitor_streams(self):
        while self._running:
            await asyncio.sleep(5.0)
            qsize = self._queue.qsize()
            if qsize > 0:
                logger.debug(f"Audio thread-safe queue size: {qsize}")
            if self._use_wasapi and self._system_stream:
                active = self._system_stream.is_active()
                if not active:
                    logger.warning("WASAPI loopback stream became inactive!")
                else:
                    logger.debug(f"WASAPI stream active, queue={qsize}")
            elif self._system_stream:
                if not self._system_stream.active:
                    logger.warning("System audio stream became inactive")

    async def get_mixed_audio(self):
        try:
            item = self._queue.get_nowait()
            return item
        except queue.Empty:
            return None
        except Exception as e:
            logger.error(f"Queue get error: {e}")
            return None
