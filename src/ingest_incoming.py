"""Process every new file sitting in data/audio/incoming/.

This is the hand-off point for whatever hardware recorder ends up feeding
this pipeline. Once that device exists, point its export/sync target --
SD card copy, Bluetooth file transfer, a synced folder, whatever it turns
out to be -- at data/audio/incoming/, and this picks files up from there.
Hardware-agnostic on purpose: anything ffmpeg/whisper can decode works, so
nothing about the pipeline needs to change once the actual device shows up.

Successfully ingested files move to data/audio/processed/ (timestamped, so
re-running never collides); files that error out move to data/audio/failed/
with a .error.txt sidecar, so nothing silently disappears.

Usage:
    python src/ingest_incoming.py                     # process once, then exit
    python src/ingest_incoming.py --loop --every 60    # poll forever
"""

import argparse
import datetime
import os
import shutil
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ingest as ingest_mod

BASE = Path(__file__).resolve().parent.parent / "data" / "audio"
INCOMING = BASE / "incoming"
PROCESSED = BASE / "processed"
FAILED = BASE / "failed"

AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".aiff", ".aif"}


def process_once(whisper_model, location, hf_token):
    INCOMING.mkdir(parents=True, exist_ok=True)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    FAILED.mkdir(parents=True, exist_ok=True)

    files = sorted(p for p in INCOMING.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXTS)
    if not files:
        print("[ingest_incoming] nothing new")
        return 0

    done = 0
    for f in files:
        print(f"[ingest_incoming] processing {f.name}")
        try:
            ingest_mod.run(str(f), location, whisper_model, hf_token)
            dest = PROCESSED / f"{datetime.datetime.now():%Y%m%d_%H%M%S}_{f.name}"
            shutil.move(str(f), dest)
            done += 1
        except Exception:
            dest = FAILED / f.name
            shutil.move(str(f), dest)
            (FAILED / f"{f.name}.error.txt").write_text(traceback.format_exc())
            print(f"[ingest_incoming] FAILED {f.name} -- see data/audio/failed/{f.name}.error.txt")
    return done


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--location", default=None)
    ap.add_argument("--whisper-model", default="small")
    ap.add_argument("--loop", action="store_true", help="keep polling instead of running once")
    ap.add_argument("--every", type=int, default=60, help="seconds between polls with --loop")
    args = ap.parse_args()

    hf_token = os.environ.get("HF_TOKEN")
    if args.loop:
        print(f"[ingest_incoming] watching data/audio/incoming/ every {args.every}s (Ctrl+C to stop)")
        while True:
            process_once(args.whisper_model, args.location, hf_token)
            time.sleep(args.every)
    else:
        process_once(args.whisper_model, args.location, hf_token)


if __name__ == "__main__":
    main()
