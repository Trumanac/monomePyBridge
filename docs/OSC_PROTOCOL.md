# OSC Protocol

MonomePyBridge speaks the **serialosc** wire protocol, so apps written for
serialosc / Max-monome externals work unchanged. Each connected device
gets its own UDP port on the bridge; the bridge forwards to your app on
the host/port you tell it via `/sys/port` and `/sys/host`.

## Discovery (serialoscd compatible)

| Message                                      | Direction | Notes                                        |
| -------------------------------------------- | --------- | -------------------------------------------- |
| `/serialosc/list <host:str> <port:int>`      | app → bridge | Reply: one `/serialosc/device <id> <type> <port>` per device |
| `/serialosc/notify <host:str> <port:int>`    | app → bridge | Subscribe to add/remove notifications (one-shot) |
| `/serialosc/add <id:str>`                    | bridge → app | Sent when a device is plugged in              |
| `/serialosc/remove <id:str>`                 | bridge → app | Sent when a device is unplugged               |

Default discovery port: **12002**.

## /sys (per-device)

Sent to the device's own UDP port (shown in the GUI). The device
echoes status back to the host/port you've configured.

| Message                                | Notes                                        |
| -------------------------------------- | -------------------------------------------- |
| `/sys/port <int>`                      | Set destination UDP port for outbound events |
| `/sys/host <str>`                      | Set destination host                         |
| `/sys/prefix <str>`                    | Change OSC prefix (default `/monome`)        |
| `/sys/rotation <0\|90\|180\|270>`      | Rotate the grid                              |
| `/sys/info` or `/sys/info <host> <port>` | Triggers `/sys/{id,size,host,port,prefix,rotation}` reply burst |

## `<prefix>/grid/led/...` (app → bridge)

| Message                                           | Notes                              |
| ------------------------------------------------- | ---------------------------------- |
| `/grid/led/set x y s`                             | Single LED on/off (`s` = 0 or 1)   |
| `/grid/led/all s`                                 | All LEDs on/off                    |
| `/grid/led/map x_off y_off m0..m7`                | 8×8 quadrant, 8 row bitmasks       |
| `/grid/led/row x_off y mask [mask...]`            | Whole row (multi-quadrant grids)   |
| `/grid/led/col x y_off mask [mask...]`            | Whole column                       |
| `/grid/led/intensity i`                           | Global intensity 0–15              |
| `/grid/led/level/set x y l`                       | LED level 0–15                     |
| `/grid/led/level/all l`                           | All LEDs to level                  |
| `/grid/led/level/map x_off y_off l0..l63`         | 8×8 quadrant, per-cell levels      |
| `/grid/led/level/row x_off y l0 l1 ...`           | Row of levels                      |
| `/grid/led/level/col x y_off l0 l1 ...`           | Column of levels                   |

## `<prefix>/grid/...` (bridge → app)

| Message                  | Notes                                   |
| ------------------------ | --------------------------------------- |
| `/grid/key x y s`        | Key event (`s` = 1 press, 0 release)    |
| `/grid/tilt n x y z`     | Tilt sensor `n` (when enabled)          |

## Legacy `monomeserial` mode

For pre-serialosc apps, set the prefix to one of `/40h`, `/64`, `/128`, `/256`.
The bridge then accepts the legacy address layout (no `/grid` infix):

```
/64/led x y s
/64/led_row x_off y mask
/64/led_col x y_off mask
/64/clear s
/64/intensity i
```

…and emits `/64/press x y s` on key events, etc.

## WebSocket bridge (modern alternative)

Per-device toggle in the GUI. JSON messages over a single WebSocket
endpoint; coordinates and levels mirror the OSC layer.

Outbound (bridge → client):

```json
{"type":"hello","id":"m12345","type_name":"monome 128","width":16,"height":8}
{"type":"key","x":3,"y":2,"s":1}
{"type":"tilt","n":0,"x":127,"y":128,"z":129}
```

Inbound (client → bridge):

```json
{"type":"led_set","x":3,"y":2,"level":15}
{"type":"led_all","level":0}
{"type":"led_row","x_off":0,"y":0,"mask":255}
{"type":"led_col","x":0,"y_off":0,"mask":255}
{"type":"intensity","level":12}
```

## MIDI bridge (modern alternative)

Per-device toggle in the GUI. Note number `n = base + y * width + x`
(default `base = 36` = C2). Channel is configurable per device.

| Direction       | MIDI                                | Bridge effect                   |
| --------------- | ----------------------------------- | ------------------------------- |
| grid → MIDI out | Note On vel 100 / Note Off          | key press / release             |
| MIDI in → grid  | Note On vel `v>0`                   | `led_set(x, y, round(v*15/127))` |
| MIDI in → grid  | Note Off / Note On vel 0            | `led_set(x, y, 0)`              |

On Linux/macOS MonomePyBridge creates **virtual** MIDI ports named
`MonomePyBridge <serial>` automatically. On Windows, install
[loopMIDI](https://www.tobias-erichsen.de/software/loopmidi.html) and
the bridge will use the first available port.
