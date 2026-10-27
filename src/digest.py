"""Generate the end-of-day digest: a ranked summary of the day's conversations
plus candidate action items, written once per day -- this is deliberately a
separate, precomputed pass from query.py's on-demand retrieval, because
"what mattered today" is a judgment call that shouldn't be re-derived fresh
on every ask (see the design spec's retrieval-modes rationale).

Usage:
    python src/digest.py 2026-10-19
"""

import argparse
import datetime
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
import store

load_dotenv()

SYSTEM_PROMPT = """You are writing an end-of-day digest from a transcript of everything the \
user said and heard on {date}. You will be given utterances as SPEAKER @ timestamp: "text".

Produce a JSON object with exactly these keys:
  "summary_md": a short markdown summary (3-6 sentences) of the day's conversations.
  "highlights": a list of 2-5 objects, each {{"why_it_matters": str, "speaker": str, \
"timestamp": str, "quote": str}}, ranked most important first. "quote" MUST be copied \
verbatim from the transcript, not reworded.
  "action_items": a list of 0-5 objects, each {{"text": str, "due_at_iso": str or null}}, \
for commitments or promises either the user or someone else made ("I'll send it Friday"). \
Resolve relative dates (Friday, tomorrow, next week) against {date} into an absolute \
"YYYY-MM-DDTHH:MM:SS" in local time; use null if no due time is implied at all.

Only use what's actually in the transcript. Return ONLY the JSON object, no other text.
"""


def build_transcript_text(conn, date_str):
    utts = store.utterances_for_date(conn, date_str)
    lines = []
    for u in utts:
        speaker = store.speaker_display(conn, u["speaker_label"])
        m, s = divmod(int(u["start_sec"]), 60)
        lines.append(f'{speaker} @ {m:02d}:{s:02d}: "{u["text"]}"')
    return utts, "\n".join(lines)


def generate(conn, date_str, model="claude-sonnet-5"):
    utts, transcript = build_transcript_text(conn, date_str)
    if not utts:
        print(f"No utterances recorded for {date_str}.")
        return None

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("[no ANTHROPIC_API_KEY set -- printing raw transcript instead of a generated digest]")
        print(transcript)
        return None

    import anthropic

    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=model,
        max_tokens=1200,
        system=SYSTEM_PROMPT.format(date=date_str),
        messages=[{"role": "user", "content": transcript}],
    )
    raw = msg.content[0].text.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print("[digest] model did not return clean JSON, showing raw output:")
        print(raw)
        return None

    store.save_digest(
        conn, date_str, data.get("summary_md", ""), data.get("highlights", []),
        datetime.datetime.now().astimezone().isoformat(),
    )

    for item in data.get("action_items", []):
        store.add_action_item(conn, None, item.get("text", ""), item.get("due_at_iso"))
    conn.commit()

    return data


def print_digest(date_str, data):
    print(f"=== Daily digest: {date_str} ===\n")
    print(data["summary_md"])
    print("\n--- highlights, most important first ---")
    for h in data.get("highlights", []):
        print(f'\n  {h["speaker"]} @ {h["timestamp"]}  ({h["why_it_matters"]})')
        print(f'    "{h["quote"]}"')
    if data.get("action_items"):
        print("\n--- action items ---")
        for a in data["action_items"]:
            due = f" (due: {a['due_at_iso']})" if a.get("due_at_iso") else ""
            print(f"  - {a['text']}{due}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("date", help="YYYY-MM-DD")
    ap.add_argument("--model", default="claude-sonnet-5")
    args = ap.parse_args()

    conn = store.get_conn()
    data = generate(conn, args.date, args.model)
    if data:
        print_digest(args.date, data)


if __name__ == "__main__":
    main()
