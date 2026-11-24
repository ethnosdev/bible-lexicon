const state = {
  overview: null,
  tier1: [],
  tier1Filtered: [],
  selectedT1Id: null,
  preset: "all",
  allLemmas: null,
  allFiltered: [],
  selectedAllId: null,
  expandAllVerses: false,
  openRefs: new Set(),
};

const SAMPLE_THEOLOGY_IDS = new Set([
  1820, // ἐπίσκοπος
  1852, // ὑπερέχω
  3959, // κατατομή
  5756, // אָבַד
  17560, // חֲרִישִׁי
]);

const SAMPLE_THEOLOGY_NORMALIZED = new Set(
  [
    "ἐπίσκοπος", "κενόω", "ὑπερέχω", "πολίτευμα", "κατατομή",
    "אָבַד", "חֲרִישִׁי", "קִיקָיוֹן", "נָחַם", "תְּשׁוּבָה",
  ].map(stripMarks)
);

function stripMarks(str) {
  if (!str) return "";
  return str
    .normalize("NFD")
    .replace(/[\u0300-\u036f\u0591-\u05c7]/g, "")
    .toLowerCase();
}

function escapeHtml(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function formatVerseSentence(sentence) {
  return escapeHtml(sentence).replace(/【([^】]+)】/g, '<mark class="target-token">$1</mark>');
}

function langClass(lang) {
  return lang === "greek" ? "lang-greek" : "lang-hebrew";
}

function confBadgeClass(conf) {
  if (conf === "high") return "badge-good";
  if (conf === "medium") return "badge-warn";
  return "badge-bad";
}

function statusBadgeClass(status) {
  if (status === "verified") return "badge-good";
  if (status === "needs_review") return "badge-bad";
  if (status === "drafted") return "badge-accent";
  return "";
}

function loadScriptBundle(name) {
  return new Promise((resolve, reject) => {
    if (window.__LEXICON_DATA__ && window.__LEXICON_DATA__[name] !== undefined) {
      resolve(window.__LEXICON_DATA__[name]);
      return;
    }
    const script = document.createElement("script");
    script.src = `data/${name}.js`;
    script.onload = () => {
      if (window.__LEXICON_DATA__ && window.__LEXICON_DATA__[name] !== undefined) {
        resolve(window.__LEXICON_DATA__[name]);
      } else {
        reject(new Error(`Bundle data/${name}.js loaded without payload`));
      }
    };
    script.onerror = () => reject(new Error(`Failed to load data/${name}.js`));
    document.head.appendChild(script);
  });
}

async function loadBundle(name) {
  if (window.location.protocol !== "file:") {
    try {
      const res = await fetch(`data/${name}.json`);
      if (res.ok) return await res.json();
    } catch (_) {
      // Fall back to script bundle below
    }
  }
  return await loadScriptBundle(name);
}

async function init() {
  const [overview, tier1] = await Promise.all([
    loadBundle("overview"),
    loadBundle("tier1_entries"),
  ]);
  state.overview = overview;
  state.tier1 = tier1;

  renderOverview();
  populatePosDropdown();
  applyTier1Filters();
  wireEvents();
}

function renderOverview() {
  const ov = state.overview;
  const ver = ov.verification || {};
  const totalChecked = ver.total_checked || state.tier1.length;
  const passedHard = ver.passed_hard_checks ?? state.tier1.length;
  const cleanCount = ver.clean_no_warnings ?? 0;
  const alignedCount = (ver.benchmark_status_counts || {}).aligned || 0;

  const metricsHtml = `
    <div class="stat-tile">
      <div class="stat-label">Tier 1 Pilot Complete</div>
      <div class="stat-value">${state.tier1.length.toLocaleString()}</div>
      <div class="stat-sub">443 Greek (Philippians) + 253 Hebrew (Jonah)</div>
    </div>
    <div class="stat-tile">
      <div class="stat-label">Hard Checks Passed</div>
      <div class="stat-value">${passedHard} / ${totalChecked}</div>
      <div class="stat-sub">${((passedHard / totalChecked) * 100).toFixed(1)}% valid citations, schema &amp; clean-room</div>
    </div>
    <div class="stat-tile">
      <div class="stat-label">Benchmark Alignment</div>
      <div class="stat-value">${alignedCount} / ${totalChecked}</div>
      <div class="stat-sub">${((alignedCount / totalChecked) * 100).toFixed(1)}% aligned with Dodson / Macula</div>
    </div>
    <div class="stat-tile">
      <div class="stat-label">Full Bible Corpus</div>
      <div class="stat-value">${ov.corpus.total_lemmas.toLocaleString()}</div>
      <div class="stat-sub">${ov.corpus.total_tokens.toLocaleString()} tokens across 3 languages</div>
    </div>
  `;
  document.getElementById("overview-metrics").innerHTML = metricsHtml;

  const hardFlags = ver.hard_flag_counts || {};
  const warnings = ver.warning_counts || {};
  document.getElementById("verification-summary-box").innerHTML = `
    <p>
      <strong>Fully clean (no warnings):</strong> ${cleanCount} / ${totalChecked} (${((cleanCount / totalChecked) * 100).toFixed(1)}%)<br/>
      <strong>Auto-flagged <code>needs_review</code>:</strong> ${ver.marked_needs_review ?? 0}
      (${Object.entries(hardFlags).map(([k, v]) => `${escapeHtml(k)}: ${v}`).join(", ") || "none"})<br/>
      <strong>Advisory warnings:</strong>
      ${Object.entries(warnings).map(([k, v]) => `<code>${escapeHtml(k)}</code> (${v})`).join(", ") || "none"}
    </p>
  `;

  const tierNames = {
    1: "Tier 1 — Pilot (Jonah + Philippians)",
    2: "Tier 2 — Core Vocabulary (10+ occurrences)",
    3: "Tier 3 — Medium Frequency (3–9 occurrences)",
    4: "Tier 4 — Rare & Hapax (1–2 occurrences)",
  };
  const rowsHtml = ov.tier_status.map(r => `
    <tr>
      <td>${escapeHtml(tierNames[r.tier] || `Tier ${r.tier}`)}</td>
      <td><span class="badge ${statusBadgeClass(r.status)}">${escapeHtml(r.status)}</span></td>
      <td><strong>${r.count.toLocaleString()}</strong></td>
    </tr>
  `).join("");
  document.getElementById("tier-table-wrap").innerHTML = `
    <table>
      <thead><tr><th>Priority Tier</th><th>Status</th><th>Lemmas</th></tr></thead>
      <tbody>${rowsHtml}</tbody>
    </table>
  `;
}

function populatePosDropdown() {
  const posSet = [...new Set(state.tier1.map(e => e.pos).filter(Boolean))].sort();
  const sel = document.getElementById("t1-pos");
  for (const pos of posSet) {
    const opt = document.createElement("option");
    opt.value = pos;
    opt.textContent = pos;
    sel.appendChild(opt);
  }
}

function applyPresetFilter(entry) {
  switch (state.preset) {
    case "needs_review":
      return entry.status === "needs_review";
    case "divergent":
      return entry.verification.benchmark_status === "divergent";
    case "missing_stems":
      return entry.verification.missing_stems && entry.verification.missing_stems.length > 0;
    case "low_conf":
      return entry.confidence === "low";
    case "sample_theology":
      return SAMPLE_THEOLOGY_IDS.has(entry.lemma_id) || SAMPLE_THEOLOGY_NORMALIZED.has(stripMarks(entry.lemma));
    default:
      return true;
  }
}

function applyTier1Filters() {
  const q = stripMarks(document.getElementById("t1-search").value.trim());
  const lang = document.getElementById("t1-lang").value;
  const book = document.getElementById("t1-book").value;
  const conf = document.getElementById("t1-conf").value;
  const verif = document.getElementById("t1-verif").value;
  const pos = document.getElementById("t1-pos").value;

  state.tier1Filtered = state.tier1.filter(e => {
    if (!applyPresetFilter(e)) return false;
    if (lang && e.lang !== lang) return false;
    if (book && !e.pilot_books.includes(book)) return false;
    if (conf && e.confidence !== conf) return false;
    if (pos && e.pos !== pos) return false;

    if (verif === "clean") {
      if (!e.verification.passed || e.verification.warnings.length > 0) return false;
    } else if (verif === "any_issue") {
      if (e.verification.passed && e.verification.warnings.length === 0) return false;
    } else if (verif === "needs_review") {
      if (e.status !== "needs_review") return false;
    } else if (verif === "divergent") {
      if (e.verification.benchmark_status !== "divergent") return false;
    }

    if (q) {
      const hay = stripMarks([
        String(e.lemma_id),
        e.lemma,
        e.transliteration,
        e.core_meaning_summary,
        ...e.senses.flatMap(s => [s.definition, ...(s.glosses || [])]),
      ].join(" "));
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  document.getElementById("t1-count-label").textContent =
    `Showing ${state.tier1Filtered.length} of ${state.tier1.length} Tier 1 entries`;

  if (!state.tier1Filtered.some(e => e.lemma_id === state.selectedT1Id)) {
    state.selectedT1Id = state.tier1Filtered[0]?.lemma_id ?? null;
    state.openRefs.clear();
  }
  renderTier1List();
  renderTier1Detail();
}

function renderTier1List() {
  const listEl = document.getElementById("t1-list");
  if (state.tier1Filtered.length === 0) {
    listEl.innerHTML = '<div class="empty-state">No entries match your filters.</div>';
    return;
  }

  listEl.innerHTML = state.tier1Filtered.map(e => {
    const active = e.lemma_id === state.selectedT1Id ? "active" : "";
    const hasWarn = !e.verification.passed || e.verification.warnings.length > 0;
    const statusDot = e.status === "needs_review"
      ? '<span class="badge badge-bad">needs_review</span>'
      : hasWarn
        ? '<span class="badge badge-warn">note</span>'
        : "";
    return `
      <div class="lemma-item ${active}" data-id="${e.lemma_id}">
        <div class="lemma-item-top">
          <span class="lemma-word ${langClass(e.lang)}">${escapeHtml(e.lemma)}</span>
          <span class="badge-row">
            ${statusDot}
            <span class="badge ${confBadgeClass(e.confidence)}">${escapeHtml(e.confidence)}</span>
          </span>
        </div>
        <div class="muted" style="font-size:0.78rem;">
          ${escapeHtml(e.transliteration)} · ${escapeHtml(e.pos || "—")} · ${e.total_count}× · ${escapeHtml(e.pilot_books.join("/"))}
        </div>
        <div class="lemma-summary-preview">${escapeHtml(e.core_meaning_summary)}</div>
      </div>
    `;
  }).join("");
}

function renderTier1Detail() {
  const detailEl = document.getElementById("t1-detail");
  const entry = state.tier1Filtered.find(e => e.lemma_id === state.selectedT1Id);
  if (!entry) {
    detailEl.innerHTML = '<div class="empty-state">Select a lemma to inspect its full lexical entry.</div>';
    return;
  }

  const isRtl = entry.lang !== "greek";
  const ver = entry.verification;
  const bScore = ver.benchmark_score !== null && ver.benchmark_score !== undefined
    ? `${Math.round(ver.benchmark_score * 100)}% token overlap`
    : "N/A";

  const sensesHtml = entry.senses.map((s, idx) => {
    const refs = s.cited_refs || [];
    const openInSense = refs.filter(r => state.expandAllVerses || state.openRefs.has(`${entry.lemma_id}:${idx}:${r}`));
    const refsHtml = refs.map(ref => {
      const key = `${entry.lemma_id}:${idx}:${ref}`;
      const isOpen = state.expandAllVerses || state.openRefs.has(key);
      return `<button class="ref-btn ${isOpen ? "open" : ""}" data-ref-key="${escapeHtml(key)}">${escapeHtml(ref)}</button>`;
    }).join("");

    const versesHtml = openInSense.length ? `
      <div class="verse-drawer">
        ${openInSense.map(ref => `
          <div class="verse-box">
            <div class="verse-ref-label">${escapeHtml(ref)}</div>
            <div class="verse-text ${isRtl ? "rtl" : "ltr-greek"}">${formatVerseSentence(entry.verses[ref] || "(Verse text not found)")}</div>
          </div>
        `).join("")}
      </div>
    ` : "";

    return `
      <div class="sense-card">
        <div class="sense-top">
          <div><span class="sense-id">${escapeHtml(s.sense_id)}</span> <strong>${escapeHtml(s.semantic_domain || "")}</strong></div>
        </div>
        <div class="sense-frame">${escapeHtml(s.grammatical_frame || "")}</div>
        <div class="sense-def">${escapeHtml(s.definition || "")}</div>
        <div class="gloss-list">
          ${(s.glosses || []).map(g => `<span class="gloss-pill">${escapeHtml(g)}</span>`).join("")}
        </div>
        <div class="refs-bar">
          <span class="muted" style="font-size:0.78rem;">Cited refs (click to view verse):</span>
          ${refsHtml}
        </div>
        ${versesHtml}
      </div>
    `;
  }).join("");

  const citedSet = new Set(entry.senses.flatMap(s => s.cited_refs || []));
  const extraRefs = Object.keys(entry.verses).filter(r => !citedSet.has(r));
  const extraHtml = extraRefs.length ? `
    <div class="section-block">
      <h3>Additional Sampled Occurrences (${extraRefs.length})</h3>
      <div class="verse-drawer">
        ${extraRefs.map(ref => `
          <div class="verse-box">
            <div class="verse-ref-label">${escapeHtml(ref)}</div>
            <div class="verse-text ${isRtl ? "rtl" : "ltr-greek"}">${formatVerseSentence(entry.verses[ref])}</div>
          </div>
        `).join("")}
      </div>
    </div>
  ` : "";

  const bRef = entry.benchmark_ref || {};
  detailEl.innerHTML = `
    <div class="entry-header">
      <div>
        <div class="entry-headword ${langClass(entry.lang)}" ${isRtl ? 'dir="rtl"' : ""}>${escapeHtml(entry.lemma)}</div>
        <div class="entry-translit">${escapeHtml(entry.transliteration)}</div>
      </div>
      <div class="badge-row">
        <span class="badge">#${entry.lemma_id}</span>
        <span class="badge">${escapeHtml(entry.lang)}</span>
        <span class="badge">${escapeHtml(entry.pos || "—")}</span>
        <span class="badge">${entry.total_count.toLocaleString()} occ.</span>
        <span class="badge">${escapeHtml(entry.pilot_books.join(", "))}</span>
        <span class="badge ${statusBadgeClass(entry.status)}">${escapeHtml(entry.status)}</span>
        <span class="badge ${confBadgeClass(entry.confidence)}">confidence: ${escapeHtml(entry.confidence)}</span>
      </div>
    </div>

    <div class="section-block">
      <h3>Core Meaning Summary</h3>
      <div class="core-summary">${escapeHtml(entry.core_meaning_summary)}</div>
    </div>

    <div class="section-block">
      <h3>Empirical Senses (${entry.senses.length})</h3>
      ${sensesHtml}
    </div>

    ${entry.collocations_and_notes ? `
      <div class="section-block">
        <h3>Collocations &amp; Grammatical Notes</h3>
        <p style="margin:0;">${escapeHtml(entry.collocations_and_notes)}</p>
      </div>
    ` : ""}

    ${entry.uncertainty_note ? `
      <div class="section-block">
        <h3>Uncertainty Note</h3>
        <div class="uncertainty-box">${escapeHtml(entry.uncertainty_note)}</div>
      </div>
    ` : ""}

    ${extraHtml}

    <div class="section-block">
      <h3>Automated Verification &amp; Reference Benchmark</h3>
      <div class="verif-panel">
        <div class="badge-row">
          <span class="badge ${ver.passed ? "badge-good" : "badge-bad"}">
            ${ver.passed ? "Hard Checks Passed" : "Flagged for Review"}
          </span>
          <span class="badge ${ver.benchmark_status === "aligned" ? "badge-good" : "badge-warn"}">
            Benchmark: ${escapeHtml(ver.benchmark_status)} (${bScore})
          </span>
          ${ver.flags.map(f => `<span class="badge badge-bad">${escapeHtml(f)}</span>`).join("")}
          ${ver.warnings.map(w => `<span class="badge badge-warn">${escapeHtml(w)}</span>`).join("")}
        </div>
        <div class="bench-drawer">
          <button class="btn btn-sm" id="toggle-bench-btn">Show Reference Benchmark (${escapeHtml(bRef.license || "ref")})</button>
          <div id="bench-content" class="bench-box" style="display:none;">
            <div><strong>Source:</strong> ${escapeHtml(bRef.source || "—")}</div>
            <div><strong>Benchmark glosses:</strong> ${escapeHtml((bRef.glosses || []).join("; ") || "None")}</div>
            ${bRef.detail ? `<div style="margin-top:0.25rem;"><strong>Extended note:</strong> ${escapeHtml(bRef.detail)}</div>` : ""}
            <div class="muted" style="margin-top:0.35rem; font-size:0.78rem;">
              Strictly isolated from the AI during drafting and excluded from CC0 exports. Provided here only for expert verification.
            </div>
          </div>
        </div>
      </div>
    </div>
  `;
}

async function ensureAllLemmasLoaded() {
  if (state.allLemmas) return;
  state.allLemmas = await loadBundle("all_lemmas");
  applyAllLemmasFilter();
}

function applyAllLemmasFilter() {
  if (!state.allLemmas) return;
  const q = stripMarks(document.getElementById("all-search").value.trim());
  const lang = document.getElementById("all-lang").value;
  const tier = document.getElementById("all-tier").value;
  const status = document.getElementById("all-status").value;

  state.allFiltered = state.allLemmas.filter(item => {
    if (lang && item.lang !== lang) return false;
    if (tier && String(item.tier) !== tier) return false;
    if (status && item.status !== status) return false;
    if (q) {
      const hay = stripMarks([String(item.id), item.lemma, item.tr || "", item.sum || ""].join(" "));
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  document.getElementById("all-count-label").textContent =
    `${state.allFiltered.length.toLocaleString()} matching lemmas (of ${state.allLemmas.length.toLocaleString()})`;

  if (!state.allFiltered.slice(0, 150).some(x => x.id === state.selectedAllId)) {
    state.selectedAllId = state.allFiltered[0]?.id ?? null;
  }
  renderAllList();
  renderAllDetail();
}

function renderAllList() {
  const listEl = document.getElementById("all-list");
  const slice = state.allFiltered.slice(0, 150);
  if (slice.length === 0) {
    listEl.innerHTML = '<div class="empty-state">No lemmas match your query.</div>';
    return;
  }
  listEl.innerHTML = slice.map(item => `
    <div class="lemma-item ${item.id === state.selectedAllId ? "active" : ""}" data-all-id="${item.id}">
      <div class="lemma-item-top">
        <span class="lemma-word ${langClass(item.lang)}">${escapeHtml(item.lemma)}</span>
        <span class="badge-row">
          <span class="badge">T${item.tier}</span>
          <span class="badge ${statusBadgeClass(item.status)}">${escapeHtml(item.status)}</span>
        </span>
      </div>
      <div class="muted" style="font-size:0.78rem;">
        #${item.id} · ${escapeHtml(item.lang)} · ${escapeHtml(item.pos || "—")} · ${item.cnt.toLocaleString()}×
      </div>
      ${item.sum ? `<div class="lemma-summary-preview">${escapeHtml(item.sum)}</div>` : ""}
    </div>
  `).join("");
}

function renderAllDetail() {
  const el = document.getElementById("all-detail");
  const item = state.allFiltered.find(x => x.id === state.selectedAllId);
  if (!item) {
    el.innerHTML = '<div class="empty-state">Select a lemma to inspect its dataset record.</div>';
    return;
  }

  const isRtl = item.lang !== "greek";
  const t1Entry = state.tier1.find(e => e.lemma_id === item.id);
  const samples = item.samples || [];

  el.innerHTML = `
    <div class="entry-header">
      <div>
        <div class="entry-headword ${langClass(item.lang)}" ${isRtl ? 'dir="rtl"' : ""}>${escapeHtml(item.lemma)}</div>
        ${item.tr ? `<div class="entry-translit">${escapeHtml(item.tr)}</div>` : ""}
      </div>
      <div class="badge-row">
        <span class="badge">#${item.id}</span>
        <span class="badge">${escapeHtml(item.lang)}</span>
        <span class="badge">${escapeHtml(item.pos || "—")}</span>
        <span class="badge">${item.cnt.toLocaleString()} occurrences</span>
        <span class="badge">Tier ${item.tier}</span>
        <span class="badge ${statusBadgeClass(item.status)}">${escapeHtml(item.status)}</span>
      </div>
    </div>
    ${t1Entry ? `
      <div class="section-block">
        <h3>Tier 1 Drafted Summary</h3>
        <div class="core-summary">${escapeHtml(t1Entry.core_meaning_summary)}</div>
        <div style="margin-top:0.85rem;">
          <button class="btn btn-primary" data-open-t1="${item.id}">Open Full Tier 1 Entry &amp; All Cited Verses</button>
        </div>
      </div>
    ` : `
      <div class="section-block">
        <h3>Queued for Empirical Analysis (Tier ${item.tier})</h3>
        <p class="muted">This lemma has not been analyzed yet. Below are sample primary-text verses from the corpus:</p>
        <div class="verse-drawer">
          ${samples.map(s => `
            <div class="verse-box">
              <div class="verse-ref-label">${escapeHtml(s.ref)}</div>
              <div class="verse-text ${isRtl ? "rtl" : "ltr-greek"}">${formatVerseSentence(s.text)}</div>
            </div>
          `).join("")}
        </div>
      </div>
    `}
  `;
}

function switchTab(tabName) {
  document.querySelectorAll(".tab-btn").forEach(b => b.classList.toggle("active", b.dataset.tab === tabName));
  document.querySelectorAll(".tab-panel").forEach(p => p.classList.toggle("active", p.id === `tab-${tabName}`));
  if (tabName === "corpus") ensureAllLemmasLoaded();
}

function setPreset(preset) {
  state.preset = preset;
  document.querySelectorAll(".preset-btn").forEach(b => b.classList.toggle("active", b.dataset.preset === preset));
  applyTier1Filters();
}

function wireEvents() {
  document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
  });

  document.querySelectorAll("[data-jump-preset]").forEach(btn => {
    btn.addEventListener("click", () => {
      switchTab("tier1");
      setPreset(btn.dataset.jumpPreset);
    });
  });

  document.querySelectorAll(".preset-btn").forEach(btn => {
    btn.addEventListener("click", () => setPreset(btn.dataset.preset));
  });

  ["t1-search", "t1-lang", "t1-book", "t1-conf", "t1-verif", "t1-pos"].forEach(id => {
    document.getElementById(id).addEventListener("input", applyTier1Filters);
    document.getElementById(id).addEventListener("change", applyTier1Filters);
  });

  document.getElementById("toggle-expand-verses").addEventListener("change", (ev) => {
    state.expandAllVerses = ev.target.checked;
    renderTier1Detail();
  });

  document.getElementById("t1-list").addEventListener("click", (ev) => {
    const item = ev.target.closest("[data-id]");
    if (!item) return;
    state.selectedT1Id = Number(item.dataset.id);
    state.openRefs.clear();
    renderTier1List();
    renderTier1Detail();
  });

  document.getElementById("t1-detail").addEventListener("click", (ev) => {
    const refBtn = ev.target.closest("[data-ref-key]");
    if (refBtn) {
      const key = refBtn.dataset.refKey;
      if (state.openRefs.has(key)) state.openRefs.delete(key);
      else state.openRefs.add(key);
      renderTier1Detail();
      return;
    }
    if (ev.target.id === "toggle-bench-btn") {
      const box = document.getElementById("bench-content");
      const open = box.style.display === "none";
      box.style.display = open ? "block" : "none";
      ev.target.textContent = open ? "Hide Reference Benchmark" : "Show Reference Benchmark";
    }
  });

  ["all-search", "all-lang", "all-tier", "all-status"].forEach(id => {
    document.getElementById(id).addEventListener("input", applyAllLemmasFilter);
    document.getElementById(id).addEventListener("change", applyAllLemmasFilter);
  });

  document.getElementById("all-list").addEventListener("click", (ev) => {
    const item = ev.target.closest("[data-all-id]");
    if (!item) return;
    state.selectedAllId = Number(item.dataset.allId);
    renderAllList();
    renderAllDetail();
  });

  document.getElementById("all-detail").addEventListener("click", (ev) => {
    const btn = ev.target.closest("[data-open-t1]");
    if (!btn) return;
    const lid = Number(btn.dataset.openT1);
    setPreset("all");
    document.getElementById("t1-search").value = "";
    document.getElementById("t1-lang").value = "";
    document.getElementById("t1-book").value = "";
    document.getElementById("t1-conf").value = "";
    document.getElementById("t1-verif").value = "";
    document.getElementById("t1-pos").value = "";
    state.selectedT1Id = lid;
    applyTier1Filters();
    switchTab("tier1");
  });
}

init().catch(err => {
  console.error(err);
  document.getElementById("overview-metrics").innerHTML =
    `<div class="card">Failed to load site data. Serve <code>site/</code> over HTTP (e.g., <code>python3 -m http.server -d site 8000</code>).</div>`;
});
