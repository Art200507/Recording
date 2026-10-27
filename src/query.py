"""Ask a question over everything ingested so far.

Usage:
    python src/query.py "what did Sam say about the agenda?"
    python src/query.py "what was the most important conversation today?" --date 2026-10-19

Retrieval is hybrid: cosine similarity over embeddings, with chunks that also
keyword-match the question (via SQLite FTS5) boosted to the top -- a pure
semantic question like "what did my professor say" might not share vocabulary
with the actual quote, but a literal word in the question almost always
deserves to outrank near-miss paraphrases.

The verbatim rule: the model is instructed to answer only from the retrieved
chunk text, quoting it exactly rather than rephrasing. If no ANTHROPIC_API_KEY
is set, raw retrieved chunks are printed instead so the pipeline is still
useful without an API key.
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
import numpy as np
from sentence_transformers import SentenceTransformer

sys.path.insert(0, str(Path(__file__).resolve().parent))
import store

load_dotenv()

EMBED_MODEL = "BAAI/bge-small-en-v1.5"
KEYWORD_BOOST = 0.15


def fmt_ts(seconds):
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def retrieve(conn, query_text, query_emb, date_from=None, date_to=None, speaker=None, top_k=6):
    chunks = store.all_chunks(conn, date_from, date_to, speaker)
    if not chunks:
        return []
    embs = np.stack([c["embedding"] for c in chunks])
    sims = embs @ query_emb
    keyword_ids = store.keyword_matches(conn, query_text)
    scores = []
    for c, sim in zip(chunks, sims):
        boost = KEYWORD_BOOST if c["id"] in keyword_ids else 0.0
        scores.append(float(sim) + boost)
    order = np.argsort(scores)[::-1][:top_k]
    return [(chunks[i], scores[i]) for i in order]


def render_chunk(conn, c):
    speakers = ", ".join(store.speaker_display(conn, lbl) for lbl in c["speakers"])
    return f"{speakers} @ {fmt_ts(c['start'])}: \"{c['text']}\""


def answer_with_claude(query_text, conn, results, model):
    import anthropic

    context = "\n\n".join(
        f"[{i+1}] speaker(s)={', '.join(store.speaker_display(conn, l) for l in r['speakers'])} "
        f"timestamp={fmt_ts(r['start'])}-{fmt_ts(r['end'])} session={r['session_id']}\n"
        f"\"{r['text']}\""
        for i, (r, score) in enumerate(results)
    )
    system = (
        "You answer questions about the user's own recorded conversations using ONLY the "
        "transcript chunks given below -- never outside knowledge. When the user asks what "
        "someone said, reproduce their exact words from the chunk in quotation marks; never "
        "paraphrase a quote. Always attribute each quote to its speaker and timestamp, like "
        "'Mom said at 04:12: \"...\"'. If the chunks don't contain the answer, say so plainly "
        "instead of guessing."
    )
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=model,
        max_tokens=600,
        system=system,
        messages=[{"role": "user", "content": f"Transcript chunks:\n{context}\n\nQuestion: {query_text}"}],
    )
    return msg.content[0].text


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("question")
    ap.add_argument("--date", default=None, help="restrict to one day, YYYY-MM-DD")
    ap.add_argument("--speaker", default=None, help="restrict to one speaker label")
    ap.add_argument("--top-k", type=int, default=6)
    ap.add_argument("--model", default="claude-sonnet-5")
    args = ap.parse_args()

    conn = store.get_conn()
    embedder = SentenceTransformer(EMBED_MODEL)
    query_emb = embedder.encode(args.question, normalize_embeddings=True)

    date_from = date_to = None
    if args.date:
        date_from, date_to = args.date, args.date + "T23:59:59"

    results = retrieve(conn, args.question, query_emb, date_from, date_to, args.speaker, args.top_k)
    if not results:
        print("No matching conversations found yet. Ingest some audio first with src/ingest.py.")
        return

    print(f"--- top {len(results)} retrieved chunks ---")
    for r, score in results:
        print(f"  ({score:.3f}) {render_chunk(conn, r)}")
    print()

    if os.environ.get("ANTHROPIC_API_KEY"):
        print("--- answer ---")
        print(answer_with_claude(args.question, conn, results, args.model))
    else:
        print("[no ANTHROPIC_API_KEY set -- showing raw retrieved chunks only, no generated answer]")


if __name__ == "__main__":
    main()
