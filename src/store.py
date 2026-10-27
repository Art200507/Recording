"""SQLite storage layer for the Verbatim P0 prototype.

Single-file store: structured metadata (sessions, speakers, utterances)
plus chunk embeddings as raw float32 blobs. Similarity search is done in
Python with numpy rather than a vector DB extension -- at prototype scale
(one person's days of conversation) a few thousand chunks fit in memory
easily, and this avoids standing up Postgres/pgvector before the pipeline
itself is proven out.
"""

import sqlite3
import json
from pathlib import Path

import numpy as np

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "db" / "verbatim.sqlite3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    audio_path TEXT NOT NULL,
    started_at TEXT NOT NULL,
    location TEXT
);

CREATE TABLE IF NOT EXISTS speakers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL UNIQUE,
    display_name TEXT
);

CREATE TABLE IF NOT EXISTS utterances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    speaker_id INTEGER REFERENCES speakers(id),
    start_sec REAL NOT NULL,
    end_sec REAL NOT NULL,
    abs_start TEXT NOT NULL,
    text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    start_sec REAL NOT NULL,
    end_sec REAL NOT NULL,
    abs_start TEXT NOT NULL,
    text TEXT NOT NULL,
    speaker_labels TEXT NOT NULL,
    embedding BLOB NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text, content='chunks', content_rowid='id'
);

CREATE TABLE IF NOT EXISTS daily_digests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    summary_md TEXT,
    highlights_json TEXT,
    generated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS action_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_utterance_id INTEGER REFERENCES utterances(id),
    text TEXT NOT NULL,
    due_at TEXT,
    status TEXT DEFAULT 'pending'
);
"""


def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def create_session(conn, audio_path, started_at_iso, location=None):
    cur = conn.execute(
        "INSERT INTO sessions (audio_path, started_at, location) VALUES (?, ?, ?)",
        (audio_path, started_at_iso, location),
    )
    return cur.lastrowid


def get_or_create_speaker(conn, label):
    row = conn.execute("SELECT id FROM speakers WHERE label = ?", (label,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute("INSERT INTO speakers (label) VALUES (?)", (label,))
    return cur.lastrowid


def rename_speaker(conn, label, display_name):
    conn.execute("UPDATE speakers SET display_name = ? WHERE label = ?", (display_name, label))
    conn.commit()


def speaker_display(conn, label):
    row = conn.execute("SELECT display_name FROM speakers WHERE label = ?", (label,)).fetchone()
    return (row["display_name"] if row and row["display_name"] else label)


def insert_utterance(conn, session_id, speaker_id, start_sec, end_sec, abs_start_iso, text):
    cur = conn.execute(
        "INSERT INTO utterances (session_id, speaker_id, start_sec, end_sec, abs_start, text) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (session_id, speaker_id, start_sec, end_sec, abs_start_iso, text),
    )
    return cur.lastrowid


def insert_chunk(conn, session_id, start_sec, end_sec, abs_start_iso, text, speaker_labels, embedding: np.ndarray):
    blob = np.asarray(embedding, dtype=np.float32).tobytes()
    cur = conn.execute(
        "INSERT INTO chunks (session_id, start_sec, end_sec, abs_start, text, speaker_labels, embedding) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (session_id, start_sec, end_sec, abs_start_iso, text, json.dumps(speaker_labels), blob),
    )
    chunk_id = cur.lastrowid
    conn.execute("INSERT INTO chunks_fts (rowid, text) VALUES (?, ?)", (chunk_id, text))
    return chunk_id


def all_chunks(conn, date_from=None, date_to=None, speaker_label=None):
    sql = "SELECT * FROM chunks WHERE 1=1"
    params = []
    if date_from:
        sql += " AND abs_start >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND abs_start <= ?"
        params.append(date_to)
    rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        labels = json.loads(r["speaker_labels"])
        if speaker_label and speaker_label not in labels:
            continue
        emb = np.frombuffer(r["embedding"], dtype=np.float32)
        out.append({
            "id": r["id"],
            "session_id": r["session_id"],
            "start": r["start_sec"],
            "end": r["end_sec"],
            "abs_start": r["abs_start"],
            "text": r["text"],
            "speakers": labels,
            "embedding": emb,
        })
    return out


def keyword_matches(conn, query_text, limit=20):
    try:
        rows = conn.execute(
            "SELECT rowid, text FROM chunks_fts WHERE chunks_fts MATCH ? LIMIT ?",
            (query_text, limit),
        ).fetchall()
        return {r["rowid"] for r in rows}
    except sqlite3.OperationalError:
        return set()


def utterances_for_date(conn, date_str):
    rows = conn.execute(
        "SELECT u.*, s.label AS speaker_label FROM utterances u "
        "JOIN speakers s ON s.id = u.speaker_id "
        "WHERE u.abs_start LIKE ? ORDER BY u.abs_start",
        (f"{date_str}%",),
    ).fetchall()
    return [dict(r) for r in rows]


def save_digest(conn, date_str, summary_md, highlights, generated_at_iso):
    conn.execute(
        "INSERT INTO daily_digests (date, summary_md, highlights_json, generated_at) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(date) DO UPDATE SET summary_md=excluded.summary_md, "
        "highlights_json=excluded.highlights_json, generated_at=excluded.generated_at",
        (date_str, summary_md, json.dumps(highlights), generated_at_iso),
    )
    conn.commit()


def add_action_item(conn, source_utterance_id, text, due_at=None):
    conn.execute(
        "INSERT INTO action_items (source_utterance_id, text, due_at) VALUES (?, ?, ?)",
        (source_utterance_id, text, due_at),
    )


def due_action_items(conn, now_iso):
    rows = conn.execute(
        "SELECT * FROM action_items WHERE status = 'pending' AND due_at IS NOT NULL AND due_at <= ?",
        (now_iso,),
    ).fetchall()
    return [dict(r) for r in rows]


def mark_action_item(conn, item_id, status):
    conn.execute("UPDATE action_items SET status = ? WHERE id = ?", (status, item_id))
    conn.commit()
