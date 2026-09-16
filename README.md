# Remote Desktop Controller

Web-based controller for the remote-controlled desktop streaming app.

## Usage

1. Run `remote-controlled.exe` on the target machine
2. Copy the tunnel URL shown in the console (e.g., `https://abc123.trycloudflare.com`)
3. Open this controller page
4. Paste the URL and click **Connect**

## Features

- Real-time screen streaming via WebRTC
- System audio + microphone streaming
- Full mouse/keyboard control
- Fullscreen mode
- Works in any modern browser (desktop & mobile)

## Deployment (GitHub Pages)

1. Create a new repository named `remote-controller`
2. Push these files to the `main` branch
3. Go to Settings → Pages
4. Source: "Deploy from a branch" → `main` → `/ (root)`
5. Access at `https://<username>.github.io/remote-controller/`

## Local Testing

```bash
# Python 3
python -m http.server 8080
# Then open http://localhost:8080
```

## Input Mapping

| Action | Desktop | Mobile |
|--------|---------|--------|
| Move mouse | Mouse move | Drag on screen |
| Left click | Left click | Tap |
| Right click | Right click | Long press |
| Scroll | Mouse wheel | Two-finger drag |
| Keyboard | Physical keyboard | On-screen keyboard |

## Browser Support

- Chrome/Edge 88+
- Firefox 85+
- Safari 14+
- Mobile Chrome/Safari

## Security

The tunnel URL is the only authentication. Anyone with the URL can connect and control the machine. Use only on trusted networks or with additional VPN/Tailscale.