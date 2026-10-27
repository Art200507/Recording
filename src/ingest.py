"""Ingest one audio file: transcribe, diarize, chunk by speaker turn, embed, store.

Usage:
    python src/ingest.py data/audio/sample.wav [--location "kitchen"] [--whisper-model small]

Diarization requires a Hugging Face token (free account, accept the terms on
    https://huggingface.co/pyannote/speaker-diarization-3.1
    https://huggingface.co/pyannote/segmentation-3.0
and set HF_TOKEN in .env). Without it, every utterance is labeled UNKNOWN
and the pipeline still runs -- diarization quality is a separate, swappable
stage, not a hard dependency of transcription + retrieval.
"""

import argparse
import datetime
import sys
from pathlib import Path

from dotenv import load_dotenv
import numpy as np
from faster_whisper import WhisperModel
from sentence_transformers import SentenceTransformer

sys.path.insert(0, str(Path(__file__).resolve().parent))
import store

load_dotenv()

EMBED_MODEL = "BAAI/bge-small-en-v1.5"
MAX_CHUNK_SECONDS = 90.0


def transcribe(audio_path, model_size):
    print(f"[ingest] loading whisper model '{model_size}' ...")
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, info = model.transcribe(audio_path, word_timestamps=False, vad_filter=True)
    segments = list(segments)
    print(f"[ingest] transcribed {len(segments)} speech segments ({info.duration:.1f}s audio)")
    return segments


def diarize(audio_path, hf_token):
    from pyannote.audio import Pipeline as DiarizationPipeline

    print("[ingest] loading diarization pipeline ...")
    pipeline = DiarizationPipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1", use_auth_token=hf_token
    )
    diarization = pipeline(audio_path)
    turns = [(t.start, t.end, spk) for t, _, spk in diarization.itertracks(yield_label=True)]
    print(f"[ingest] diarization found {len(set(s for _, _, s in turns))} speaker(s), {len(turns)} turn(s)")
    return turns


def label_for(turns, start, end):
    if not turns:
        return "UNKNOWN"
    mid = (start + end) / 2
    best, best_overlap = None, 0.0
    for t_start, t_end, spk in turns:
        overlap = min(end, t_end) - max(start, t_start)
        if overlap > best_overlap:
            best_overlap, best = overlap, spk
    if best is not None:
        return best
    # fall back to nearest turn by midpoint distance
    nearest = min(turns, key=lambda t: abs(mid - (t[0] + t[1]) / 2))
    return nearest[2]


def chunk_utterances(utterances, max_dur=MAX_CHUNK_SECONDS):
    """Break into chunks on every speaker change, and on exceeding max_dur
    (so a single long monologue, e.g. a lecture, still yields time-addressable
    chunks instead of one giant block)."""
    chunks = []
    cur = None
    for utt in utterances:
        if cur is None:
            cur = {"start": utt["start"], "end": utt["end"], "text": utt["text"],
                   "speaker": utt["speaker"], "utt_ids": [utt["id"]]}
            continue
        same_speaker = utt["speaker"] == cur["speaker"]
        dur_if_extended = utt["end"] - cur["start"]
        if same_speaker and dur_if_extended <= max_dur:
            cur["end"] = utt["end"]
            cur["text"] += " " + utt["text"]
            cur["utt_ids"].append(utt["id"])
        else:
            chunks.append(cur)
            cur = {"start": utt["start"], "end": utt["end"], "text": utt["text"],
                   "speaker": utt["speaker"], "utt_ids": [utt["id"]]}
    if cur:
        chunks.append(cur)
    return chunks


def run(audio_path, location, whisper_model, hf_token):
    audio_path = str(Path(audio_path).resolve())
    segments = transcribe(audio_path, whisper_model)
    turns = diarize(audio_path, hf_token) if hf_token else []
    if not hf_token:
        print("[ingest] no HF_TOKEN set -- skipping diarization, labeling everyone UNKNOWN")

    conn = store.get_conn()
    started_at = datetime.datetime.now().astimezone()
    session_id = store.create_session(conn, audio_path, started_at.isoformat(), location)

    print(f"[ingest] loading embedding model '{EMBED_MODEL}' ...")
    embedder = SentenceTransformer(EMBED_MODEL)

    utterances = []
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        label = label_for(turns, seg.start, seg.end)
        speaker_id = store.get_or_create_speaker(conn, label)
        abs_start = (started_at + datetime.timedelta(seconds=seg.start)).isoformat()
        utt_id = store.insert_utterance(conn, session_id, speaker_id, seg.start, seg.end, abs_start, text)
        utterances.append({"id": utt_id, "start": seg.start, "end": seg.end, "speaker": label, "text": text})

    if not utterances:
        print("[ingest] no speech detected -- nothing stored")
        conn.commit()
        return

    chunks = chunk_utterances(utterances)
    texts = [c["text"].strip() for c in chunks]
    embeddings = embedder.encode(texts, normalize_embeddings=True, show_progress_bar=False)

    for chunk, emb in zip(chunks, embeddings):
        abs_start = (started_at + datetime.timedelta(seconds=chunk["start"])).isoformat()
        store.insert_chunk(
            conn, session_id, chunk["start"], chunk["end"], abs_start,
            chunk["text"].strip(), [chunk["speaker"]], emb,
        )

    conn.commit()
    print(f"[ingest] session {session_id}: {len(utterances)} utterances -> {len(chunks)} chunks stored")
    print(f"[ingest] speakers seen: {sorted(set(u['speaker'] for u in utterances))}")
    print("[ingest] rename a speaker with: python src/rename_speaker.py SPEAKER_00 'Mom'")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("audio_path")
    ap.add_argument("--location", default=None)
    ap.add_argument("--whisper-model", default="small",
                     help="tiny/base/small/medium/large-v3 (bigger = slower + more accurate)")
    args = ap.parse_args()

    import os
    hf_token = os.environ.get("HF_TOKEN")
    run(args.audio_path, args.location, args.whisper_model, hf_token)


if __name__ == "__main__":
    main()
