#!/usr/bin/env python3
"""Generate JSON data bundles for the static expert review website in site/data/."""

import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "lexicon.db"
SITE_DATA_DIR = BASE_DIR / "site" / "data"
VERIF_REPORT_PATH = BASE_DIR / "exports" / "verification_report.json"


def build_verse_sentence(conn: sqlite3.Connection, ref: str, lang: str, target_lemma: str) -> str:
    rows = conn.execute(
        "SELECT surface, lemma FROM tokens WHERE ref = ? AND lang = ? ORDER BY token_seq",
        (ref, lang),
    ).fetchall()
    return " ".join(f"【{surf}】" if lem == target_lemma else surf for surf, lem in rows)


def sample_list(items: list, max_items: int) -> list:
    if len(items) <= max_items:
        return items
    step = len(items) / max_items
    return [items[int(i * step)] for i in range(max_items)]


def write_dual_bundle(name: str, payload: object, pretty: bool = False) -> None:
    """Write both .json (for HTTP fetch) and .js (for file:// fallback without CORS)."""
    json_text = json.dumps(payload, indent=2 if pretty else None, ensure_ascii=False)
    json_path = SITE_DATA_DIR / f"{name}.json"
    js_path = SITE_DATA_DIR / f"{name}.js"
    json_path.write_text(json_text + "\n", encoding="utf-8")
    js_path.write_text(
        f"window.__LEXICON_DATA__ = window.__LEXICON_DATA__ || {{}};\n"
        f"window.__LEXICON_DATA__[{json.dumps(name)}] = {json_text};\n",
        encoding="utf-8",
    )


