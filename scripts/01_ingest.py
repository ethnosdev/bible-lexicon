#!/usr/bin/env python3
import argparse
import csv
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "lexicon.db"
NESTLE_DIR = BASE_DIR / "raw_data" / "Nestle1904" / "morph"
WLC_DIR = BASE_DIR / "raw_data" / "macula-hebrew" / "WLC" / "tsv"
DODSON_CSV = BASE_DIR / "raw_data" / "Dodson-Greek-Lexicon" / "dodson.csv"

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


def nestle_pos_from_morph(tag: str) -> str:
    """Map Robinson/Nestle1904 morphology prefix to a clean POS label."""
    t = tag.strip().upper()
    if not t:
        return ""
    if t.startswith("A-NUI"):
        return "num"
    if t.startswith("N-"):
        return "noun"
    if t.startswith("V-"):
        return "verb"
    if t.startswith("A-"):
        return "adj"
    if t.startswith("T-"):
        return "art"
    if t[:2] in {"P-", "R-", "C-", "D-", "K-", "I-", "X-", "Q-", "F-", "S-"}:
        return "pron"
    mapping = {
        "ADV": "adv",
        "CONJ": "conj",
        "COND": "conj",
        "PREP": "prep",
        "PRT": "ptcl",
        "INJ": "ij",
        "ARAM": "foreign",
        "HEB": "foreign",
        "PUNCT": "punct",
    }
    return mapping.get(t, tag.strip().lower())


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
                raw_pos = pick_col(row, ["func_tag", "pos", "part_of_speech", "func_morph"])
                pos = nestle_pos_from_morph(raw_pos)
                morph = pick_col(row, ["morph", "parsing", "form_morph"]) or raw_pos
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


