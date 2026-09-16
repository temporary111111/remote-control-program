import subprocess
import sys
from pathlib import Path

from utils.logger import logger


class AutoStart:
    TASK_NAME = "RemotePC"

    @classmethod
    def install(cls):
        if cls.is_installed():
            logger.info("Auto-start already configured")
            return

        exe_path = cls._get_exe_path()
        cmd = [
            "schtasks", "/create",
            "/tn", cls.TASK_NAME,
            "/tr", f'"{exe_path}"',
            "/sc", "onlogon",
            "/rl", "highest",
            "/f",
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                logger.info(f"Auto-start installed: {exe_path}")
            else:
                logger.error(f"Auto-start failed: {result.stderr}")
        except Exception as e:
            logger.error(f"Auto-start install error: {e}")

    @classmethod
    def uninstall(cls):
        cmd = ["schtasks", "/delete", "/tn", cls.TASK_NAME, "/f"]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                logger.info("Auto-start removed")
            else:
                logger.warning(f"Auto-start remove failed: {result.stderr}")
        except Exception as e:
            logger.error(f"Auto-start uninstall error: {e}")

    @classmethod
    def is_installed(cls) -> bool:
        cmd = ["schtasks", "/query", "/tn", cls.TASK_NAME]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.returncode == 0
        except Exception:
            return False

    @classmethod
    def _get_exe_path(cls) -> str:
        if getattr(sys, "frozen", False):
            return sys.executable
        return str(Path(__file__).parent.parent / "main.py")
