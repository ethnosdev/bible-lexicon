#!/usr/bin/env python3
import csv
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "lexicon.db"
NESTLE_DIR = BASE_DIR / "raw_data" / "Nestle1904" / "morph"
WLC_DIR = BASE_DIR / "raw_data" / "macula-hebrew" / "WLC" / "tsv"

PILOT_BOOKS = {"JON", "Jonah", "PHP", "Phil", "Philippians"}

NT_BOOK_MAP = {
    "40": "MAT", "41": "MRK", "42": "LUK", "43": "JHN", "44": "ACT",
    "45": "ROM", "46": "1CO", "47": "2CO", "48": "GAL", "49": "EPH",
    "50": "PHP", "51": "COL", "52": "1TH", "53": "2TH", "54": "1TI",
    "55": "2TI", "56": "TIT", "57": "PHM", "58": "HEB", "59": "JAS",
    "60": "1PE", "61": "2PE", "62": "1JN", "63": "2JN", "64": "3JN",
    "65": "JUD", "66": "REV",
    "Matt": "MAT", "Mark": "MRK", "Luke": "LUK", "John": "JHN", "Acts": "ACT",
    "Rom": "ROM", "1Cor": "1CO", "2Cor": "2CO", "Gal": "GAL", "Eph": "EPH",
    "Phil": "PHP", "Col": "COL", "1Thess": "1TH", "2Thess": "2TH", "1Tim": "1TI",
    "2Tim": "2TI", "Titus": "TIT", "Phlm": "PHM", "Heb": "HEB", "Jas": "JAS",
    "1Pet": "1PE", "2Pet": "2PE", "1John": "1JN", "2John": "2JN", "3John": "3JN",
    "Jude": "JUD", "Rev": "REV",
}


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    PRAGMA journal_mode=WAL;
    PRAGMA foreign_keys=ON;

    CREATE TABLE IF NOT EXISTS tokens (
        token_seq     INTEGER PRIMARY KEY AUTOINCREMENT,
        lang          TEXT NOT NULL,
        book          TEXT NOT NULL,
        chapter       INTEGER NOT NULL,
        verse         INTEGER NOT NULL,
        ref           TEXT NOT NULL,
        surface       TEXT NOT NULL,
        lemma         TEXT NOT NULL,
        pos           TEXT,
        morph_note    TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_tokens_lemma ON tokens(lang, lemma);
    CREATE INDEX IF NOT EXISTS idx_tokens_ref ON tokens(ref);

    CREATE TABLE IF NOT EXISTS lemmas (
        lemma_id      INTEGER PRIMARY KEY AUTOINCREMENT,
        lang          TEXT NOT NULL,
        lemma         TEXT NOT NULL,
        pos           TEXT,
        total_count   INTEGER NOT NULL,
        priority_tier INTEGER NOT NULL,
        status        TEXT NOT NULL DEFAULT 'pending',
        batch_id      TEXT,
        updated_at    TEXT,
        UNIQUE(lang, lemma)
    );

    CREATE TABLE IF NOT EXISTS lexicon_entries (
        lemma_id      INTEGER PRIMARY KEY REFERENCES lemmas(lemma_id),
        entry_json    TEXT NOT NULL,
        confidence    TEXT NOT NULL,
        flag_reason   TEXT,
        created_at    TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS benchmark_hidden (
        lang          TEXT,
        lemma         TEXT,
        hidden_gloss  TEXT,
        hidden_domain TEXT
    );
    """)


def pick_col(row: dict, candidates: list[str]) -> str:
    lower_map = {k.lower().strip(): v for k, v in row.items() if k}
    for c in candidates:
        if c.lower() in lower_map and lower_map[c.lower()] is not None:
            return lower_map[c.lower()].strip()
    return ""


def parse_ref(raw_ref: str, book_fallback="", ch_fallback="", vs_fallback=""):
    if raw_ref:
        clean = raw_ref.split("!")[0].split("#")[0].strip()
        # Handle "GEN 1:1" or "Matt.1.1"
        m = re.match(r"^([1-3]?[A-Za-z]+)[.\s]+(\d+)[:.](\d+)", clean)
        if m:
            bk = NT_BOOK_MAP.get(m.group(1), m.group(1).upper())
            ch, vs = int(m.group(2)), int(m.group(3))
            return bk, ch, vs, f"{bk} {ch}:{vs}"
        # Handle numeric BCV e.g. 40001001 or 400101
        if clean.isdigit() and len(clean) >= 6:
            bk_num = clean[:2]
            bk = NT_BOOK_MAP.get(bk_num, bk_num)
            rest = clean[2:]
            mid = len(rest) // 2
            ch, vs = int(rest[:mid]), int(rest[mid:])
            return bk, ch, vs, f"{bk} {ch}:{vs}"
    bk = NT_BOOK_MAP.get(book_fallback, book_fallback.upper() or "UNK")
    ch = int(ch_fallback) if str(ch_fallback).isdigit() else 0
    vs = int(vs_fallback) if str(vs_fallback).isdigit() else 0
    return bk, ch, vs, f"{bk} {ch}:{vs}"


def ingest_nestle1904(conn: sqlite3.Connection) -> int:
    csv_files = sorted(NESTLE_DIR.glob("*.csv"))
    if not csv_files:
        print(f"[WARN] No CSV files found in {NESTLE_DIR}")
        return 0

    count = 0
    for fpath in csv_files:
        with fpath.open("r", encoding="utf-8-sig") as f:
            sample = f.readline()
            f.seek(0)
            delim = "\t" if "\t" in sample else ","
            reader = csv.DictReader(f, delimiter=delim)
            print(f"[INFO] Reading Greek: {fpath.name} | Columns: {reader.fieldnames}")
            rows = []
            for row in reader:
                surface = pick_col(row, ["text", "word", "surface", "form", "unicode"])
                lemma = pick_col(row, ["lemma", "lex", "dict_form"])
                if not surface or not lemma:
                    continue
                raw_ref = pick_col(row, ["BCV", "ref", "bcv", "verse_id"])
                bk, ch, vs, ref = parse_ref(
                    raw_ref,
                    pick_col(row, ["book"]),
                    pick_col(row, ["chapter"]),
                    pick_col(row, ["verse"]),
                )
                pos = pick_col(row, ["func_tag", "pos", "part_of_speech"])
                morph = pick_col(row, ["morph", "parsing"])
                rows.append(("greek", bk, ch, vs, ref, surface, lemma, pos, morph))
            conn.executemany(
                "INSERT INTO tokens (lang, book, chapter, verse, ref, surface, lemma, pos, morph_note) VALUES (?,?,?,?,?,?,?,?,?)",
                rows,
            )
            count += len(rows)
    return count


def ingest_wlc(conn: sqlite3.Connection) -> int:
    tsv_files = sorted(WLC_DIR.rglob("*.tsv"))
    if not tsv_files:
        print(f"[WARN] No TSV files found in {WLC_DIR}")
        return 0

    count = 0
    hidden_rows = []
    for fpath in tsv_files:
        with fpath.open("r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter="\t")
            print(f"[INFO] Reading Hebrew/Aramaic: {fpath.name} | Columns: {reader.fieldnames}")
            rows = []
            for row in reader:
                surface = pick_col(row, ["text", "unicode", "surface", "word"])
                lemma = pick_col(row, ["lemma", "lex"])
                if not surface or not lemma:
                    continue
                raw_ref = pick_col(row, ["ref", "xml:id", "bcv"])
                bk, ch, vs, ref = parse_ref(raw_ref)
                raw_lang = pick_col(row, ["lang", "language"]).lower()
                lang = "aramaic" if raw_lang.startswith("a") else "hebrew"
                pos = pick_col(row, ["class", "pos"])
                # Note: morph_note stays strictly internal (never exported to CC0 output)
                stem = pick_col(row, ["stem"])
                rows.append((lang, bk, ch, vs, ref, surface, lemma, pos, stem))

                gloss = pick_col(row, ["gloss", "english"])
                domain = pick_col(row, ["sdbh", "domain"])
                if gloss or domain:
                    hidden_rows.append((lang, lemma, gloss, domain))

            conn.executemany(
                "INSERT INTO tokens (lang, book, chapter, verse, ref, surface, lemma, pos, morph_note) VALUES (?,?,?,?,?,?,?,?,?)",
                rows,
            )
            count += len(rows)

    if hidden_rows:
        conn.executemany(
            "INSERT INTO benchmark_hidden (lang, lemma, hidden_gloss, hidden_domain) VALUES (?,?,?,?)",
            hidden_rows,
        )
    return count


def build_lemma_queue(conn: sqlite3.Connection) -> int:
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute("""
        SELECT
            lang,
            lemma,
            MAX(pos) AS main_pos,
            COUNT(*) AS cnt,
            GROUP_CONCAT(DISTINCT book) AS books
        FROM tokens
        GROUP BY lang, lemma
        ORDER BY cnt DESC
    """)
    inserted = 0
    for lang, lemma, pos, cnt, books_str in cur.fetchall():
        books = set((books_str or "").split(","))
        if books & PILOT_BOOKS:
            tier = 1
        elif cnt >= 10:
            tier = 2
        elif cnt >= 3:
            tier = 3
        else:
            tier = 4

        conn.execute("""
            INSERT OR IGNORE INTO lemmas (lang, lemma, pos, total_count, priority_tier, status, updated_at)
            VALUES (?, ?, ?, ?, ?, 'pending', ?)
        """, (lang, lemma, pos, cnt, tier, now))
        inserted += 1
    return inserted


def main():
    if DB_PATH.exists():
        print(f"[INFO] {DB_PATH.name} already exists. Checking token count...")
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    existing_tokens = conn.execute("SELECT COUNT(*) FROM tokens").fetchone()[0]
    if existing_tokens == 0:
        g_cnt = ingest_nestle1904(conn)
        h_cnt = ingest_wlc(conn)
        l_cnt = build_lemma_queue(conn)
        conn.commit()
        print(f"\n[DONE] Ingested {g_cnt:,} Greek tokens + {h_cnt:,} Hebrew/Aramaic tokens.")
        print(f"[DONE] Created resumable work queue with {l_cnt:,} unique lemmas.")
    else:
        print(f"[SKIP] Database already has {existing_tokens:,} tokens. Delete lexicon.db only if you want a full reset.")
    conn.close()


if __name__ == "__main__":
    main()