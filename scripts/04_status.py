#!/usr/bin/env python3
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "lexicon.db"

def main():
    conn = sqlite3.connect(DB_PATH)
    print("\n=== BIBLE LEXICON PROGRESS ===")
    rows = conn.execute("""
        SELECT priority_tier, status, COUNT(*)
        FROM lemmas
        GROUP BY priority_tier, status
        ORDER BY priority_tier, status
    """).fetchall()
    tier_names = {1: "Tier 1 (Pilot: Jonah+Phil)", 2: "Tier 2 (10+ occ)", 3: "Tier 3 (3-9 occ)", 4: "Tier 4 (1-2 occ)"}
    for tier, status, cnt in rows:
        print(f"  {tier_names.get(tier, tier):28s} | {status:12s} | {cnt:,}")

    total = conn.execute("SELECT COUNT(*) FROM lemmas").fetchone()[0]
    done = conn.execute("SELECT COUNT(*) FROM lemmas WHERE status IN ('drafted','needs_review','verified')").fetchone()[0]
    pct = (done / total * 100) if total else 0
    print(f"\nTotal Complete: {done:,} / {total:,} ({pct:.1f}%)\n")
    conn.close()

if __name__ == "__main__":
    main()