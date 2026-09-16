import sys
import shutil
from pathlib import Path

from utils.logger import logger

try:
    import winreg
except ImportError:
    winreg = None


class AutoStart:
    REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
    APP_NAME = "RemotePC"

    @classmethod
    def install(cls):
        if cls.is_installed():
            logger.info("Auto-start already configured")
            return

        exe_path = cls._get_exe_path()
        if not exe_path:
            logger.error("Could not determine exe path for auto-start")
            return

        if winreg is None:
            logger.error("winreg not available")
            return

        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, cls.REG_KEY, 0, winreg.KEY_SET_VALUE)
            winreg.SetValueEx(key, cls.APP_NAME, 0, winreg.REG_SZ, f'"{exe_path}"')
            winreg.CloseKey(key)
            logger.info(f"Auto-start installed: {exe_path}")
        except Exception as e:
            logger.error(f"Auto-start install error: {e}")

    @classmethod
    def uninstall(cls):
        if winreg is None:
            return
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, cls.REG_KEY, 0, winreg.KEY_SET_VALUE)
            winreg.DeleteValue(key, cls.APP_NAME)
            winreg.CloseKey(key)
            logger.info("Auto-start removed")
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.error(f"Auto-start uninstall error: {e}")

    @classmethod
    def is_installed(cls) -> bool:
        if winreg is None:
            return False
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, cls.REG_KEY, 0, winreg.KEY_READ)
            winreg.QueryValueEx(key, cls.APP_NAME)
            winreg.CloseKey(key)
            return True
        except FileNotFoundError:
            return False
        except Exception:
            return False

    @classmethod
    def _get_exe_path(cls) -> str | None:
        if getattr(sys, "frozen", False):
            src = Path(sys.executable)
            dest_dir = Path.home() / "AppData" / "Local" / "RemotePC"
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / src.name

            if dest.resolve() != src.resolve():
                try:
                    shutil.copy2(src, dest)
                    logger.info(f"Copied exe to stable path: {dest}")
                except Exception as e:
                    logger.error(f"Failed to copy exe: {e}")
                    return str(src)

            return str(dest)

        logger.warning("Auto-start only works from built .exe")
        return None
