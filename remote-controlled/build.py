import PyInstaller.__main__
import shutil
from pathlib import Path

BUILD_DIR = Path("dist")
CLOUDFLARED = Path("cloudflared.exe")

COMMON_ARGS = [
    "main.py",
    "--onefile",
    "--add-data", "config.yaml;.",
    "--add-data", "assets;assets",
]

if CLOUDFLARED.exists():
    COMMON_ARGS.extend(["--add-data", "cloudflared.exe;."])
    print(f"Bundling cloudflared.exe ({CLOUDFLARED.stat().st_size // 1024 // 1024}MB)")
else:
    print("WARNING: cloudflared.exe not found, will not be bundled")

HIDDEN_IMPORTS = [
    "--hidden-import", "sounddevice",
    "--hidden-import", "soundfile",
    "--collect-all", "av",
    "--collect-all", "aiortc",
    "--collect-all", "mss",
    "--collect-all", "pynput",
]

def build(name: str, windowed: bool = False):
    args = [
        *COMMON_ARGS,
        "--name", name,
        *HIDDEN_IMPORTS,
        "--clean",
    ]
    if windowed:
        args.append("--windowed")
        print(f"\nBuilding {name}.exe (silent/no terminal)...")
    else:
        args.append("--console")
        print(f"\nBuilding {name}.exe (with terminal)...")

    PyInstaller.__main__.run(args)
    print(f"Built: {BUILD_DIR / f'{name}.exe'}")

if __name__ == "__main__":
    BUILD_DIR.mkdir(exist_ok=True)

    build("RemotePC", windowed=False)
    build("RemotePC-Silent", windowed=True)

    print(f"\nDone! Files in {BUILD_DIR}/")
