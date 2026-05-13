# Troubleshooting

## My monome doesn't appear in the device list

1. **Check the cable.** Original 40h kits are notorious for flaky USB
   cables — try another one.
2. **Driver (40h / older grids only):** install the FTDI VCP driver.
   - Windows: <https://ftdichip.com/drivers/vcp-drivers/>
   - macOS: built-in since 10.9
   - Linux: built-in (`ftdi_sio` kernel module)
3. **Linux permissions:** add yourself to the `dialout` group, then
   log out and back in:

   ```bash
   sudo usermod -aG dialout $USER
   ```

4. **macOS permissions:** allow MonomePyBridge under
   *System Settings → Privacy & Security → Input Monitoring*.
5. Check the **Logs** view (button in the bottom toolbar) — discovery
   errors get logged at INFO/WARN level.

## App connects to the bridge but no LEDs light up

- Verify the **prefix** matches what your app sends. Modern apps use
  `/monome`; old MLR 2.x uses `/64` or `/128`.
- Verify the **OSC port** in the GUI matches the port your app sends
  *to*. The bridge listens on the per-device port shown in the panel.
- Click the **Live test** cells in the GUI — if those work, the bridge
  ↔ device link is fine and the issue is on the OSC side.

## Key presses don't reach my app

- Verify **`/sys/host`** and **`/sys/port`** point at your app. Many
  apps set these on launch automatically; some require manual setup.
- Check the **firewall**: on Windows, the first launch should prompt
  to allow MonomePyBridge through Windows Defender Firewall. Allow
  both **Private** and **Public** if you're unsure.

## MIDI bridge does nothing on Windows

Windows has no built-in virtual MIDI driver. Install
[**loopMIDI**](https://www.tobias-erichsen.de/software/loopmidi.html),
create a port called e.g. *MonomePyBridge*, then toggle the MIDI
bridge in the device panel. The bridge will grab the first available
port. macOS has built-in **IAC** (enable in *Audio MIDI Setup → MIDI
Studio*); Linux has ALSA virtual ports automatically.

## WebSocket bridge: "connection refused"

- Confirm the toggle is **on** in the device panel; the status line
  should read `WebSocket: ws://localhost:<port>`.
- Some browsers refuse `ws://` from `https://` pages — host your test
  page over plain `http://` or `file://` for local testing.
- If using a fixed port, make sure nothing else is on it.

## "App.app is damaged and can't be opened" (macOS)

The bundle isn't notarised yet. Bypass once with:

```bash
xattr -dr com.apple.quarantine /path/to/MonomePyBridge.app
```

## Reset to a clean state

Quit MonomePyBridge, then delete the config directory (see
[USER_GUIDE.md](USER_GUIDE.md#config-files)). Next launch will recreate
defaults.

## Reporting a bug

Open an issue at <https://github.com/Trumanac/monomePyBridge/issues>
with:

- OS + version
- MonomePyBridge version (top of the GUI window title)
- Device model + serial (the GUI shows both)
- Relevant excerpt from the **Logs** view
- Steps to reproduce