def main():
    SITE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    now = datetime.now(timezone.utc).isoformat()

    # 1. Overview & Scorecard
    lang_stats = [
        {"lang": r[0], "tokens": r[1], "books": r[2], "lemmas": r[3]}
        for r in conn.execute(
            "SELECT lang, COUNT(*), COUNT(DISTINCT book), COUNT(DISTINCT lemma) FROM tokens GROUP BY lang ORDER BY lang"
        ).fetchall()
    ]
    tier_status = [
        {"tier": r[0], "status": r[1], "count": r[2]}
        for r in conn.execute(
            "SELECT priority_tier, status, COUNT(*) FROM lemmas GROUP BY priority_tier, status ORDER BY priority_tier, status"
        ).fetchall()
    ]
    verif_summary = {}
    if VERIF_REPORT_PATH.exists():
        raw_rep = json.loads(VERIF_REPORT_PATH.read_text(encoding="utf-8"))
        verif_summary = {k: v for k, v in raw_rep.items() if k != "flagged_entries"}

    overview = {
        "generated_at": now,
        "corpus": {
            "total_tokens": sum(x["tokens"] for x in lang_stats),
            "total_lemmas": sum(x["lemmas"] for x in lang_stats),
            "by_language": lang_stats,
        },
        "tier_status": tier_status,
        "verification": verif_summary,
    }
    write_dual_bundle("overview", overview, pretty=True)

    # 2. Tier 1 Full Entries + Cited/Sampled Verses + Verification + Benchmark Reference
    tier1_rows = conn.execute("""
        SELECT l.lemma_id, l.lang, l.lemma, l.pos, l.total_count, l.priority_tier, l.status,
               e.entry_json,
               v.passed, v.flags_json, v.warnings_json, v.benchmark_score, v.benchmark_status, v.missing_stems_json
        FROM lemmas l
        JOIN lexicon_entries e ON e.lemma_id = l.lemma_id
        LEFT JOIN verification_reports v ON v.lemma_id = l.lemma_id
        WHERE l.priority_tier = 1
        ORDER BY l.lemma_id ASC
    """).fetchall()

    # Preload benchmark_hidden for Tier 1 lemmas
    bench_map: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for lang, lemma, gloss, domain in conn.execute("""
        SELECT DISTINCT b.lang, b.lemma, b.hidden_gloss, b.hidden_domain
        FROM benchmark_hidden b
        JOIN lemmas l ON l.lang = b.lang AND l.lemma = b.lemma
        WHERE l.priority_tier = 1
    """):
        if gloss or domain:
            bench_map.setdefault((lang, lemma), []).append((gloss or "", domain or ""))

    # Preload pilot books (JON / PHP) per Tier 1 lemma
    pilot_books_map: dict[tuple[str, str], list[str]] = {}
    for lang, lemma, bk in conn.execute("""
        SELECT DISTINCT t.lang, t.lemma, t.book
        FROM tokens t
        JOIN lemmas l ON l.lang = t.lang AND l.lemma = t.lemma
        WHERE l.priority_tier = 1 AND t.book IN ('JON', 'PHP')
        ORDER BY t.book
    """):
        pilot_books_map.setdefault((lang, lemma), []).append(bk)

    tier1_entries = []
    for row in tier1_rows:
        (
            lemma_id, lang, lemma, pos, total_count, tier, status, entry_json,
            v_passed, v_flags_json, v_warnings_json, v_bscore, v_bstatus, v_mstems_json
        ) = row
        entry = json.loads(entry_json)

        cited_refs: list[str] = []
        seen_refs: set[str] = set()
        for s in entry.get("senses", []):
            for ref in s.get("cited_refs", []):
                if ref not in seen_refs:
                    seen_refs.add(ref)
                    cited_refs.append(ref)

        # Also include up to 6 sampled refs if few refs are cited
        if len(cited_refs) < 6:
            all_occ_refs = [
                r[0] for r in conn.execute(
                    "SELECT DISTINCT ref FROM tokens WHERE lang = ? AND lemma = ? ORDER BY token_seq",
                    (lang, lemma),
                ).fetchall()
            ]
            for ref in sample_list(all_occ_refs, 6):
                if ref not in seen_refs:
                    seen_refs.add(ref)
                    cited_refs.append(ref)

        verses = {
            ref: build_verse_sentence(conn, ref, lang, lemma)
            for ref in cited_refs
        }

        b_rows = bench_map.get((lang, lemma), [])
        glosses_clean = list(dict.fromkeys(g for g, _ in b_rows if g))
        if lang == "greek":
            bench_ref = {
                "source": "Dodson Greek Lexicon (Public Domain / CC0)",
                "license": "CC0-1.0",
                "glosses": glosses_clean[:8],
                "detail": " | ".join(dict.fromkeys(d for _, d in b_rows if d))[:500],
            }
        else:
            bench_ref = {
                "source": "Clear-Bible / macula-hebrew (CC BY 4.0 — verification reference only)",
                "license": "CC-BY-4.0",
                "glosses": glosses_clean[:12],
                "detail": "",
            }

        tier1_entries.append({
            "lemma_id": lemma_id,
            "lemma": entry.get("lemma", lemma),
            "lang": lang,
            "transliteration": entry.get("transliteration", ""),
            "pos": pos,
            "total_count": total_count,
            "status": status,
            "pilot_books": pilot_books_map.get((lang, lemma), []),
            "confidence": entry.get("confidence", "medium"),
            "core_meaning_summary": entry.get("core_meaning_summary", ""),
            "senses": entry.get("senses", []),
            "collocations_and_notes": entry.get("collocations_and_notes"),
            "uncertainty_note": entry.get("uncertainty_note"),
            "verification": {
                "passed": bool(v_passed) if v_passed is not None else True,
                "flags": json.loads(v_flags_json) if v_flags_json else [],
                "warnings": json.loads(v_warnings_json) if v_warnings_json else [],
                "benchmark_score": v_bscore,
                "benchmark_status": v_bstatus or "unknown",
                "missing_stems": json.loads(v_mstems_json) if v_mstems_json else [],
            },
            "verses": verses,
            "benchmark_ref": bench_ref,
        })

    write_dual_bundle("tier1_entries", tier1_entries, pretty=False)

    # 3. Full 14,042-Lemma Index (compact + up to 2 sample primary-text refs for pending inspection)
    # Preload sample refs & verses efficiently in bulk
    all_lemmas = conn.execute("""
        SELECT l.lemma_id, l.lang, l.lemma, l.pos, l.total_count, l.priority_tier, l.status
        FROM lemmas l
        ORDER BY l.priority_tier ASC, l.total_count DESC, l.lemma_id ASC
    """).fetchall()

    # Map (lang, lemma) -> up to 2 sample refs
    sample_refs_map: dict[tuple[str, str], list[str]] = {}
    needed_refs: set[tuple[str, str]] = set()
    for lang, lemma, ref in conn.execute("""
        SELECT lang, lemma, ref
        FROM (
            SELECT lang, lemma, ref,
                   ROW_NUMBER() OVER (PARTITION BY lang, lemma ORDER BY MIN(token_seq)) AS rn
            FROM tokens
            GROUP BY lang, lemma, ref
        )
        WHERE rn <= 2
    """):
        sample_refs_map.setdefault((lang, lemma), []).append(ref)
        needed_refs.add((lang, ref))

    # Build verse token lists once for all needed (lang, ref) pairs
    verse_tokens_map: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for lang, ref, surf, lem in conn.execute("""
        SELECT lang, ref, surface, lemma
        FROM tokens
        ORDER BY token_seq
    """):
        if (lang, ref) in needed_refs:
            verse_tokens_map.setdefault((lang, ref), []).append((surf, lem))

    tier1_summaries = {
        e["lemma_id"]: {
            "tr": e["transliteration"],
            "sum": e["core_meaning_summary"],
            "conf": e["confidence"],
        }
        for e in tier1_entries
    }

    full_index = []
    for lid, lang, lemma, pos, cnt, tier, status in all_lemmas:
        samples = []
        if lid not in tier1_summaries:
            for ref in sample_refs_map.get((lang, lemma), []):
                toks = verse_tokens_map.get((lang, ref), [])
                sent = " ".join(f"【{s}】" if lm == lemma else s for s, lm in toks)
                samples.append({"ref": ref, "text": sent})
        t1 = tier1_summaries.get(lid)
        rec = {
            "id": lid,
            "lang": lang,
            "lemma": lemma,
            "pos": pos or "",
            "cnt": cnt,
            "tier": tier,
            "status": status,
        }
        if t1:
            rec["tr"] = t1["tr"]
            rec["sum"] = t1["sum"]
            rec["conf"] = t1["conf"]
        else:
            rec["samples"] = samples
        full_index.append(rec)

    write_dual_bundle("all_lemmas", full_index, pretty=False)
    conn.close()

    for fname in ("overview.json", "tier1_entries.json", "all_lemmas.json"):
        p = SITE_DATA_DIR / fname
        size_mb = p.stat().st_size / (1024 * 1024)
        print(f"[SITE DATA] {fname}: {size_mb:.2f} MB")


if __name__ == "__main__":
    main()