def load_dodson_map() -> dict[str, tuple[str, str]]:
    """Load Strong's -> (brief_gloss, longer_def) from Dodson Greek Lexicon."""
    if not DODSON_CSV.exists():
        print(f"[WARN] Dodson lexicon not found at {DODSON_CSV}")
        return {}
    mapping: dict[str, tuple[str, str]] = {}
    with DODSON_CSV.open("r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            raw_s = pick_col(row, ["Strong's", "strongs"])
            brief = pick_col(row, ["English Definition (brief)", "brief"])
            longer = pick_col(row, ["English Definition (longer)", "longer"])
            for num in re.findall(r"\d+", raw_s):
                key = f"{int(num):04d}"
                if key not in mapping:
                    mapping[key] = (brief, longer)
    return mapping


def ingest_dodson_benchmark(conn: sqlite3.Connection) -> int:
    """Populate benchmark_hidden for Greek lemmas using Nestle1904 strongs -> Dodson."""
    dodson = load_dodson_map()
    if not dodson:
        return 0
    csv_files = sorted(NESTLE_DIR.glob("*.csv"))
    if not csv_files:
        return 0

    lemma_glosses: dict[str, list[tuple[str, str]]] = {}
    seen: set[tuple[str, str]] = set()
    for fpath in csv_files:
        with fpath.open("r", encoding="utf-8-sig") as f:
            sample = f.readline()
            f.seek(0)
            delim = "\t" if "\t" in sample else ","
            for row in csv.DictReader(f, delimiter=delim):
                lemma = pick_col(row, ["lemma", "lex", "dict_form"])
                strongs = pick_col(row, ["strongs", "strong"])
                if not lemma or not strongs:
                    continue
                for num in re.findall(r"\d+", strongs):
                    key = f"{int(num):04d}"
                    if key in dodson and (lemma, key) not in seen:
                        seen.add((lemma, key))
                        lemma_glosses.setdefault(lemma, []).append(dodson[key])

    conn.execute("DELETE FROM benchmark_hidden WHERE lang = 'greek'")
    rows = []
    for lemma, entries in lemma_glosses.items():
        brief = "; ".join(dict.fromkeys(b for b, _ in entries if b))
        longer = " | ".join(dict.fromkeys(lg for _, lg in entries if lg))
        if brief or longer:
            rows.append(("greek", lemma, brief, longer))
    conn.executemany(
        "INSERT INTO benchmark_hidden (lang, lemma, hidden_gloss, hidden_domain) VALUES (?,?,?,?)",
        rows,
    )
    return len(rows)


def compute_main_pos(conn: sqlite3.Connection) -> dict[tuple[str, str], str]:
    pos_counts: dict[tuple[str, str], dict[str, int]] = {}
    for lang, lemma, pos, pcnt in conn.execute("""
        SELECT lang, lemma, pos, COUNT(*) AS pcnt
        FROM tokens
        WHERE pos IS NOT NULL AND pos != ''
        GROUP BY lang, lemma, pos
    """):
        pos_counts.setdefault((lang, lemma), {})[pos] = pcnt
    return {
        k: max(pdict.items(), key=lambda kv: (kv[1], kv[0]))[0]
        for k, pdict in pos_counts.items()
    }


def backfill_metadata(conn: sqlite3.Connection) -> None:
    """Backfill Greek POS/morph_note, recompute lemmas.pos, and load Dodson benchmark."""
    csv_files = sorted(NESTLE_DIR.glob("*.csv"))
    csv_tokens = []
    for fpath in csv_files:
        with fpath.open("r", encoding="utf-8-sig") as f:
            sample = f.readline()
            f.seek(0)
            delim = "\t" if "\t" in sample else ","
            for row in csv.DictReader(f, delimiter=delim):
                surface = pick_col(row, ["text", "word", "surface", "form", "unicode"])
                lemma = pick_col(row, ["lemma", "lex", "dict_form"])
                if not surface or not lemma:
                    continue
                raw_pos = pick_col(row, ["func_tag", "pos", "part_of_speech", "func_morph"])
                pos = nestle_pos_from_morph(raw_pos)
                morph = pick_col(row, ["morph", "parsing", "form_morph"]) or raw_pos
                csv_tokens.append((surface, lemma, pos, morph))

    db_tokens = conn.execute(
        "SELECT token_seq, surface, lemma FROM tokens WHERE lang = 'greek' ORDER BY token_seq"
    ).fetchall()
    if len(csv_tokens) != len(db_tokens):
        raise RuntimeError(f"Greek token count mismatch: csv={len(csv_tokens)} db={len(db_tokens)}")

    updates = []
    for (seq, db_surf, db_lem), (c_surf, c_lem, pos, morph) in zip(db_tokens, csv_tokens):
        if db_surf != c_surf or db_lem != c_lem:
            raise RuntimeError(f"Token mismatch at seq={seq}: ({db_surf}, {db_lem}) != ({c_surf}, {c_lem})")
        updates.append((pos, morph, seq))

    conn.executemany("UPDATE tokens SET pos = ?, morph_note = ? WHERE token_seq = ?", updates)
    main_pos = compute_main_pos(conn)
    pos_updates = [(pos, lang, lemma) for (lang, lemma), pos in main_pos.items()]
    conn.executemany("UPDATE lemmas SET pos = ? WHERE lang = ? AND lemma = ?", pos_updates)
    g_bench = ingest_dodson_benchmark(conn)
    conn.commit()
    print(f"[BACKFILL] Updated {len(updates):,} Greek tokens, {len(pos_updates):,} lemma POS tags, and {g_bench:,} Greek Dodson benchmark rows.")


def build_lemma_queue(conn: sqlite3.Connection) -> int:
    now = datetime.now(timezone.utc).isoformat()
    pos_counts: dict[tuple[str, str], dict[str, int]] = {}
    for lang, lemma, pos, pcnt in conn.execute("""
        SELECT lang, lemma, pos, COUNT(*) AS pcnt
        FROM tokens
        WHERE pos IS NOT NULL AND pos != ''
        GROUP BY lang, lemma, pos
    """):
        pos_counts.setdefault((lang, lemma), {})[pos] = pcnt

    cur = conn.execute("""
        SELECT
            lang,
            lemma,
            COUNT(*) AS cnt,
            GROUP_CONCAT(DISTINCT book) AS books
        FROM tokens
        GROUP BY lang, lemma
        ORDER BY cnt DESC
    """)
    inserted = 0
    for lang, lemma, cnt, books_str in cur.fetchall():
        pdict = pos_counts.get((lang, lemma), {})
        pos = max(pdict.items(), key=lambda kv: (kv[1], kv[0]))[0] if pdict else ""
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
    parser = argparse.ArgumentParser(description="Ingest primary texts into lexicon.db.")
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="Backfill Greek POS/morph_note, recompute lemmas.pos, and load Dodson benchmark in place.",
    )
    args = parser.parse_args()

    if DB_PATH.exists():
        print(f"[INFO] {DB_PATH.name} already exists. Checking token count...")
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    existing_tokens = conn.execute("SELECT COUNT(*) FROM tokens").fetchone()[0]
    if existing_tokens == 0:
        g_cnt = ingest_nestle1904(conn)
        h_cnt = ingest_wlc(conn)
        d_cnt = ingest_dodson_benchmark(conn)
        l_cnt = build_lemma_queue(conn)
        conn.commit()
        print(f"\n[DONE] Ingested {g_cnt:,} Greek tokens + {h_cnt:,} Hebrew/Aramaic tokens.")
        print(f"[DONE] Created resumable work queue with {l_cnt:,} unique lemmas (+ {d_cnt:,} Greek Dodson benchmark rows).")
    elif args.backfill:
        backfill_metadata(conn)
    else:
        print(f"[SKIP] Database already has {existing_tokens:,} tokens. Run with --backfill to refresh metadata or delete lexicon.db for a full reset.")
    conn.close()


if __name__ == "__main__":
    main()