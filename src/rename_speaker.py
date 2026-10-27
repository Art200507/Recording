"""Attach a real name to a diarized speaker label.

Usage:
    python src/rename_speaker.py SPEAKER_00 "Mom"
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import store


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("label")
    ap.add_argument("display_name")
    args = ap.parse_args()

    conn = store.get_conn()
    store.get_or_create_speaker(conn, args.label)
    store.rename_speaker(conn, args.label, args.display_name)
    print(f"{args.label} -> {args.display_name}")


if __name__ == "__main__":
    main()
