#!/usr/bin/env bash
set -euo pipefail

APP_PATH="${1:-/Applications/MonomePyBridge.app}"
TS="$(date +%Y%m%d_%H%M%S)"
REPORT="$HOME/Desktop/MonomePyBridge_test_report_${TS}.txt"

log() {
  printf "%s\n" "$*" | tee -a "$REPORT"
}

section() {
  printf "\n===== %s =====\n" "$*" | tee -a "$REPORT"
}

run_capture() {
  local title="$1"
  shift
  section "$title"
  {
    printf "+ %s\n" "$*"
    "$@"
  } >>"$REPORT" 2>&1 || true
}

section "MonomePyBridge macOS Tester"
log "Report: $REPORT"
log "App path: $APP_PATH"

if [[ ! -d "$APP_PATH" ]]; then
  section "ERROR"
  log "App bundle not found at: $APP_PATH"
  log "Usage: bash macos_tester_script.sh /Applications/MonomePyBridge.app"
  exit 1
fi

run_capture "macOS version" sw_vers
run_capture "Initial quarantine flags" xattr -lr "$APP_PATH"

section "Step 1: Remove quarantine"
run_capture "Remove quarantine" xattr -dr com.apple.quarantine "$APP_PATH"
run_capture "Quarantine after removal" xattr -lr "$APP_PATH"

section "Step 2: Ad-hoc sign (local workaround)"
run_capture "Ad-hoc sign" codesign --force --deep --sign - "$APP_PATH"

section "Step 3: Launch app"
run_capture "open app" open "$APP_PATH"
sleep 3

if pgrep -f "MonomePyBridge" >/dev/null 2>&1; then
  log "Process check: MonomePyBridge appears to be running."
else
  log "Process check: app process not detected yet."
fi

section "Step 4: Gatekeeper / signature diagnostics"
run_capture "spctl assessment" spctl --assess --verbose=4 "$APP_PATH"
run_capture "codesign details" codesign -dv --verbose=4 "$APP_PATH"

section "Manual checklist for tester"
log "1. If macOS warns the app is blocked, use Finder: right-click app -> Open -> Open."
log "2. If still blocked, go to System Settings -> Privacy and Security -> Open Anyway."
log "3. Confirm app window appears."
log "4. Connect a device and confirm it appears in device list."
log "5. Open WebSocket Demo from app and confirm page opens."
log "6. Toggle MIDI bridge and confirm expected MIDI device behavior."
log "7. Quit app from menu and confirm it exits."

section "What to send back"
log "Send this report file: $REPORT"
log "Also include screenshots of any popup errors or Privacy and Security messages."

section "Done"
log "Tester script completed."
