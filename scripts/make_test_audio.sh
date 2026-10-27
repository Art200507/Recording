#!/bin/bash
# Synthesize a short two-speaker test recording with macOS `say`, so the
# pipeline can be exercised end-to-end without a real recording on hand.
set -euo pipefail

OUT_DIR="$(cd "$(dirname "$0")/.." && pwd)/data/audio"
mkdir -p "$OUT_DIR"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

say -v Alex     "Hey, are we still on for the project review Friday afternoon?" -o "$TMP/1.aiff"
say -v Samantha "Yes, let's do three P M. I will send the agenda tonight."       -o "$TMP/2.aiff"
say -v Alex     "Perfect, that works for me. Thanks for sorting the room too."  -o "$TMP/3.aiff"
say -v Samantha "No problem. Oh, and remind me to loop in Priya before Friday." -o "$TMP/4.aiff"

for f in "$TMP"/*.aiff; do
  ffmpeg -y -loglevel error -i "$f" -ar 16000 -ac 1 "${f%.aiff}.wav"
done
ffmpeg -y -loglevel error -f lavfi -i anullsrc=r=16000:cl=mono -t 0.6 "$TMP/gap.wav"

ffmpeg -y -loglevel error \
  -i "$TMP/1.wav" -i "$TMP/gap.wav" -i "$TMP/2.wav" -i "$TMP/gap.wav" \
  -i "$TMP/3.wav" -i "$TMP/gap.wav" -i "$TMP/4.wav" \
  -filter_complex "[0:a][1:a][2:a][3:a][4:a][5:a][6:a]concat=n=7:v=0:a=1[out]" \
  -map "[out]" -acodec pcm_s16le "$OUT_DIR/sample_meeting.wav"

echo "Wrote $OUT_DIR/sample_meeting.wav"
