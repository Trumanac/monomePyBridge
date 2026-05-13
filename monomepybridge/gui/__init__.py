"""PySide6 GUI (Phase 3).

The GUI is optional — the daemon runs perfectly headless. Importing
this module pulls in PySide6, so callers should defer the import until
they actually need a GUI.
"""

from .app import run_gui

__all__ = ["run_gui"]
