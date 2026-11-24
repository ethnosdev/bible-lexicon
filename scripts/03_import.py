#!/usr/bin/env python3
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "lexicon.db"
INBOX_FILE = BASE_DIR / "inbox" / "response.json"

REQUIRED_KEYS = {
    "lemma_id", "lemma", "lang", "transliteration",
    "core_meaning_summary", "senses", "confidence"
}


def clean_json_text(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()


def normalize_uncertainty_note(val) -> Optional[str]:
    """Coerce literal 'null' or blank strings in uncertainty_note to None."""
    if val is None:
        return None
    if isinstance(val, str):
        stripped = val.strip()
        if not stripped or stripped.lower() == "null":
            return None
        return stripped
    return str(val)


def main():
    if not INBOX_FILE.exists():
        print(f"[ERROR] Missing {INBOX_FILE}")
        return

    try:
        data = json.loads(clean_json_text(INBOX_FILE.read_text(encoding="utf-8")))
        if not isinstance(data, list):
            raise ValueError("Top-level JSON must be an array [...]")
    except Exception as e:
        print(f"[REJECTED] Invalid JSON in response.json: {e}")
        return

    conn = sqlite3.connect(DB_PATH)
    now = datetime.now(timezone.utc).isoformat()
    saved, rejected = 0, 0

    for item in data:
        missing = REQUIRED_KEYS - set(item.keys())
        if missing:
            print(f"[REJECTED] lemma_id={item.get('lemma_id')} missing keys: {missing}")
            rejected += 1
            continue

        lid = item["lemma_id"]
        row = conn.execute(
            "SELECT lang, lemma, total_count FROM lemmas WHERE lemma_id = ?", (lid,)
        ).fetchone()
        if not row:
            print(f"[REJECTED] Unknown lemma_id={lid}")
            rejected += 1
            continue

        db_lang, db_lemma, total_count = row
        valid_refs = {
            r[0] for r in conn.execute(
                "SELECT DISTINCT ref FROM tokens WHERE lang = ? AND lemma = ?",
                (db_lang, db_lemma),
            ).fetchall()
        }

        # Verify every cited reference actually exists for this word
        bad_refs = []
        if not isinstance(item["senses"], list) or len(item["senses"]) == 0:
            bad_refs.append("EMPTY_SENSES")
        else:
            for s in item["senses"]:
                for ref in s.get("cited_refs", []):
                    if ref not in valid_refs:
                        bad_refs.append(ref)

        if bad_refs:
            print(f"[REJECTED] lemma_id={lid} ({db_lemma}) cited invalid refs: {bad_refs}")
            conn.execute(
                "UPDATE lemmas SET status = 'pending', updated_at = ? WHERE lemma_id = ?",
                (now, lid),
            )
            rejected += 1
            continue

        note = normalize_uncertainty_note(item.get("uncertainty_note"))
        if "uncertainty_note" in item:
            item["uncertainty_note"] = note

        # Flag suspiciously overconfident hapax legomena for later human review
        conf = item.get("confidence", "medium").lower()
        flag_reason = note
        new_status = "drafted"
        if total_count == 1 and conf == "high":
            flag_reason = (
                f"{flag_reason} | AUTO-FLAG: single occurrence marked high confidence"
                if flag_reason
                else "AUTO-FLAG: single occurrence marked high confidence"
            )
            new_status = "needs_review"

        conn.execute("""
            INSERT OR REPLACE INTO lexicon_entries (lemma_id, entry_json, confidence, flag_reason, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (lid, json.dumps(item, ensure_ascii=False), conf, flag_reason, now))

        conn.execute(
            "UPDATE lemmas SET status = ?, updated_at = ? WHERE lemma_id = ?",
            (new_status, now, lid),
        )
        saved += 1

    conn.commit()
    conn.close()

    if saved > 0 and rejected == 0:
        INBOX_FILE.unlink()
    print(f"[IMPORT COMPLETE] Saved: {saved} | Rejected (returned to pending): {rejected}")


if __name__ == "__main__":
    main()