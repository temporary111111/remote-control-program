import asyncio
import sys
import yaml
from pathlib import Path

from utils.logger import logger, setup_logger
from utils.tunnel import CloudflareTunnel
from utils.telegram import TelegramNotifier
from utils.autostart import AutoStart
from signaling.server import SignalingServer
from capture.screen import ScreenCapturer
from capture.audio import AudioCapturer
from capture.input import InputHandler
from webrtc.connection import WebRTCConnection


def get_base_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).parent


class RemoteControlledApp:
    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = str(get_base_path() / "config.yaml")
        with open(config_path) as f:
            self.config = yaml.safe_load(f)
        
        self.server_config = self.config["server"]
        self.capture_config = self.config["capture"]
        self.webrtc_config = self.config["webrtc"]
        
        self.frame_queue: asyncio.Queue = asyncio.Queue(maxsize=5)
        self.screen_capturer: ScreenCapturer | None = None
        self.audio_capturer: AudioCapturer | None = None
        self.signaling: SignalingServer | None = None
        self.webrtc: WebRTCConnection | None = None
        self.tunnel: CloudflareTunnel | None = None
        self.telegram: TelegramNotifier | None = None
        
        self._running = False
        self._tasks: list[asyncio.Task] = []

    async def start(self):
        self._running = True
        logger.info("Starting remote-controlled server...")
        
        AutoStart.install()
        self._init_telegram()
        await self._start_capture()
        await self._start_signaling()
        await self._start_tunnel()
        await self._run_webrtc_loop()
    
    def _init_telegram(self):
        telegram_cfg = self.config.get("telegram", {})
        if telegram_cfg.get("enabled"):
            self.telegram = TelegramNotifier(
                bot_token=telegram_cfg["bot_token"],
                chat_id=telegram_cfg["chat_id"],
            )
            logger.info("Telegram notifier enabled")
    
    async def _start_capture(self):
        screen_cfg = self.capture_config["screen"]
        audio_cfg = self.capture_config["audio"]
        
        self.screen_capturer = ScreenCapturer(
            monitor=screen_cfg["monitor"],
            fps=screen_cfg["fps"],
        )
        await self.screen_capturer.start(self.frame_queue)
        
        self.audio_capturer = AudioCapturer(
            sample_rate=audio_cfg["sample_rate"],
            channels=audio_cfg["channels"],
            include_system=audio_cfg.get("include_system", True),
            include_mic=audio_cfg.get("include_mic", True),
        )
        await self.audio_capturer.start(asyncio.Queue())
        
        logger.info("Capture systems started")

    async def _start_signaling(self):
        self.signaling = SignalingServer(
            host="0.0.0.0",
            port=self.server_config["port"],
            path=self.server_config["signaling_path"],
        )
        
        self.signaling.set_connection_state_callback = lambda cb: None
        
        runner = await self.signaling.start()
        self._signaling_runner = runner
        logger.info("Signaling server started")

    async def _start_tunnel(self):
        self.tunnel = CloudflareTunnel(self.server_config["port"])
        tunnel_url = await self.tunnel.start()
        
        print("\n" + "=" * 60)
        print(f"Tunnel ready: {tunnel_url}")
        print("=" * 60 + "\n")
        
        logger.info(f"Tunnel URL: {tunnel_url}")
        
        if self.telegram:
            await self.telegram.send(
                f"*Remote PC Ready*\n\n"
                f"Click the link below to control your PC:\n"
                f"{tunnel_url}"
            )

    async def _run_webrtc_loop(self):
        while self._running:
            logger.info("Waiting for controller connection...")
            
            offer_sdp = await self.signaling.wait_for_offer(timeout=300.0)
            if not offer_sdp:
                logger.warning("No offer received, continuing to wait...")
                continue
            
            logger.info("Controller connected, creating WebRTC connection...")
            
            self.webrtc = WebRTCConnection(
                frame_queue=self.frame_queue,
                audio_capturer=self.audio_capturer,
                fps=self.capture_config["screen"]["fps"],
                sample_rate=self.capture_config["audio"]["sample_rate"],
                channels=self.capture_config["audio"]["channels"],
                max_bitrate=self.webrtc_config["max_bitrate"],
            )
            
            self.webrtc.set_ice_candidate_callback(self._on_ice_candidate)
            self.webrtc.set_connection_state_callback(self._on_connection_state_change)
            
            try:
                # Wait for offer from controller
                offer_sdp = await self.signaling.wait_for_offer(timeout=30.0)
                if not offer_sdp:
                    logger.warning("No offer received from controller")
                    continue
                
                logger.info("Received offer, creating answer...")
                # Set remote description (controller's offer) and create answer
                await self.webrtc.set_remote_description(offer_sdp, "offer")
                answer = await self.webrtc.create_answer()
                if answer is None:
                    logger.error("Failed to create answer")
                    continue
                
                await self.signaling.send_answer(answer.sdp)
                logger.info("Answer sent to controller")
                
                # Give time for answer to be processed
                await asyncio.sleep(0.5)
                
                logger.info("WebRTC connection established")
                
                while self.webrtc.pc and self.webrtc.pc.connectionState not in ("failed", "closed", "disconnected"):
                    ice_messages = self.signaling.get_pending_ice()
                    for msg in ice_messages:
                        logger.info(f"Processing ICE candidate: {msg.payload}")
                        await self.webrtc.add_ice_candidate(
                            msg.payload["candidate"],
                            msg.payload["sdpMid"],
                            msg.payload["sdpMLineIndex"]
                        )
                    await asyncio.sleep(0.1)
                
            except Exception as e:
                logger.error(f"WebRTC error: {e}")
            finally:
                if self.webrtc:
                    await self.webrtc.close()
                    self.webrtc = None
                
                logger.info("Controller disconnected, waiting for next connection...")

    async def _on_ice_candidate(self, candidate: str, sdp_mid: str, sdp_mline_index: int):
        if self.signaling:
            await self.signaling.send_ice_candidate(candidate, sdp_mid, sdp_mline_index)

    async def _on_connection_state_change(self, state: str):
        logger.info(f"Connection state: {state}")

    async def stop(self):
        self._running = False
        logger.info("Shutting down...")
        
        if self.webrtc:
            await self.webrtc.close()
        
        if self.screen_capturer:
            await self.screen_capturer.stop()
        
        if self.audio_capturer:
            await self.audio_capturer.stop()
        
        if self.tunnel:
            await self.tunnel.stop()
        
        if self.signaling:
            await self.signaling.stop()
        
        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        logger.info("Shutdown complete")


async def main():
    setup_logger()
    
    app = RemoteControlledApp()
    
    try:
        await app.start()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        raise
    finally:
        await app.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting...")