"""Bridge layer — device abstraction + driver factory."""

from .base import (
    Device,
    DeviceCallbacks,
    DeviceInfo,
    DeviceProtocol,
    DisconnectCallback,
    KeyCallback,
    TiltCallback,
    lookup_dimensions,
)
from .factory import build_device

__all__ = [
    "Device",
    "DeviceCallbacks",
    "DeviceInfo",
    "DeviceProtocol",
    "DisconnectCallback",
    "KeyCallback",
    "TiltCallback",
    "build_device",
    "lookup_dimensions",
]
