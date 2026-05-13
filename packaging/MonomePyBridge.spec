# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for MonomePyBridge.

Produces a one-folder bundle (``dist/MonomePyBridge/``) containing the
GUI executable plus all dependencies. Cross-platform: same spec runs on
Windows, macOS, and Linux. CI zips the dist folder per OS.

Build locally:

    pyinstaller packaging/MonomePyBridge.spec --noconfirm --clean
"""

from __future__ import annotations

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# ── repo root (spec files run from the repo root) ──────────────────────
ROOT = Path(SPECPATH).resolve().parent  # noqa: F821 -- SPECPATH provided by PyInstaller
PKG = ROOT / "monomepybridge"

# ── implicit imports PyInstaller can miss ──────────────────────────────
hiddenimports: list[str] = []
hiddenimports += collect_submodules("monomepybridge")
hiddenimports += [
    "pyserial",
    "serial",
    "serial.tools",
    "serial.tools.list_ports",
    "rtmidi",
    "websockets",
    "websockets.legacy",
    "websockets.legacy.server",
    "websockets.asyncio",
    "websockets.asyncio.server",
    "pythonosc",
    "pythonosc.osc_server",
    "pythonosc.dispatcher",
    "pythonosc.udp_client",
    "pythonosc.osc_message_builder",
    "platformdirs",
    "pystray",
    "PIL",
    "PIL.Image",
]

datas = []
# Bundle our resources/ folder (icons, etc.).
datas += collect_data_files("monomepybridge", includes=["resources/*", "resources/**/*"])

block_cipher = None

a = Analysis(
    [str(PKG / "__main__.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Trim things we don't ship.
        "tkinter",
        "test",
        "unittest",
        "pytest",
        "pytest_qt",
        "pytest_asyncio",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtQuick3D",
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
        "PySide6.QtPdf",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtBluetooth",
        "PySide6.QtNfc",
        "PySide6.QtPositioning",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Show a console window only on Windows when explicitly debugging.
_is_windows = sys.platform.startswith("win")
_is_macos = sys.platform == "darwin"

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MonomePyBridge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="MonomePyBridge",
)

# ── macOS: also produce a proper .app bundle ───────────────────────────
if _is_macos:
    app = BUNDLE(
        coll,
        name="MonomePyBridge.app",
        icon=None,
        bundle_identifier="org.trumanac.monomepybridge",
        info_plist={
            "CFBundleName": "MonomePyBridge",
            "CFBundleDisplayName": "MonomePyBridge",
            "CFBundleShortVersionString": "0.6.9.0",
            "CFBundleVersion": "0.6.9.0",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "10.15",
            "NSMicrophoneUsageDescription": "Not used.",
        },
    )
