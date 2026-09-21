import asyncio
import os
import re
import sys
import tempfile
import subprocess
from pathlib import Path
from typing import Callable, Optional

from utils.logger import logger


class CloudflareTunnel:
    def __init__(self, local_port: int = 8080):
        self.local_port = local_port
        self.process: asyncio.subprocess.Process | None = None
        self.tunnel_url: str | None = None
        self._cloudflared_path: str | None = None
        self._on_url_change: Optional[Callable] = None
        self._monitor_task: Optional[asyncio.Task] = None
        self._stdout_task: Optional[asyncio.Task] = None
        self._stopping = False
        self._tunnel_unhealthy = False

    def set_url_change_callback(self, callback: Callable):
        self._on_url_change = callback

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
            creationflags=getattr(asyncio.subprocess, "CREATE_NO_WINDOW", 0x08000000),
        )

        url_pattern = re.compile(r"(https://[a-z0-9-]+\.trycloudflare\.com)")

        async for line_bytes in self.process.stdout:
            line = line_bytes.decode(errors="ignore").strip()
            if line:
                logger.debug(f"cloudflared: {line}")
                match = url_pattern.search(line)
                if match:
                    self.tunnel_url = match.group(1)
                    self._tunnel_unhealthy = False
                    logger.info(f"Tunnel ready: {self.tunnel_url}")
                    self._copy_to_clipboard(self.tunnel_url)
                    self._start_stdout_monitor()
                    return self.tunnel_url

        raise RuntimeError("cloudflared process ended without producing a tunnel URL")

    def _start_stdout_monitor(self):
        if self._stdout_task and not self._stdout_task.done():
            self._stdout_task.cancel()
        self._stdout_task = asyncio.ensure_future(self._monitor_stdout())

    async def _monitor_stdout(self):
        try:
            async for line_bytes in self.process.stdout:
                line = line_bytes.decode(errors="ignore").strip()
                if line:
                    logger.debug(f"cloudflared: {line}")
                    lower = line.lower()
                    if any(kw in lower for kw in ("error", "fail", "disconnect", "refused", "timeout", "fatal")):
                        logger.warning(f"cloudflared reported issue: {line}")
                        self._tunnel_unhealthy = True
            logger.warning("cloudflared stdout pipe closed")
            if self.process and self.process.returncode is None:
                self._tunnel_unhealthy = True
        except asyncio.CancelledError:
            pass

    async def _check_tunnel_health(self) -> bool:
        if not self.tunnel_url:
            return False
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.tunnel_url,
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    return resp.status == 200
        except Exception:
            return False

    async def _restart_tunnel(self, reason: str):
        logger.warning(f"Restarting tunnel: {reason}")
        self._tunnel_unhealthy = False
        if self._stdout_task and not self._stdout_task.done():
            self._stdout_task.cancel()
            try:
                await self._stdout_task
            except asyncio.CancelledError:
                pass
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
        try:
            new_url = await self.start()
            logger.info(f"Tunnel restarted: {new_url}")
            if self._on_url_change:
                await self._on_url_change(new_url)
        except Exception as e:
            logger.error(f"Failed to restart cloudflared: {e}")
            await asyncio.sleep(5)

    def _copy_to_clipboard(self, text: str):
        try:
            import pyperclip
            pyperclip.copy(text)
            logger.info("Tunnel URL copied to clipboard")
        except Exception as e:
            logger.warning(f"Could not copy to clipboard: {e}")

    async def stop(self):
        self._stopping = True
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        if self._stdout_task and not self._stdout_task.done():
            self._stdout_task.cancel()
            try:
                await self._stdout_task
            except asyncio.CancelledError:
                pass
        if self.process:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
            logger.info("Cloudflare tunnel stopped")

    async def monitor(self):
        self._stopping = False
        while not self._stopping:
            await asyncio.sleep(10)
            if self._stopping:
                break

            if self.process and self.process.returncode is not None:
                await self._restart_tunnel(
                    f"cloudflared exited (code {self.process.returncode})"
                )
                continue

            if self.tunnel_url and self._tunnel_unhealthy:
                await self._restart_tunnel("cloudflared reported errors")
                continue

            if self.tunnel_url:
                healthy = await self._check_tunnel_health()
                if not healthy:
                    await self._restart_tunnel("tunnel health check failed")
                    continue


async def start_tunnel(port: int = 8080) -> str:
    tunnel = CloudflareTunnel(port)
    return await tunnel.start()