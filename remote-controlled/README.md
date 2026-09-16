# Remote Controlled - Desktop Streaming Server

Runs on the **controlled machine** (the one you want to access remotely). Captures screen, audio, and microphone, exposes via Cloudflare Tunnel, and accepts WebRTC connections from the controller.

## Features

- **Screen capture** (30fps, with cursor overlay)
- **System audio + microphone** streaming (48kHz, stereo)
- **Full input control** (mouse, keyboard, scroll)
- **Zero-config networking** via Cloudflare Tunnel (auto-starts, copies URL to clipboard)
- **Single .exe distribution** (no dependencies, no VC++ redist needed)
- **WebRTC** for low-latency streaming to any browser

## Quick Start

### Run from Source (Development)

```bash
pip install -r requirements.txt
python main.py
```

### Build Single .exe

```bash
pip install pyinstaller
pyinstaller remote-controlled.spec
# Output: dist/remote-controlled.exe
```

### Run the .exe

1. Copy `dist/remote-controlled.exe` to target machine
2. Double-click to run
3. Console shows: `Tunnel ready: https://xxx.trycloudflare.com` (auto-copied to clipboard)
4. Open controller page → paste URL → Connect

## Architecture

```
┌─────────────────┐     Cloudflare Tunnel      ┌──────────────────┐
│  Controlled     │◄──────────────────────────►│  Controller      │
│  (this app)     │   HTTPS / WSS              │  (browser)       │
│                 │                             │                  │
│ • Screen (mss)  │  WebRTC: VP8 + Opus         │ • Video playback │
│ • Audio (WASAPI)│  DataChannel: JSON input    │ • Input capture  │
│ • Input (pynput)│                             │                  │
└─────────────────┘                             └──────────────────┘
```

## Project Structure

```
remote-controlled/
├── main.py                 # Entry point
├── config.yaml             # Configuration
├── requirements.txt        # Python deps
├── remote-controlled.spec  # PyInstaller spec
├── cloudflared.exe         # Bundled tunnel binary
├── assets/
│   └── cursor.png          # Cursor overlay
├── signaling/
│   ├── server.py           # aiohttp WebSocket + REST
│   └── protocol.py         # Message types
├── webrtc/
│   ├── connection.py       # RTCPeerConnection wrapper
│   ├── video_track.py      # Screen → VideoStreamTrack
│   └── audio_track.py      # Audio → AudioStreamTrack
├── capture/
│   ├── screen.py           # mss capture + cursor draw
│   ├── audio.py            # sounddevice (loopback + mic)
│   └── input.py            # pynput injection
└── utils/
    ├── tunnel.py           # cloudflared subprocess
    └── logger.py
```

## Configuration (`config.yaml`)

```yaml
server:
  port: 8080
  signaling_path: /ws

capture:
  screen:
    monitor: 1        # 1 = primary
    fps: 30
  audio:
    sample_rate: 48000
    channels: 2
    include_system: true
    include_mic: true

webrtc:
  video_codec: VP8
  audio_codec: opus
  max_bitrate: 5000000  # 5 Mbps
```

## Requirements

- Windows 10/11 (tested)
- Python 3.10+ (for building)
- Microphone access permission (first run)
- Stereo Mix / Loopback enabled in Sound settings (for system audio)

## Distribution Notes

- **No VC++ Redistributable required** - uses pure Python `mss` for screen capture
- **cloudflared.exe bundled** - extracts to temp, runs automatically
- **~80MB single .exe** - includes Python runtime + all deps
- **Code signing recommended** - avoids SmartScreen warnings

## Security

⚠️ **No authentication** - anyone with the tunnel URL has full control.  
Mitigations:
- URL is long, random, HTTPS-only
- Tunnel dies when .exe closes
- Console shows connection status
- For production: add PIN, use Tailscale, or VPN

## Troubleshooting

| Issue | Fix |
|-------|-----|
| No system audio | Enable "Stereo Mix" in Sound Control Panel → Recording |
| Mic not working | Allow microphone permission in Windows Settings |
| Tunnel fails | Check firewall, try `cloudflared.exe tunnel --url http://localhost:8080` manually |
| High CPU | Lower `fps` or `max_bitrate` in config.yaml |
| Cursor not visible | Ensure `assets/cursor.png` exists in .exe |

## Controller

See [`remote-controller`](../remote-controller) repo for the browser-based controller. Deploy to GitHub Pages for free hosting.

## License

MIT