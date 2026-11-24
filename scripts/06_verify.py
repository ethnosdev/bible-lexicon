#!/usr/bin/env python3
"""Deterministic automated verification for drafted lexicon entries."""

import argparse
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "lexicon.db"
REPORT_PATH = BASE_DIR / "exports" / "verification_report.json"

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "by", "do",
    "does", "for", "from", "had", "has", "have", "he", "her", "him", "his",
    "i", "in", "into", "is", "it", "its", "may", "me", "my", "no", "not",
    "of", "on", "one", "or", "our", "out", "she", "so", "some", "such",
    "than", "that", "the", "their", "them", "then", "there", "these", "they",
    "this", "those", "to", "up", "us", "was", "we", "were", "what", "when",
    "which", "who", "whom", "will", "with", "you", "your", "et", "etc",
    "someone", "something", "person", "thing", "state", "act", "action",
}

FORBIDDEN_LEXICON_RE = re.compile(
    r"\b(BDAG|HALOT|DCH|Louw[- ]Nida|Strong'?s|BDB|Thayer'?s?)\b",
    re.IGNORECASE,
)
STRONGS_CODE_RE = re.compile(r"\b[GH]\d{3,4}\b")
ROOT_FALLACY_RE = re.compile(
    r"(?<!figura )\b(triliteral|three-letter root|3-letter root|biliteral|etymology|etymological)\b",
    re.IGNORECASE,
)

STEM_ALIASES = {
    "qal": ("qal", "simple active", "basic active"),
    "niphal": ("niphal", "simple passive", "medio-passive", "reflexive"),
    "piel": ("piel", "intensive active", "intensive"),
    "pual": ("pual", "intensive passive"),
    "hiphil": ("hiphil", "causative active", "causative"),
    "hophal": ("hophal", "causative passive"),
    "hithpael": ("hithpael", "intensive reflexive", "reflexive"),
    "qal passive": ("qal passive", "simple passive"),
    "polel": ("polel", "poel", "intensive active", "intensive"),
    "polal": ("polal", "poal", "intensive passive"),
    "hithpolel": ("hithpolel", "hithpoel", "reflexive"),
}


