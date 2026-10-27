#!/bin/bash
# Installs the three background jobs as launchd user agents:
#   com.verbatim.ingest     -- every 5 min, picks up new files in data/audio/incoming/
#   com.verbatim.reminders  -- every 15 min, fires due reminders as notifications
#   com.verbatim.digest     -- once a day at 21:30, generates the day's digest
#
# Not run automatically -- run this yourself whenever you're ready to have
# these running in the background all the time, independent of any terminal
# or Claude session being open. Safe to re-run (unloads + reloads).
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
mkdir -p "$LAUNCH_AGENTS" "$PROJECT_DIR/data/logs"

for name in ingest reminders digest; do
    label="com.verbatim.$name"
    src="$PROJECT_DIR/scripts/launchd/$label.plist.template"
    dest="$LAUNCH_AGENTS/$label.plist"
    sed "s|__PROJECT_DIR__|$PROJECT_DIR|g" "$src" > "$dest"
    launchctl unload "$dest" 2>/dev/null || true
    launchctl load "$dest"
    echo "installed + loaded $label"
done

echo
echo "Logs land in $PROJECT_DIR/data/logs/"
echo "Uninstall any time with: scripts/uninstall_automation.sh"
