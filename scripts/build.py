"""
Local one-shot build script.

Cleans previous artifacts, runs PyInstaller, and zips the result.
Usage (from repo root):

    python scripts/build.py

Output:

    dist/MonomePyBridge/                -- runnable folder
    dist/MonomePyBridge-<os>-<arch>.zip -- distributable archive
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "packaging" / "MonomePyBridge.spec"
DIST = ROOT / "dist"
BUILD = ROOT / "build"


def _os_tag() -> str:
    sysname = platform.system().lower()
    arch = platform.machine().lower()
    if sysname == "darwin":
        sysname = "macos"
    return f"{sysname}-{arch}"


def _clean() -> None:
    for p in (DIST, BUILD):
        if p.exists():
            print(f"[clean] removing {p}")
            shutil.rmtree(p, ignore_errors=True)


def _run_pyinstaller() -> None:
    cmd = [sys.executable, "-m", "PyInstaller", str(SPEC), "--noconfirm", "--clean"]
    print("[build]", " ".join(cmd))
    subprocess.check_call(cmd, cwd=str(ROOT))


def _zip_dist() -> Path:
    folder = DIST / "MonomePyBridge"
    if not folder.exists():
        # macOS .app may be the output instead.
        app = DIST / "MonomePyBridge.app"
        if app.exists():
            folder = app
        else:
            raise SystemExit(f"build artifact not found under {DIST}")
    out = DIST / f"MonomePyBridge-{_os_tag()}.zip"
    print(f"[zip] {out}")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in folder.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(DIST))
    return out


def main() -> int:
    _clean()
    _run_pyinstaller()
    out = _zip_dist()
    print(f"\n[done] {out}  ({out.stat().st_size / (1024 * 1024):.1f} MiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
