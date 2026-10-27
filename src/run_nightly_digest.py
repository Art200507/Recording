"""Zero-argument wrapper so a scheduler (launchd/cron) can run the digest
for "today" without any argument wrangling. See src/digest.py for the
actual logic.
"""

import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import store
import digest


def main():
    date_str = datetime.date.today().isoformat()
    conn = store.get_conn()
    data = digest.generate(conn, date_str)
    if data:
        digest.print_digest(date_str, data)


if __name__ == "__main__":
    main()
