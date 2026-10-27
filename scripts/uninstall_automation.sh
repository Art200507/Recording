#!/bin/bash
set -euo pipefail
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"

for name in ingest reminders digest; do
    label="com.verbatim.$name"
    dest="$LAUNCH_AGENTS/$label.plist"
    if [ -f "$dest" ]; then
        launchctl unload "$dest" 2>/dev/null || true
        rm "$dest"
        echo "removed $label"
    fi
done
