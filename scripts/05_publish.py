#!/usr/bin/env python3
"""Publish clean CC0 public-domain lexicon exports from lexicon.db."""

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "lexicon.db"
EXPORTS_DIR = BASE_DIR / "exports"

EXPORTABLE_STATUSES = ("drafted", "needs_review", "verified")


def build_export_records(conn: sqlite3.Connection, statuses: tuple[str, ...]) -> list[dict]:
    """Load lexicon entries matching statuses without exposing internal benchmark/morph data."""
    placeholders = ",".join("?" for _ in statuses)
    rows = conn.execute(
        f"""
        SELECT l.lemma_id, l.lang, l.lemma, l.pos, l.total_count, l.priority_tier, l.status, e.entry_json
        FROM lexicon_entries e
        JOIN lemmas l ON l.lemma_id = e.lemma_id
        WHERE l.status IN ({placeholders})
        ORDER BY l.lemma_id ASC
        """,
        statuses,
    ).fetchall()

    records = []
    for lemma_id, lang, lemma, pos, total_count, tier, status, entry_json in rows:
        entry = json.loads(entry_json)
        record = {
            "lemma_id": lemma_id,
            "lemma": entry.get("lemma", lemma),
            "lang": entry.get("lang", lang),
            "transliteration": entry.get("transliteration", ""),
            "pos": pos,
            "total_occurrences": total_count,
            "priority_tier": tier,
            "status": status,
            "core_meaning_summary": entry.get("core_meaning_summary", ""),
            "senses": entry.get("senses", []),
            "collocations_and_notes": entry.get("collocations_and_notes"),
            "confidence": entry.get("confidence", "medium"),
            "uncertainty_note": entry.get("uncertainty_note"),
        }
        records.append(record)
    return records


def main():
    parser = argparse.ArgumentParser(description="Export CC0 lexicon deliverables to exports/.")
    parser.add_argument(
        "--verified-only",
        action="store_true",
        help="Export only entries with status='verified' (default includes drafted and needs_review).",
    )
    args = parser.parse_args()

    statuses = ("verified",) if args.verified_only else EXPORTABLE_STATUSES
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    records = build_export_records(conn, statuses)
    conn.close()

    status_counts = dict(Counter(r["status"] for r in records))
    lang_counts = dict(Counter(r["lang"] for r in records))
    now = datetime.now(timezone.utc).isoformat()

    json_path = EXPORTS_DIR / "lexicon.json"
    jsonl_path = EXPORTS_DIR / "lexicon.jsonl"

    payload = {
        "license": "CC0-1.0",
        "generated_at": now,
        "total_entries": len(records),
        "status_counts": status_counts,
        "lang_counts": lang_counts,
        "entries": records,
    }
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    with jsonl_path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"[PUBLISHED] {len(records):,} entries -> {json_path.name}, {jsonl_path.name}")
    print(f"            Languages: {lang_counts} | Statuses: {status_counts}")


if __name__ == "__main__":
    main()
