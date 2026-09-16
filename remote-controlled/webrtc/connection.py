import asyncio
import json
import logging
from typing import Optional, Callable

from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
from aiortc.contrib.media import MediaRelay

from utils.logger import logger
from webrtc.video_track import ScreenVideoTrack
from webrtc.audio_track import AudioCaptureTrack
from capture.input import InputHandler


def parse_ice_candidate(candidate_str: str) -> dict:
    """Parse ICE candidate string into components for RTCIceCandidate constructor."""
    parts = candidate_str.split()
    if not parts or not parts[0].startswith("candidate:"):
        raise ValueError(f"Invalid candidate string: {candidate_str}")
    
    foundation = parts[0][10:]  # remove "candidate:"
    component = int(parts[1])
    protocol = parts[2]
    priority = int(parts[3])
    ip = parts[4]
    port = int(parts[5])
    
    typ_idx = parts.index("typ") if "typ" in parts else -1
    if typ_idx == -1 or typ_idx + 1 >= len(parts):
        raise ValueError(f"Missing 'typ' in candidate: {candidate_str}")
    candidate_type = parts[typ_idx + 1]
    
    related_address = None
    related_port = None
    
    if "raddr" in parts:
        raddr_idx = parts.index("raddr")
        if raddr_idx + 1 < len(parts):
            related_address = parts[raddr_idx + 1]
    
    if "rport" in parts:
        rport_idx = parts.index("rport")
        if rport_idx + 1 < len(parts):
            related_port = int(parts[rport_idx + 1])
    
    return {
        "component": 1,
        "foundation": foundation,
        "ip": ip,
        "port": port,
        "priority": priority,
        "protocol": protocol,
        "type": candidate_type,
        "relatedAddress": related_address,
        "relatedPort": related_port,
    }


class WebRTCConnection:
    def __init__(
        self,
        frame_queue: asyncio.Queue,
        audio_capturer,
        fps: int = 30,
        sample_rate: int = 48000,
        channels: int = 2,
        max_bitrate: int = 5000000,
    ):
        self.frame_queue = frame_queue
        self.audio_capturer = audio_capturer
        self.fps = fps
        self.sample_rate = sample_rate
        self.channels = channels
        self.max_bitrate = max_bitrate
        
        self.pc: Optional[RTCPeerConnection] = None
        self.video_track: Optional[ScreenVideoTrack] = None
        self.audio_track: Optional[AudioCaptureTrack] = None
        self.input_handler: Optional[InputHandler] = None
        self.data_channel = None
        
        self._on_ice_candidate: Optional[Callable] = None
        self._on_connection_state_change: Optional[Callable] = None

    def set_ice_candidate_callback(self, callback: Callable):
        self._on_ice_candidate = callback

    def set_connection_state_callback(self, callback: Callable):
        self._on_connection_state_change = callback

    async def _initialize_peer_connection(self):
        """Initialize peer connection, tracks, and data channel (used for both offer/answer flows)"""
        if self.pc is not None:
            return
            
        config = RTCConfiguration(
            iceServers=[
                RTCIceServer(urls="stun:stun.l.google.com:19302"),
                RTCIceServer(urls="stun:stun1.l.google.com:19302"),
            ]
        )
        
        self.pc = RTCPeerConnection(configuration=config)
        self._setup_event_handlers()
        
        self.video_track = ScreenVideoTrack(self.frame_queue, self.fps)
        self.audio_track = AudioCaptureTrack(self.audio_capturer, self.sample_rate, self.channels)
        
        video_sender = self.pc.addTrack(self.video_track)
        audio_sender = self.pc.addTrack(self.audio_track)
        
        if video_sender:
            try:
                params = video_sender.getParameters()
                params.encodings[0].maxBitrate = self.max_bitrate
                await video_sender.setParameters(params)
            except AttributeError:
                logger.warning("getParameters/setParameters not available, skipping bitrate limit")
        
        self.data_channel = self.pc.createDataChannel("input", ordered=True)
        self._setup_data_channel()
        
        self.input_handler = InputHandler()
        input_queue = asyncio.Queue()
        await self.input_handler.start(input_queue)

    async def create_offer(self) -> RTCSessionDescription:
        await self._initialize_peer_connection()
        
        offer = await self.pc.createOffer()
        await self.pc.setLocalDescription(offer)
        
        return self.pc.localDescription

    async def set_remote_description(self, sdp: str, type: str):
        await self._initialize_peer_connection()
        await self.pc.setRemoteDescription(RTCSessionDescription(sdp, type))

    async def create_answer(self):
        if self.pc:
            logger.info("Creating answer...")
            answer = await self.pc.createAnswer()
            logger.info(f"Answer created: {answer.sdp[:100]}...")
            await self.pc.setLocalDescription(answer)
            logger.info(f"Local description set: {self.pc.localDescription is not None}")
            return self.pc.localDescription
        logger.error("No peer connection to create answer")
        return None

    async def add_ice_candidate(self, candidate: str, sdp_mid: str, sdp_mline_index: int):
        if self.pc:
            logger.info(f"Adding ICE candidate: candidate={candidate[:50]}..., mid={sdp_mid}, mline={sdp_mline_index}")
            try:
                from aiortc import RTCIceCandidate
                # Parse candidate string and create RTCIceCandidate with proper components
                parsed = parse_ice_candidate(candidate)
                ice_candidate = RTCIceCandidate(
                    **parsed,
                    sdpMid=sdp_mid,
                    sdpMLineIndex=sdp_mline_index,
                )
                await self.pc.addIceCandidate(ice_candidate)
            except Exception as e:
                logger.error(f"Failed to add ICE candidate: {e}")
                raise

    def _setup_event_handlers(self):
        @self.pc.on("icecandidate")
        def on_ice_candidate(candidate):
            if candidate and self._on_ice_candidate:
                asyncio.create_task(self._on_ice_candidate(
                    candidate.candidate,
                    candidate.sdpMid,
                    candidate.sdpMLineIndex
                ))

        @self.pc.on("connectionstatechange")
        def on_connection_state_change():
            state = self.pc.connectionState
            logger.info(f"WebRTC connection state: {state}")
            if self._on_connection_state_change:
                asyncio.create_task(self._on_connection_state_change(state))
            
            if state in ("failed", "closed", "disconnected"):
                asyncio.create_task(self.close())

        @self.pc.on("datachannel")
        def on_data_channel(channel):
            logger.info(f"Data channel received: {channel.label}")
            self.data_channel = channel
            self._setup_data_channel()

    def _setup_data_channel(self):
        if not self.data_channel:
            return
        
        @self.data_channel.on("message")
        def on_message(message):
            try:
                data = json.loads(message)
                if self.input_handler:
                    asyncio.create_task(self.input_handler._queue.put(data))
            except Exception as e:
                logger.error(f"Data channel message error: {e}")

        @self.data_channel.on("open")
        def on_open():
            logger.info("Data channel opened")

        @self.data_channel.on("close")
        def on_close():
            logger.info("Data channel closed")

    async def close(self):
        logger.info("Closing WebRTC connection")
        
        if self.input_handler:
            await self.input_handler.stop()
            self.input_handler = None
        
        if self.pc:
            await self.pc.close()
            self.pc = None
        
        self.video_track = None
        self.audio_track = None
        self.data_channel = None