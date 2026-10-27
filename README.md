# Verbatim — P0 pipeline prototype

Proves the core claim of the [design spec](./) before any app gets built:
record a conversation, retrieve it later by meaning *or* by importance, and
get back the exact words someone said, not an LLM's paraphrase of them.

No mobile app yet — this is a CLI over a local SQLite store, matching Phase
P0 of the roadmap ("prove the pipeline offline before building a client
around it"). Hardware is on order; everything downstream of "an audio file
exists" is built and tested now, so plugging the recorder in later is just
pointing it at a folder.

## When the hardware recorder arrives

Whatever it turns out to be (SD card, Bluetooth file transfer, a synced
folder), the integration point is the same: get audio files into
`data/audio/incoming/`. Nothing about the pipeline needs to change for a
specific device — it's hardware-agnostic by design.

```bash
python src/ingest_incoming.py                     # process what's there, once
python src/ingest_incoming.py --loop --every 60    # or keep polling
```

Processed files move to `data/audio/processed/`; anything that fails to
transcribe moves to `data/audio/failed/` with an `.error.txt` explaining why,
so nothing silently disappears.

To run the whole loop in the background permanently — picking up new
recordings, firing due reminders, generating the nightly digest — without a
terminal or Claude open:

```bash
./scripts/install_automation.sh     # installs 3 launchd agents (macOS)
./scripts/uninstall_automation.sh   # removes them
```

This installs `com.verbatim.ingest` (every 5 min), `com.verbatim.reminders`
(every 15 min, fires due action items as macOS notifications), and
`com.verbatim.digest` (once daily at 21:30). Logs land in `data/logs/`.

## Pipeline

```
audio file -> transcribe (faster-whisper) -> diarize (pyannote, optional)
           -> chunk by speaker turn -> embed (bge-small) -> SQLite + vectors
```

Query and digest then read from that store:

- `src/query.py` — ask a question, get back cited, verbatim-quoted chunks.
- `src/digest.py` — generate one day's ranked "what mattered" summary.
- `src/rename_speaker.py` — attach a real name to a diarized `SPEAKER_00` label.
- `src/ingest_incoming.py` — process (or watch) `data/audio/incoming/` for new recordings.
- `src/check_reminders.py` — fire any action items that are now due, as a notification.
- `src/run_nightly_digest.py` — zero-argument wrapper so a scheduler can run the digest for "today".

## Setup

```bash
python3.11 -m venv .venv      # 3.11, not whatever `python3` resolves to --
source .venv/bin/activate     # torch/pyannote wheels lag behind new Python releases
pip install -r requirements.txt
cp .env.example .env          # then fill in the two keys below, both optional
```

Both keys are optional and the pipeline is useful without either:

| Key | Unlocks | Without it |
|---|---|---|
| `HF_TOKEN` | real speaker diarization | every utterance labeled `UNKNOWN`, everything in one chunk |
| `ANTHROPIC_API_KEY` | generated answers + daily digest | raw retrieved transcript chunks printed instead |

`HF_TOKEN` is a free Hugging Face account — create a token at
[huggingface.co/settings/tokens](https://huggingface.co/settings/tokens),
then accept the gated-model terms (one click each, no review wait) at
[pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)
and [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0).

## Try it

A synthetic two-speaker test recording, since there's no real one on hand yet:

```bash
./scripts/make_test_audio.sh          # writes data/audio/sample_meeting.wav
python src/ingest.py data/audio/sample_meeting.wav --location "test"
python src/query.py "what did they say about the agenda?"
```

With a real recording, drop the file in `data/audio/` and ingest it the same
way. Once a few sessions are in, try the digest:

```bash
python src/digest.py 2026-10-19
```

## What's actually verified right now

Ran end-to-end against the synthetic sample in this environment:
transcription, SQLite storage, embedding, and cosine-similarity retrieval all
work correctly (confirmed: asking about "the agenda" retrieves the right
chunk). The folder-watch ingest and the reminder checker have both been
smoke-tested too (drop a file in `incoming/`, it gets transcribed and moved
to `processed/`; `check_reminders.py` correctly finds nothing due on an
empty queue). Diarization and the generated-answer/digest stages are wired
up and separately unit-tested (speaker-turn chunking splits correctly given
diarization labels) but not yet run against the real models, since those
need the two keys above, which only you can create.

## Known limitations (see design spec for the full reasoning)

- No capture app yet — audio has to be dropped into `data/audio/` by hand.
- Diarization will mislabel speakers sometimes (expect ~10-20% error in
  noisy, multi-speaker audio); `rename_speaker.py` fixes the label, not the
  misattribution for utterances already assigned to the wrong speaker.
- Whisper's `small` model is the default for speed; swap to `medium` or
  `large-v3` via `--whisper-model` for better accuracy on real recordings.
