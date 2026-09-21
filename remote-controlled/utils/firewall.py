import subprocess
import sys
from pathlib import Path

from utils.logger import logger


class Firewall:
    RULE_NAME = "RemotePC Server"

    @classmethod
    def ensure_rule(cls):
        if getattr(sys, "frozen", False):
            exe_path = str(Path(sys.executable).resolve())
        else:
            return

        if cls._rule_exists():
            return

        try:
            result = subprocess.run(
                [
                    "netsh", "advfirewall", "firewall", "add", "rule",
                    f"name={cls.RULE_NAME}",
                    "dir=in",
                    "action=allow",
                    f"program={exe_path}",
                    "enable=yes",
                    "profile=private",
                ],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if result.returncode == 0:
                logger.info("Firewall rule added successfully")
            else:
                logger.warning(f"Firewall rule add failed (needs admin): {result.stderr.strip()}")
        except Exception as e:
            logger.warning(f"Could not add firewall rule: {e}")

    @classmethod
    def _rule_exists(cls) -> bool:
        try:
            result = subprocess.run(
                ["netsh", "advfirewall", "firewall", "show", "rule", f"name={cls.RULE_NAME}"],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return cls.RULE_NAME in result.stdout
        except Exception:
            return False
