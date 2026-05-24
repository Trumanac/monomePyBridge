#!/usr/bin/env bash
set -euo pipefail

APP_PATH="${1:-/Applications/MonomePyBridge.app}"

osascript -e 'display notification "Preparing MonomePyBridge..." with title "MonomePyBridge"' || true

if [[ ! -d "$APP_PATH" ]]; then
  osascript -e 'display dialog "MonomePyBridge.app was not found in /Applications.\n\nMove the app to /Applications, then run this again." buttons {"OK"} default button "OK" with title "MonomePyBridge"'
  exit 1
fi

# Remove quarantine attributes that cause Gatekeeper block dialogs.
xattr -dr com.apple.quarantine "$APP_PATH" || true

# Local ad-hoc sign can help with stricter "app is damaged" checks.
codesign --force --deep --sign - "$APP_PATH" >/dev/null 2>&1 || true

# Attempt launch.
open "$APP_PATH"

# Friendly instructions if user still sees a block dialog.
osascript -e 'display dialog "If macOS still blocks launch:\n\n1) In Finder, right-click MonomePyBridge.app -> Open\n2) Click Open\n3) If needed: System Settings -> Privacy & Security -> Open Anyway\n\nAfter this first run, normal launches should work." buttons {"OK"} default button "OK" with title "MonomePyBridge"'
