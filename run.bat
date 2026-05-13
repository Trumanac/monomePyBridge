@echo off
REM MonomePyBridge launcher (Windows, dev mode using local .venv)
setlocal
pushd "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m monomepybridge %*
) else (
    echo .venv not found. Run setup first:
    echo     py -3.11 -m venv .venv
    echo     .venv\Scripts\activate
    echo     pip install -e .[dev]
    exit /b 1
)
popd
endlocal
