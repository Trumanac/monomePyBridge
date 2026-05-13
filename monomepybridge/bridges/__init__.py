"""Modern bonus features: MIDI bridge, WebSocket bridge, etc.

Each bridge is a per-device adapter that lives alongside the OSC server
and translates the device's events into a different transport. They are
optional — toggled per device via the GUI / profile.
"""
