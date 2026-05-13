# User Guide

## Install

1. Grab the latest `MonomePyBridge-<os>-<arch>.zip` from the
   [Releases](https://github.com/Trumanac/monomePyBridge/releases) page.
2. Unzip anywhere — `Documents`, `Applications`, `~/bin`, wherever.
3. Launch:
   - **Windows:** double-click `MonomePyBridge.exe`
   - **macOS:** double-click `MonomePyBridge.app` (you may need to right-click → *Open* the first time to bypass Gatekeeper, since the build is unsigned)
   - **Linux:** run `./MonomePyBridge` from the unzipped folder

No Python install required.

## First run

1. Plug your monome in **before or after** launching — both work, the
   bridge polls continuously.
2. The device shows up in the left-hand list with its serial (e.g.
   `m12345` or `40h-FT...`).
3. Click the device. The right pane shows:
   - Device info (model, protocol, size).
   - **OSC settings** — host, app port, prefix, rotation, intensity.
   - **Tilt** toggle (40h / 256 only).
   - **MIDI bridge** toggle + channel + base note.
   - **WebSocket bridge** toggle + port (0 = auto-allocate).
   - **Live test pad** — click cells to flash LEDs; physical key presses
     light up here.
4. Edit OSC host/port to match your app (default `127.0.0.1:8000`),
   click **Apply**, and your monome app should now see the grid.

Settings persist per device serial — re-plug the same grid and you get
the same prefix / port / toggles back automatically.

## Virtual grids

Use the **Virtual** tab to create on-screen grids for testing apps
without hardware:

1. Choose dimensions (8×8, 16×8, 16×16) and click **Add**.
2. A clickable on-screen grid appears in the right pane and is
   advertised over OSC like a real device.
3. Tick **Persistent virtual grid (auto-attach at startup)** in the
   device editor to make it come back next time you launch the app.

## Using with classic Max patches

| App | Settings |
| --- | -------- |
| **MLR / MLRV** (modern) | host `127.0.0.1`, port = whatever the patch listens on, prefix `/monome` |
| **Pre-serialosc apps** (e.g. original MLR 2.x) | Set the prefix to `/40h`, `/64`, `/128`, or `/256` to match the patch |
| **monome SDK / `monome-sdk`** | Use the discovery port shown in the GUI Status bar (default `12002`) |

## System tray

MonomePyBridge minimises to the tray. Right-click the icon for:

- **Show window** — restore the GUI
- **Quit** — fully exit (closing the window only hides it)

## Config files

Settings live in your OS's standard app-config directory:

| OS      | Path                                              |
| ------- | ------------------------------------------------- |
| Windows | `%APPDATA%\MonomePyBridge\`                        |
| macOS   | `~/Library/Application Support/MonomePyBridge/`    |
| Linux   | `~/.config/MonomePyBridge/`                        |

Files:

- `config.json` — global preferences (discovery port, log level, etc.)
- `devices.json` — per-device profiles keyed by serial
- `logs/` — rotating log files (use the **View Logs** button in the GUI)

Delete either JSON to reset.
