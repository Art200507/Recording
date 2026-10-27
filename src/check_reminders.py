"""Fire any action-item reminders that are now due, as a macOS notification.

Meant to be run on a schedule (every ~15 min is plenty -- these are
day-granularity reminders, not alarms). See scripts/launchd/ for a template
that runs this automatically without Claude or a terminal open.

Usage:
    python src/check_reminders.py
"""

import datetime
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import store


def notify(title, message):
    script = f'display notification {message!r} with title {title!r} sound name "Ping"'
    subprocess.run(["osascript", "-e", script], check=False)


def main():
    conn = store.get_conn()
    now_iso = datetime.datetime.now().astimezone().isoformat()
    due = store.due_action_items(conn, now_iso)
    if not due:
        print("[check_reminders] nothing due")
        return

    for item in due:
        notify("Verbatim reminder", item["text"])
        store.mark_action_item(conn, item["id"], "notified")
        print(f"[check_reminders] fired: {item['text']}")


if __name__ == "__main__":
    main()
