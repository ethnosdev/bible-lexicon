# Empirical Public-Domain Biblical Lexicon (Hebrew, Aramaic & Greek)

An open, corpus-driven lexicon covering every Hebrew, Aramaic, and Greek lemma in the Bible—derived empirically from primary ancient texts using AI-assisted distributional analysis and released into the **Public Domain (`CC0 1.0`)**.

---

## Why This Project Exists

Biblical students, translators, and software builders face an awkward gap in lexical resources:
* **Modern scholarly lexicons** (e.g., BDAG, HALOT, DCH) are high quality, but strictly copyrighted and expensive—locking them out of open Bible apps, global translation tools, and public datasets.
* **Classic public-domain lexicons** (e.g., Strong’s, BDB, Thayer’s) are over a century old and frequently rely on outdated 19th-century comparative philology and "root fallacies."

This project takes a different approach: **empirical, clean-room lexicography.** Rather than asking an AI to recite memorized dictionaries, the pipeline forces the model to act strictly as a primary-text analyst—grouping usages, identifying grammatical frames, surfacing poetic parallels, and flagging genuine uncertainty directly from the ancient sentences themselves.

---

## Core Principles & Guardrails

1. **Public Domain (`CC0 1.0`) by Design:** All scripts, schemas, and generated lexicon entries are dedicated to the public domain with zero attribution hurdles or commercial restrictions.
2. **Clean-Room Empirical Discipline:** The AI is prohibited from imitating copyrighted lexicons or relying on theological presuppositions. Every sense must cite exact verse references from the provided evidence packet.
3. **No Root Fallacy:** Meanings are derived from contextual syntax and usage—not speculative breakdown of compound words or three-letter roots.
4. **Honest Uncertainty:** Words appearing only once or twice (*hapax legomena*) whose exact meaning cannot be determined from biblical context alone are explicitly marked `"confidence": "low"` with an explanation of what context narrows down vs. what remains uncertain.
5. **Automated Anti-Hallucination Checks:** Every generated entry is programmatically verified before saving—confirming valid JSON structure and checking that every cited verse actually contains the target lemma.

---

## Primary Sources & Licensing Hygiene

To keep the final published lexicon cleanly in the Public Domain (`CC0`), source inputs are strictly separated from any third-party `CC BY` annotations:

* **Greek New Testament:** [Nestle 1904](https://github.com/biblicalhumanities/Nestle1904) Greek text (**Public Domain**) with Ulrik Sandborg-Petersen’s morphological analysis (**CC0**).
* **Hebrew & Aramaic Old Testament:** Westminster Leningrad Codex (**WLC**, **Public Domain**). Internal verse grouping uses [Clear-Bible/macula-hebrew](https://github.com/Clear-Bible/macula-hebrew) TSVs during preprocessing, while stripping and isolating all third-party glosses, semantic domain tags, and morphology code strings into a hidden benchmark table (`benchmark_hidden`) that is never shown to the AI and never exported into the published lexicon.

---

## How the Pipeline Works

The project uses a **resumable SQLite "save-game" architecture** (`lexicon.db`) designed to run incrementally across weekly AI credit quotas without losing progress:

```text
raw_data/           -> Primary texts (Nestle 1904 CC0 + WLC Public Domain)
scripts/
  ├── 01_ingest.py  -> Builds SQLite queue & isolates hidden benchmark glosses ($0)
  ├── 02_export.py  -> Packs next batch of pending words into batches/current_batch.md ($0)
  ├── 03_import.py  -> Validates AI JSON & verse citations, commits to lexicon.db ($0)
  ├── 04_status.py  -> Displays completion progress across tiers ($0)
  └── 05_publish.py -> Exports clean CC0 deliverables (JSON/JSONL) to exports/ ($0)
GEMINI.md           -> Strict lexicographer rules & JSON output schema for the AI agent
batches/            -> Outgoing primary-text evidence packets
inbox/              -> Incoming AI JSON responses awaiting validation
lexicon.db          -> Master SQLite database & resumable state queue
exports/            -> Published public-domain outputs
```

### Priority Tiers
Words are processed in four practical milestones:
* **Tier 1 — Pilot (~400 lemmas):** Every word occurring in **Jonah** (OT) and **Philippians** (NT) to validate quality end-to-end across both testaments.
* **Tier 2 — Core Vocabulary (10+ occurrences):** Covers roughly 85–90% of all running words in the Bible.
* **Tier 3 — Medium Frequency (3–9 occurrences):** Packed 4 lemmas per batch.
* **Tier 4 — Rare & *Hapax Legomena* (1–2 occurrences):** Packed 15 lemmas per batch.

---

## Status & Verification Workflow

Entries in `lexicon.db` move through explicit verification states:
* `pending` — Queued for analysis.
* `exported` — Currently in an active batch (automatically resumed if a session is interrupted).
* `drafted` — Generated empirically and passed automated JSON + verse-citation checks.
* `needs_review` — Flagged automatically (e.g., single-occurrence words marked high confidence) for human review.
* `verified` — Audited by human reviewers against primary texts and public-domain/standard reference benchmarks.

> **Transparency Note:** Until an entry reaches `verified`, treat `drafted` entries as AI-synthesized corpus analyses subject to scholarly review—especially for rare flora, fauna, architectural terms, and technical nouns.

---

## Quick Usage

Check overall progress at any time:
```bash
python3 scripts/04_status.py
```

Export the next batch manually:
```bash
python3 scripts/02_export.py
```

Validate and save an AI response from `inbox/response.json`:
```bash
python3 scripts/03_import.py
```

Publish clean public-domain outputs (`exports/lexicon.json` and `exports/lexicon.jsonl`):
```bash
python3 scripts/05_publish.py
```

---

## License

To the extent possible under law, the authors and contributors waive all copyright and related or neighboring rights to this work under the **CC0 1.0 Universal (Public Domain Dedication)**. See `LICENSE` for details.

## Acknowledgments

* **biblicalhumanities/Nestle1904** for providing the Public Domain Nestle 1904 text and CC0 morphological dataset.
* **The Westminster Leningrad Codex (WLC)** maintainers for preserving and freely sharing the Public Domain Hebrew/Aramaic text.
* **Clear Bible (`macula-hebrew`)** for open-source Hebrew text tooling used internally during initial verse alignment.
