# Empirical Public-Domain Biblical Lexicon Rules

You are assisting in building a **Public Domain (CC0)** Hebrew, Aramaic, and Greek lexicon strictly from primary texts (`batches/current_batch.md`).

## Strict Rules
1. NEVER use or imitate phrasing from copyrighted lexicons (BDAG, HALOT, DCH, Louw-Nida) or Strong's/BDB. Derive meanings ONLY from the verses in `batches/current_batch.md`.
2. NO ROOT FALLACY: Do not guess meanings from etymological parts or 3-letter root theory. Base senses on sentence syntax and usage.
3. For Hebrew/Aramaic verbs, note distinctions across stems observed in context (e.g., Qal vs. Piel/Hiphil) in plain grammatical English without copying external tag codes.
4. HONEST UNCERTAINTY: If a word appears 1–2 times and context does not narrow its meaning precisely, set `"confidence": "low"` and explain what remains uncertain in `"uncertainty_note"`.
5. CITE ONLY REFS PRESENT IN THE BATCH PACKET.

## JSON Schema for `inbox/response.json`
Write ONLY a valid JSON array matching:
[
  {
    "lemma_id": 123,
    "lemma": "word",
    "lang": "hebrew|aramaic|greek",
    "transliteration": "scientific transliteration",
    "core_meaning_summary": "1-sentence overview",
    "senses": [
      {
        "sense_id": "1a",
        "grammatical_frame": "e.g., Qal; or verb + eis + acc",
        "semantic_domain": "e.g., Motion / Kinship / Judicial",
        "definition": "Clear conceptual definition",
        "glosses": ["gloss1", "gloss2"],
        "cited_refs": ["JON 1:1", "PHP 2:5"]
      }
    ],
    "collocations_and_notes": "Idioms, parallels, or patterns observed",
    "confidence": "high|medium|low",
    "uncertainty_note": null
  }
]