def init_verification_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
    CREATE TABLE IF NOT EXISTS verification_reports (
        lemma_id          INTEGER PRIMARY KEY REFERENCES lemmas(lemma_id),
        passed            INTEGER NOT NULL,
        flag_count        INTEGER NOT NULL,
        warning_count     INTEGER NOT NULL,
        flags_json        TEXT NOT NULL,
        warnings_json     TEXT NOT NULL,
        benchmark_score   REAL,
        benchmark_status  TEXT NOT NULL,
        missing_stems_json TEXT NOT NULL,
        checked_at        TEXT NOT NULL
    )
    """)


def stem_word(w: str) -> str:
    w = w.lower().strip()
    for suf in ("ing", "ings", "ed", "es", "ly", "ness", "ment", "tion", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            w = w[: -len(suf)]
            break
    return w


def tokenize_gloss_words(text: str, include_stopwords: bool = False) -> set[str]:
    if not text:
        return set()
    cleaned = re.sub(r"[().\[\]/,;:\"'`\-]+", " ", text.lower())
    return {
        w for w in cleaned.split()
        if (include_stopwords and len(w) >= 1 and w.isalpha())
        or (not include_stopwords and len(w) >= 2 and w not in STOPWORDS)
    }


def words_match(w1: str, w2: str) -> bool:
    if w1 == w2:
        return True
    s1, s2 = stem_word(w1), stem_word(w2)
    if s1 == s2:
        return True
    if len(s1) >= 4 and len(s2) >= 4 and (s1.startswith(s2) or s2.startswith(s1)):
        return True
    return False


def compute_benchmark_alignment(entry: dict, bench_rows: list[tuple[str, str]]) -> tuple[Optional[float], str]:
    if not bench_rows:
        return None, "no_benchmark"

    bench_text = " ".join(
        f"{g or ''} {d or ''}" if entry.get("lang") == "greek" else f"{g or ''}"
        for g, d in bench_rows
    )
    include_sw = False
    bench_words = tokenize_gloss_words(bench_text, include_stopwords=False)
    if not bench_words:
        bench_words = tokenize_gloss_words(bench_text, include_stopwords=True)
        include_sw = True
    if not bench_words:
        return None, "empty_benchmark"

    entry_parts = [entry.get("core_meaning_summary", "")]
    for s in entry.get("senses", []):
        entry_parts.extend(s.get("glosses", []))
        entry_parts.append(s.get("definition", ""))
    entry_words = tokenize_gloss_words(" ".join(entry_parts), include_stopwords=include_sw)

    if not entry_words:
        return 0.0, "empty_entry_glosses"

    matched = sum(1 for bw in bench_words if any(words_match(bw, ew) for ew in entry_words))
    score = round(matched / len(bench_words), 3)
    if matched > 0:
        return score, "aligned"
    return 0.0, "divergent"


def check_entry(conn: sqlite3.Connection, row: tuple) -> dict:
    lemma_id, lang, lemma, pos, total_count, tier, status, entry_json = row
    entry = json.loads(entry_json)

    flags: list[str] = []
    warnings: list[str] = []

    # 1. Schema & required text completeness
    if not str(entry.get("transliteration", "")).strip():
        flags.append("missing_transliteration")
    if not str(entry.get("core_meaning_summary", "")).strip():
        flags.append("missing_summary")

    senses = entry.get("senses", [])
    if not isinstance(senses, list) or not senses:
        flags.append("empty_senses")

    valid_refs = {
        r[0] for r in conn.execute(
            "SELECT DISTINCT ref FROM tokens WHERE lang = ? AND lemma = ?",
            (lang, lemma),
        ).fetchall()
    }

    cited_all: set[str] = set()
    for idx, s in enumerate(senses):
        if not str(s.get("definition", "")).strip():
            flags.append(f"sense_{idx + 1}_empty_definition")
        if not s.get("glosses"):
            flags.append(f"sense_{idx + 1}_empty_glosses")
        refs = s.get("cited_refs", [])
        if not refs:
            flags.append(f"sense_{idx + 1}_no_cited_refs")
        for ref in refs:
            if ref not in valid_refs:
                flags.append(f"invalid_ref:{ref}")
            else:
                cited_all.add(ref)

    if valid_refs and total_count <= 25:
        coverage = len(cited_all) / len(valid_refs)
        if coverage < 0.5:
            warnings.append(f"low_citation_coverage:{len(cited_all)}/{len(valid_refs)}")

    # 2. Confidence & uncertainty note calibration
    conf = str(entry.get("confidence", "")).lower()
    unote = entry.get("uncertainty_note")
    if isinstance(unote, str) and unote.strip().lower() == "null":
        flags.append("literal_null_uncertainty_note")
    if conf in {"low", "medium"} and (not unote or not str(unote).strip()):
        flags.append("missing_uncertainty_note_for_non_high_confidence")
    if total_count == 1 and conf == "high":
        flags.append("single_occ_marked_high")
    elif total_count == 1 and conf == "medium":
        warnings.append("single_occ_marked_medium")

    # 3. Clean-room & rule linting
    all_text_fields = [
        str(entry.get("core_meaning_summary", "")),
        str(entry.get("collocations_and_notes") or ""),
        str(unote or ""),
    ]
    for s in senses:
        all_text_fields.extend([
            str(s.get("grammatical_frame", "")),
            str(s.get("definition", "")),
            " ".join(str(g) for g in s.get("glosses", [])),
        ])
    combined_text = "\n".join(all_text_fields)

    if FORBIDDEN_LEXICON_RE.search(combined_text) or STRONGS_CODE_RE.search(combined_text):
        flags.append("clean_room_lexicon_or_strongs_leak")
    if ROOT_FALLACY_RE.search(combined_text):
        warnings.append("possible_etymology_or_root_language")

    # 4. Hebrew/Aramaic verb stem coverage
    missing_stems: list[str] = []
    if lang in {"hebrew", "aramaic"} and pos == "verb":
        stem_counts = Counter(
            r[0].strip().lower()
            for r in conn.execute(
                "SELECT morph_note FROM tokens WHERE lang = ? AND lemma = ? AND pos = 'verb' AND morph_note != ''",
                (lang, lemma),
            ).fetchall()
        )
        frame_text = " ".join(
            [str(entry.get("collocations_and_notes") or "")]
            + [str(s.get("grammatical_frame", "")) for s in senses]
        ).lower()
        # Require stems with >= 2 occurrences (or sole stem if total_count == 1)
        major_missing: list[str] = []
        minor_missing: list[str] = []
        for stem, cnt in sorted(stem_counts.items()):
            if cnt < 2 and len(stem_counts) > 1:
                continue
            aliases = STEM_ALIASES.get(stem, (stem,))
            if not any(alias in frame_text for alias in aliases):
                tag = f"{stem}({cnt})"
                missing_stems.append(tag)
                if cnt >= 10:
                    major_missing.append(tag)
                else:
                    minor_missing.append(tag)
        if major_missing:
            flags.append("missing_major_verb_stems:" + ",".join(major_missing))
        if minor_missing:
            warnings.append("missing_minor_verb_stems:" + ",".join(minor_missing))

    # 5. Benchmark cross-check
    bench_rows = conn.execute(
        "SELECT DISTINCT hidden_gloss, hidden_domain FROM benchmark_hidden WHERE lang = ? AND lemma = ?",
        (lang, lemma),
    ).fetchall()
    bench_score, bench_status = compute_benchmark_alignment(entry, bench_rows)
    if bench_status == "divergent":
        warnings.append("benchmark_gloss_divergent")

    return {
        "lemma_id": lemma_id,
        "lang": lang,
        "lemma": lemma,
        "pos": pos,
        "total_count": total_count,
        "confidence": conf,
        "passed": len(flags) == 0,
        "flags": flags,
        "warnings": warnings,
        "benchmark_score": bench_score,
        "benchmark_status": bench_status,
        "missing_stems": missing_stems,
    }


def main():
    parser = argparse.ArgumentParser(description="Run deterministic verification checks on drafted entries.")
    parser.add_argument("--tier", type=int, default=1, help="Priority tier to verify (default: 1; use 0 for all).")
    parser.add_argument(
        "--apply-flags",
        action="store_true",
        help="Update lemmas.status to 'needs_review' when hard flags are found (keeps 'verified' for human review).",
    )
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    init_verification_table(conn)
    now = datetime.now(timezone.utc).isoformat()

    where_tier = "AND l.priority_tier = ?" if args.tier > 0 else ""
    params = (args.tier,) if args.tier > 0 else ()
    rows = conn.execute(
        f"""
        SELECT l.lemma_id, l.lang, l.lemma, l.pos, l.total_count, l.priority_tier, l.status, e.entry_json
        FROM lexicon_entries e
        JOIN lemmas l ON l.lemma_id = e.lemma_id
        WHERE l.status IN ('drafted', 'needs_review', 'verified') {where_tier}
        ORDER BY l.lemma_id ASC
        """,
        params,
    ).fetchall()

    results = []
    flag_counts = Counter()
    warning_counts = Counter()
    bench_counts = Counter()
    flagged_for_review = 0

    for row in rows:
        res = check_entry(conn, row)
        results.append(res)
        for fl in res["flags"]:
            flag_counts[fl.split(":")[0]] += 1
        for wr in res["warnings"]:
            warning_counts[wr.split(":")[0]] += 1
        bench_counts[res["benchmark_status"]] += 1

        conn.execute(
            """
            INSERT OR REPLACE INTO verification_reports
            (lemma_id, passed, flag_count, warning_count, flags_json, warnings_json,
             benchmark_score, benchmark_status, missing_stems_json, checked_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                res["lemma_id"],
                1 if res["passed"] else 0,
                len(res["flags"]),
                len(res["warnings"]),
                json.dumps(res["flags"], ensure_ascii=False),
                json.dumps(res["warnings"], ensure_ascii=False),
                res["benchmark_score"],
                res["benchmark_status"],
                json.dumps(res["missing_stems"], ensure_ascii=False),
                now,
            ),
        )

        if args.apply_flags and not res["passed"] and row[6] == "drafted":
            conn.execute(
                "UPDATE lemmas SET status = 'needs_review', updated_at = ? WHERE lemma_id = ?",
                (now, res["lemma_id"]),
            )
            flagged_for_review += 1

    conn.commit()
    conn.close()

    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    clean_no_warn = sum(1 for r in results if r["passed"] and not r["warnings"])
    summary = {
        "generated_at": now,
        "tier": args.tier,
        "total_checked": total,
        "passed_hard_checks": passed,
        "clean_no_warnings": clean_no_warn,
        "flagged_hard_count": total - passed,
        "marked_needs_review": flagged_for_review,
        "benchmark_status_counts": dict(bench_counts),
        "hard_flag_counts": dict(flag_counts),
        "warning_counts": dict(warning_counts),
        "flagged_entries": [r for r in results if not r["passed"] or r["warnings"]],
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"=== VERIFICATION SUMMARY (Tier {args.tier}) ===")
    print(f"Checked: {total:,} | Passed hard checks: {passed:,} | Fully clean (no warnings): {clean_no_warn:,}")
    print(f"Benchmark alignment: {dict(bench_counts)}")
    print(f"Hard flags: {dict(flag_counts)}")
    print(f"Warnings:   {dict(warning_counts)}")
    if args.apply_flags:
        print(f"Marked needs_review: {flagged_for_review:,}")
    print(f"Report saved -> {REPORT_PATH}")


if __name__ == "__main__":
    main()
