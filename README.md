# MonomePyBridge

[![ci](https://github.com/Trumanac/monomePyBridge/actions/workflows/ci.yml/badge.svg)](https://github.com/Trumanac/monomePyBridge/actions/workflows/ci.yml)
[![release](https://github.com/Trumanac/monomePyBridge/actions/workflows/release.yml/badge.svg?event=push)](https://github.com/Trumanac/monomePyBridge/actions/workflows/release.yml)

A modern, cross-platform standalone bridge for [monome](https://monome.org/) grid controllers — a drop-in replacement for the legacy `monomeserial` software, with full `serialosc` compatibility so existing Max/MSP patches (MLR, MLRV, Re:mix, Polygomé, etc.) and any serialosc-aware app work unchanged.

> **Status:** early alpha — under active development.

## Documentation

- [User guide](docs/USER_GUIDE.md) — install, first run, virtual grids, config files
- [OSC / WebSocket / MIDI protocol](docs/OSC_PROTOCOL.md) — every message the bridge speaks
- [Troubleshooting](docs/TROUBLESHOOTING.md) — driver / firewall / loopMIDI / Gatekeeper

## Why this exists

The original [`monomeserial`](https://github.com/monome/monomeserial) was discontinued ~2011 and no longer builds on modern Windows / macOS / Linux. Its successor, `serialosc`, dropped support for the original 40h-protocol kit grids (m40h, black-rubber 64). MonomePyBridge brings *every* monome grid — from the original 2007 kits through to current production hardware — back online on modern systems, with one app, one UI, and zero setup.

## Features

- **Universal device support** — 40h kit, series (64/128/256), mext (current production), auto-detected.
- **serialosc-compatible OSC** — apps and Max patches that already work with serialosc see MonomePyBridge as if it *were* serialosc.
- **Legacy monomeserial mode** — fixed `/40h`, `/64`, `/128`, `/256` prefixes for old apps.
- **Cross-platform** — Windows, macOS, Linux. Single download, ready to run.
- **Modern GUI** — device list, live LED test, button press visualizer, tilt meters, log viewer, system tray.
- **Multiple devices simultaneously** — each gets its own OSC port + persistent prefix.
- **Tilt / ADC support** for 40h and 256 hardware.
- **MIDI bridge** — use any monome grid as a MIDI controller.
- **WebSocket bridge** — JSON protocol for browser-based grid apps.
- **Per-device config** persisted by serial number.

## Quickstart (end users)

1. Download the latest `.zip` for your OS from [Releases](https://github.com/Trumanac/monomePyBridge/releases).
2. Unzip anywhere.
3. Run `MonomePyBridge` (Windows: `.exe`; macOS: `.app`; Linux: binary).
4. Plug in your monome — it appears in the device list automatically.

No Python install required. Everything is bundled.

### FTDI driver note (40h / older grids only)

Original 40h kit grids use an FTDI USB-serial chip. Most modern OSes ship the driver, but if your device isn't detected:

- **Windows:** [FTDI VCP driver](https://ftdichip.com/drivers/vcp-drivers/)
- **macOS:** built-in (no install needed on 10.9+)
- **Linux:** built-in (`ftdi_sio` kernel module)

## Development

```pwsh
git clone https://github.com/Trumanac/monomePyBridge.git
cd monomePyBridge
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1   # Windows
# source .venv/bin/activate    # macOS / Linux
pip install -e ".[dev]"
python -m monomepybridge
```

### Run the tests

```pwsh
$env:QT_QPA_PLATFORM = "offscreen"
pytest tests/ -v
python scripts/gui_smoke.py
```

### Build a standalone bundle

```pwsh
pip install -e ".[dev]"      # includes pyinstaller
python scripts/build.py
```

Output: `dist/MonomePyBridge-<os>-<arch>.zip` plus the runnable
`dist/MonomePyBridge/` folder (or `MonomePyBridge.app` on macOS).

### Cutting a release

Push a tag of the form `vX.Y.Z`. The `release` GitHub Action builds
Windows / macOS / Linux bundles in parallel and attaches them to a new
GitHub Release automatically.

```bash
git tag v0.1.0
git push --tags
```

## License

MIT with [Commons Clause](https://commonsclause.com/) — free for personal, hobby, educational, and creative use; commercial resale prohibited. See [LICENSE](LICENSE).

## Credits

- The [monome](https://monome.org/) community.
- Original `monomeserial` and `libmonome` authors.
- Born from the [MLRVP](https://github.com/Trumanac/MLRVP) project where the 40h direct-protocol driver was first reverse-engineered for modern Windows.
