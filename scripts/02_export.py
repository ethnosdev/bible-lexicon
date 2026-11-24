#!/usr/bin/env python3
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "lexicon.db"
BATCH_FILE = BASE_DIR / "batches" / "current_batch.md"


def get_verse_context(conn: sqlite3.Connection, ref: str, target_lemma: str, target_lang: str) -> str:
    rows = conn.execute(
        "SELECT surface, lemma FROM tokens WHERE ref = ? AND lang = ? ORDER BY token_seq",
        (ref, target_lang),
    ).fetchall()
    parts = []
    for surf, lem in rows:
        if lem == target_lemma:
            parts.append(f"【{surf}】")
        else:
            parts.append(surf)
    return " ".join(parts)


def sample_occurrences(rows: list[tuple], max_samples: int) -> list[tuple]:
    if len(rows) <= max_samples:
        return rows
    step = len(rows) / max_samples
    return [rows[int(i * step)] for i in range(max_samples)]


def main():
    conn = sqlite3.connect(DB_PATH)
    now = datetime.now(timezone.utc).isoformat()

    # 1. Recover any previously exported batch that wasn't imported yet (crash/credit-limit safety)
    in_flight = conn.execute("""
        SELECT lemma_id, lang, lemma, pos, total_count, priority_tier
        FROM lemmas
        WHERE status = 'exported'
        ORDER BY lemma_id
    """).fetchall()

    if in_flight:
        batch_id = "RESUMED"
        selected = in_flight
    else:
        first = conn.execute("""
            SELECT lemma_id, lang, lemma, pos, total_count, priority_tier
            FROM lemmas
            WHERE status = 'pending'
            ORDER BY priority_tier ASC, total_count ASC, lemma_id ASC
            LIMIT 1
        """).fetchone()

        if not first:
            print("[ALL DONE] No pending lemmas left!")
            return

        first_cnt = first[4]
        if first_cnt <= 5:
            limit = 15
        elif first_cnt <= 50:
            limit = 4
        else:
            limit = 1

        selected = conn.execute("""
            SELECT lemma_id, lang, lemma, pos, total_count, priority_tier
            FROM lemmas
            WHERE status = 'pending' AND priority_tier = ?
              AND CASE WHEN ? <= 5 THEN total_count <= 5
                       WHEN ? <= 50 THEN total_count <= 50
                       ELSE total_count > 50 END
            ORDER BY total_count ASC, lemma_id ASC
            LIMIT ?
        """, (first[5], first_cnt, first_cnt, limit)).fetchall()

        batch_id = uuid.uuid4().hex[:8]
        ids = [(batch_id, now, row[0]) for row in selected]
        conn.executemany(
            "UPDATE lemmas SET status = 'exported', batch_id = ?, updated_at = ? WHERE lemma_id = ?",
            ids,
        )
        conn.commit()

    # Build clean markdown evidence packet
    lines = [
        f"# Empirical Lexicon Batch `{batch_id}` ({len(selected)} lemma(s))",
        "",
        "Analyze ONLY the primary-text sentences below. Target words are marked with `【...】`.",
        "Return ONLY a valid JSON array written to `inbox/response.json` (no markdown fences needed, or valid JSON only).",
        "",
        "## Evidence Packets",
        "",
    ]

    for lemma_id, lang, lemma, pos, total_count, tier in selected:
        lines.append(f"### `lemma_id`: {lemma_id} | `{lemma}` ({lang}, total occurrences: {total_count})")
        occ = conn.execute("""
            SELECT DISTINCT ref, surface, morph_note
            FROM tokens
            WHERE lang = ? AND lemma = ?
            ORDER BY token_seq
        """, (lang, lemma)).fetchall()

        sampled = sample_occurrences(occ, max_samples=40 if total_count > 50 else 25)
        if len(occ) > len(sampled):
            lines.append(f"*(Stratified sample of {len(sampled)} of {len(occ)} distinct verse occurrences)*")

        for ref, surface, morph_note in sampled:
            verse_text = get_verse_context(conn, ref, lemma, lang)
            # Include CC0 Greek morph tag; keep Hebrew clean-room by omitting OSHB tag strings
            morph_str = f" [{morph_note}]" if (lang == "greek" and morph_note) else ""
            lines.append(f"- **{ref}**{morph_str}: {verse_text}")
        lines.append("")

    BATCH_FILE.write_text("\n".join(lines), encoding="utf-8")
    print(f"[EXPORTED] Batch {batch_id} ({len(selected)} lemmas) -> {BATCH_FILE}")
    conn.close()


if __name__ == "__main__":
    main()