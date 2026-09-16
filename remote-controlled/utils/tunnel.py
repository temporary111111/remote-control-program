import asyncio
import os
import re
import sys
import tempfile
import subprocess
from pathlib import Path

from utils.logger import logger


class CloudflareTunnel:
    def __init__(self, local_port: int = 8080):
        self.local_port = local_port
        self.process: asyncio.subprocess.Process | None = None
        self.tunnel_url: str | None = None
        self._cloudflared_path: str | None = None

    def _get_cloudflared_path(self) -> str:
        if self._cloudflared_path and os.path.exists(self._cloudflared_path):
            return self._cloudflared_path

        if getattr(sys, "frozen", False):
            base_path = sys._MEIPASS
        else:
            base_path = Path(__file__).parent.parent

        src = Path(base_path) / "cloudflared.exe"
        dst = Path(tempfile.gettempdir()) / "cloudflared.exe"

        if not dst.exists() and src.exists():
            try:
                with open(src, "rb") as f_in:
                    with open(dst, "wb") as f_out:
                        f_out.write(f_in.read())
                logger.info(f"Extracted cloudflared to {dst}")
            except Exception as e:
                logger.error(f"Failed to extract cloudflared: {e}")
                raise

        if not dst.exists():
            raise FileNotFoundError("cloudflared.exe not found. Place it in the project root.")

        self._cloudflared_path = str(dst)
        return self._cloudflared_path

    async def start(self) -> str:
        cloudflared = self._get_cloudflared_path()
        
        logger.info(f"Starting cloudflared tunnel on port {self.local_port}...")
        
        self.process = await asyncio.create_subprocess_exec(
            cloudflared,
            "tunnel",
            "--url",
            f"http://localhost:{self.local_port}",
            "--no-autoupdate",
            "--protocol",
            "http2",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        url_pattern = re.compile(r"(https://[a-z0-9-]+\.trycloudflare\.com)")
        
        async for line_bytes in self.process.stdout:
            line = line_bytes.decode(errors="ignore").strip()
            if line:
                logger.debug(f"cloudflared: {line}")
                match = url_pattern.search(line)
                if match:
                    self.tunnel_url = match.group(1)
                    logger.info(f"Tunnel ready: {self.tunnel_url}")
                    self._copy_to_clipboard(self.tunnel_url)
                    return self.tunnel_url

        raise RuntimeError("cloudflared process ended without producing a tunnel URL")

    def _copy_to_clipboard(self, text: str):
        try:
            import pyperclip
            pyperclip.copy(text)
            logger.info("Tunnel URL copied to clipboard")
        except Exception as e:
            logger.warning(f"Could not copy to clipboard: {e}")

    async def stop(self):
        if self.process:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
            logger.info("Cloudflare tunnel stopped")


async def start_tunnel(port: int = 8080) -> str:
    tunnel = CloudflareTunnel(port)
    return await tunnel.start()