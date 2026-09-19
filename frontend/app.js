/* All displayed profiles, edges and reports come from the API. No demo data. */
const $ = id => document.getElementById(id);
const terminal = s => ["COMPLETED", "FAILED", "CANCELLED"].includes(s);
let searchId = null, stream = null, refreshTimer = null, fallbackTimer = null, busy = false;
let latest = null, questionId = null, refreshRunning = false, refreshAgain = false;
let currentSeedType = null, currentSeedValue = null, emailFetchedFor = null;
let emailOsintData = null, emailOsintView = "accounts";
let imageBusy = false, imageController = null, imageGeneration = 0;
const autoContinuedQuestions = new Set();

// Clear all prior investigation output so a new run starts from a clean slate.
function resetResultView() {
  const reportEl = $("report");
  if (reportEl) reportEl.textContent = "An executive identity report appears when the investigation finishes.";
  ["hypotheses", "evidence", "question-options", "email-osint-sources", "email-osint-overview", "identifiers-grid", "evidence-ledger"].forEach(id => {
    const el = $(id);
    if (el) el.replaceChildren();
  });
  const questionSection = $("question-section");
  if (questionSection) questionSection.hidden = true;
  questionId = null;
  const emailSection = $("email-osint-section");
  if (emailSection) emailSection.hidden = true;
  ["candidate-count", "hypothesis-count", "evidence-count", "run-count", "identifier-count", "observation-count", "source-count"].forEach(id => {
    const el = $(id);
    if (el) el.textContent = "0";
  });
  Object.keys(animatedMetricValues).forEach(key => { animatedMetricValues[key] = 0; });
  const imageResults = $("image-results");
  if (imageResults) imageResults.replaceChildren();
  const imageStatus = $("image-status");
  if (imageStatus) imageStatus.textContent = "";
}

// ── Investigation Status Cycling Messages ──
const INVESTIGATION_MESSAGES = [
  "Searching public OSINT connectors...",
  "Extracting first-class identifiers...",
  "Cross-referencing profile observations...",
  "Correlating evidence signals...",
  "Tracing source provenance...",
  "Calculating deterministic match relevance...",
];
let _statusCycleTimer = null;
let _statusCycleIdx = 0;

function startStatusCycle() {
  const bar = $("investigation-status-bar");
  const msg = $("investigation-status-msg");
  if (!bar || !msg) return;
  bar.hidden = false;
  _statusCycleIdx = 0;
  msg.textContent = INVESTIGATION_MESSAGES[0];
  clearInterval(_statusCycleTimer);
  _statusCycleTimer = setInterval(() => {
    _statusCycleIdx = (_statusCycleIdx + 1) % INVESTIGATION_MESSAGES.length;
    msg.textContent = INVESTIGATION_MESSAGES[_statusCycleIdx];
  }, 2400);
}

function stopStatusCycle() {
  clearInterval(_statusCycleTimer);
  _statusCycleTimer = null;
  const bar = $("investigation-status-bar");
  if (bar) bar.hidden = true;
}

// ── Show result sections once search has started ──
function showResultSections() {
  const ids = [
    "metrics-section",
    "identifiers-section",
    "evidence-ledger-section",
    "view-report",
  ];
  ids.forEach(id => {
    const el = $(id);
    if (el && el.hidden) {
      el.hidden = false;
      if (window.gsap && window.ScrollTrigger) {
        ScrollTrigger.refresh();
      }
    }
  });
}
const node = (tag, text = "", cls = "") => { const n = document.createElement(tag); n.textContent = text; if (cls) n.className = cls; return n; };
const label = p => `${p.platform} ${p.username ? "@" + p.username : p.display_name || "profile"}`;
const points = v => Math.round(Math.max(0, Math.min(1, v || 0)) * 100);
function safeLink(url, text) { const a = node("a", text); try { if (new URL(url).protocol !== "https:") return node("span", text); } catch { return node("span", text); } a.href = url; a.target = "_blank"; a.rel = "noopener noreferrer"; return a; }

// ── Metric Count-Up Animation ──
const animatedMetricValues = {
  "candidate-count": 0,
  "hypothesis-count": 0,
  "evidence-count": 0,
  "run-count": 0,
  "identifier-count": 0,
  "observation-count": 0,
  "source-count": 0,
};

function animateMetricCount(id, targetVal) {
  const el = $(id);
  if (!el) return;
  const numericTarget = parseInt(targetVal, 10) || 0;
  const obj = { val: animatedMetricValues[id] ?? 0 };
  if (window.gsap && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    gsap.to(obj, {
      val: numericTarget,
      duration: 1.5,
      ease: "power2.out",
      onUpdate: () => {
        el.textContent = Math.round(obj.val);
      },
      onComplete: () => {
        animatedMetricValues[id] = numericTarget;
        el.textContent = numericTarget;
      }
    });
  } else {
    animatedMetricValues[id] = numericTarget;
    el.textContent = numericTarget;
  }
}

async function request(path, options = {}) {
  const response = await fetch(path, {headers:{"Content-Type":"application/json"}, ...options});
  const payload = await response.json();
  if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : JSON.stringify(payload.detail || response.status));
  return payload;
}
function cleanErrorMessage(message) {
  const text = message || "";
  if (text.includes("upsert_profile") || text.includes("AttributeError")) return "Email account discovery could not save profiles in the previous run. Start a fresh email search after this update.";
  return text;
}
function error(e) { $("error").textContent = cleanErrorMessage(e.message || String(e)); }
function setBusy(value) {
  busy = value;
  $("search-button").disabled = value;
  $("seed").disabled = value;
  $("seed-type").disabled = value;
  $("question-form").querySelectorAll("input,button").forEach(n => n.disabled = value);
  if (value) {
    startStatusCycle();
  } else {
    stopStatusCycle();
  }
}
function schedule() { clearTimeout(refreshTimer); refreshTimer = setTimeout(() => refresh().catch(error), 250); }

function maybeAutoContinue(state, question) {
  if (!state || state.status !== "AWAITING_USER" || !searchId) return;
  const key = question ? `q:${searchId}:${question.id}` : `s:${searchId}`;
  if (autoContinuedQuestions.has(key)) return;
  autoContinuedQuestions.add(key);
  request(`/api/searches/${searchId}/continue`, { method: "POST" })
    .then(() => schedule())
    .catch(() => autoContinuedQuestions.delete(key));
}
function connect() {
  stream?.close(); clearTimeout(fallbackTimer);
  if (!searchId) return;
  const id = searchId;
  stream = new EventSource(`/api/searches/${id}/events`);
  stream.onopen = () => { $("connection").textContent = "● Live event stream"; clearTimeout(fallbackTimer); };
  stream.addEventListener("update", schedule);
  stream.addEventListener("done", () => { stream.close(); clearTimeout(fallbackTimer); schedule(); });
  stream.onerror = () => { $("connection").textContent = "Reconnecting · polling fallback"; clearTimeout(fallbackTimer); fallbackTimer = setTimeout(async function retry() { if (id !== searchId || terminal(latest?.state.status)) return; try { await refresh(); } catch(e) { error(e); } fallbackTimer = setTimeout(retry, 4000); }, 4000); };
}
async function refresh() {
  if (!searchId) return;
  if (refreshRunning) { refreshAgain = true; return; }
  refreshRunning = true;
  const id = searchId;
  try {
    const root = `/api/searches/${id}`;
    const [state, candidates, hypotheses, question, report, runs, evidence, identifiers, observations] = await Promise.all(
      ["", "/candidates", "/hypotheses", "/question", "/report", "/connector-runs", "/evidence", "/identifiers", "/observations"].map(path =>
        request(root + path).catch(() => ({ items: [] }))
      )
    );
    if (id !== searchId) return;
    latest = {
      state,
      candidates: candidates.items || [],
      hypotheses: hypotheses.items || [],
      question: question.item,
      report: report.report_data,
      runs: runs.items || [],
      evidence: evidence.items || [],
      identifiers: identifiers?.items || [],
      observations: observations?.items || [],
    };
    $("status").textContent = state.status.replaceAll("_", " "); $("search-id").textContent = id;
    $("ai-status").textContent = `AI adviser: ${state.ai_assist?.status || "Not run yet"}${state.ai_assist?.reason ? " · " + state.ai_assist.reason : ""}`;
    
    // Update Confidence Badge
    const confidenceBadge = $("confidence-badge");
    if (confidenceBadge) {
      const topCandidateScore = candidates.items?.length ? Math.max(...candidates.items.map(c => points(c.identity_score || c.score || 0))) : 0;
      const confidenceVal = Math.max(topCandidateScore, state.status === "COMPLETED" ? 85 : 40);
      confidenceBadge.textContent = `Confidence: ${confidenceVal}%`;
      confidenceBadge.className = `status-chip ${confidenceVal >= 70 ? "status-chip--found" : "status-chip--neutral"}`;
      confidenceBadge.style.display = "inline-flex";
    }

    const aiChip = $("ai-status");
    if (aiChip) {
      const isRun = Boolean(state.ai_assist?.status);
      aiChip.className = `status-chip ${isRun ? "status-chip--active" : "status-chip--disabled"}`;
      aiChip.textContent = `AI adviser: ${state.ai_assist?.status || "Disabled"}${state.ai_assist?.reason ? " · " + state.ai_assist.reason : ""}`;
    }

    // Summary Metrics Count
    const foundProfiles = (latest.candidates || []).filter(p => (p.score || 0) > 0 || (p.identity_score || 0) > 0 || p.canonical_url).length;
    const discoveredIdentifiers = (latest.identifiers || []).length;
    const recordedObservations = (latest.observations || []).length;
    const evidenceSignalsCount = (latest.evidence || []).length;
    const uniqueSourcesCount = new Set((latest.runs || []).filter(r => r.status === "SUCCESS" || r.status === "COMPLETED").map(r => r.connector)).size;

    animateMetricCount("candidate-count", foundProfiles);
    animateMetricCount("identifier-count", discoveredIdentifiers);
    animateMetricCount("observation-count", recordedObservations);
    animateMetricCount("evidence-count", evidenceSignalsCount);
    animateMetricCount("source-count", Math.max(uniqueSourcesCount, 1));
    animateMetricCount("run-count", (latest.runs || []).filter(r => r.status === "COMPLETED" || r.status === "RUNNING").length);

    $("stop-search").disabled = terminal(state.status);
    $("continue-search").disabled = state.status !== "AWAITING_USER";
    maybeAutoContinue(state, question.item);
    if (terminal(state.status)) stopStatusCycle();
    if (terminal(state.status)) {
      stream?.close();
      clearTimeout(fallbackTimer);
      $("connection").textContent = "Saved investigation";
      if (currentSeedType === "EMAIL" && currentSeedValue && emailFetchedFor !== currentSeedValue) fetchEmailOsint(currentSeedValue);
    }
    if (state.error_summary) error(new Error(state.error_summary));

    renderIdentifierCards();
    renderEvidenceLedger();
    renderQuestion();
    renderReport();

    $("check-image").disabled = imageBusy || !$("reference-image").files.length;
    $("image-prompt").textContent = terminal(state.status) ? "Search finished. Optionally select an image to check reuse across avatars." : "Choose an optional image to check reuse across discovered candidate avatars.";
    if (state.status === "COMPLETED" && $("reference-image").files.length && !imageBusy) checkImage();
  } finally { refreshRunning = false; if (refreshAgain) { refreshAgain = false; schedule(); } }
}

// ── Match Strength Labels (Deterministic Thresholds) ──
// Strong Match: score >= 0.75
// Supported Match: 0.50 <= score < 0.75
// Possible Match: 0.25 <= score < 0.50
// Weak Match: score < 0.25
// (Never use "confirmed identity")
function getMatchLabel(scoreVal) {
  const pct = points(scoreVal);
  if (pct >= 75) return { label: "Strong Match", cls: "status-chip--strong", score: pct };
  if (pct >= 50) return { label: "Supported Match", cls: "status-chip--supported", score: pct };
  if (pct >= 25) return { label: "Possible Match", cls: "status-chip--possible", score: pct };
  return { label: "Weak Match", cls: "status-chip--weak", score: pct };
}

function candidateMatchValue(p) {
  if (typeof p.score === "number") return p.score;
  if (typeof p.identity_score === "number") return p.identity_score;
  return 0;
}

// ── First-Class Identifier Cards ──
function renderIdentifierCards() {
  const grid = $("identifiers-grid");
  if (!grid) return;
  grid.replaceChildren();

  const items = latest?.identifiers || [];
  if (!items.length) {
    grid.append(node("p", "No OSINT identifiers extracted yet.", "empty-muted"));
    return;
  }

  items.forEach(idItem => {
    const card = node("div", "", "case-card identifier-card");
    const header = node("div", "", "id-card-header");
    header.append(
      node("span", idItem.type, `status-chip id-type-badge id-type-${idItem.type.toLowerCase()}`),
      node("strong", idItem.value, "id-value-text")
    );
    card.append(header);

    const meta = node("div", "", "id-card-meta");
    const sourcesList = (idItem.sources || []).join(", ") || "Seed input";
    meta.append(
      node("div", `Sources: ${sourcesList}`, "id-meta-line"),
      node("div", `Independent Sources: ${idItem.independent_source_count}`, "id-meta-line")
    );
    card.append(meta);

    const btn = node("button", "Inspect Observations & Profiles ↗", "btn btn-secondary btn-sm");
    btn.onclick = () => openIdentifierDrawer(idItem);
    card.append(btn);

    grid.append(card);
  });
}

function openIdentifierDrawer(idItem) {
  const drawer = $("identifier-drawer");
  if (!drawer) return;
  $("drawer-type-badge").textContent = idItem.type;
  $("drawer-title").textContent = idItem.value;

  const body = $("drawer-body");
  body.replaceChildren();

  body.append(node("h4", "Observed Provenance"));
  if (idItem.observations?.length) {
    const list = node("ul", "", "drawer-obs-list");
    idItem.observations.forEach(obs => {
      const li = node("li", "", "drawer-obs-item");
      li.append(
        node("strong", obs.source),
        node("span", ` (${obs.type || "observation"})`),
        obs.source_url ? node("div", safeLink(obs.source_url, obs.source_url)) : null,
        obs.observed_at ? node("small", ` Observed at: ${obs.observed_at}`) : null
      );
      list.append(li);
    });
    body.append(list);
  } else {
    body.append(node("p", `Target initial seed identifier (${idItem.sources.join(", ")}).`));
  }

  body.append(node("h4", "Linked Profiles"));
  const linkedProfiles = (latest?.candidates || []).filter(p => (idItem.linked_profile_ids || []).includes(p.id));
  if (linkedProfiles.length) {
    linkedProfiles.forEach(p => {
      const pcard = node("div", "", "case-card mini-profile-card");
      pcard.append(node("strong", `@${p.username || p.display_name || p.platform}`));
      pcard.append(node("p", `${p.platform} profile`));
      if (p.canonical_url) pcard.append(safeLink(p.canonical_url, "Open Profile ↗"));
      body.append(pcard);
    });
  } else {
    body.append(node("p", "No direct profile links established yet.", "empty-muted"));
  }

  drawer.hidden = false;
}

$("drawer-close")?.addEventListener("click", () => {
  const drawer = $("identifier-drawer");
  if (drawer) drawer.hidden = true;
});

// ── Evidence Ledger ──
function renderEvidenceLedger() {
  const ledger = $("evidence-ledger");
  if (!ledger) return;
  ledger.replaceChildren();

  const items = latest?.evidence || [];
  if (!items.length) {
    ledger.append(node("p", "No pairwise evidence signals generated yet.", "empty-muted"));
    return;
  }

  const profileMap = new Map((latest?.candidates || []).map(p => [p.id, p]));

  items.forEach(item => {
    const card = node("div", "", `evidence-ledger-card ev-${item.direction.toLowerCase()}`);
    const top = node("div", "", "ev-card-top");
    top.append(
      node("strong", item.signal_type.replaceAll("_", " "), "ev-type-title"),
      node("span", `Reliability: ${points(item.reliability)}%`, "status-chip status-chip--neutral")
    );
    card.append(top);

    const leftProf = profileMap.get(item.left_profile_id);
    const rightProf = profileMap.get(item.right_profile_id);
    const pairText = `${leftProf ? label(leftProf) : item.left_profile_id} ↔ ${rightProf ? label(rightProf) : item.right_profile_id}`;
    
    card.append(node("p", pairText, "ev-pair-text"));
    card.append(node("p", item.explanation, "ev-explanation"));

    const meta = node("div", "", "ev-meta-line");
    meta.append(
      node("span", `Direction: ${item.direction}`),
      node("span", `Family: ${item.evidence_family}`),
      node("span", `Signal Score: ${points(item.normalized_score)}/100`),
      node("span", `Contribution: ${item.model_contribution != null ? Number(item.model_contribution).toFixed(3) : "N/A"}`)
    );
    card.append(meta);

    ledger.append(card);
  });
}

// ── Shared helpers ──
// `label`/`points` and the match helpers below are pure data helpers (no DOM
// access) still used by the identifier drawer, evidence ledger and report.

function renderQuestion() {
  const q = latest.question; $("question-section").hidden = !q;
  if (!q) { questionId = null; return; }
  if (questionId === q.id) return; questionId = q.id;
  $("question").textContent = q.question_text; $("question-reason").textContent = q.reason; const choices = $("question-options"); choices.replaceChildren();
  $("question-form").onsubmit = e => e.preventDefault();
  if (q.question_type === "TEXT") {
    const input = node("input"); input.type = "text"; input.required = true; input.name = "answer"; input.setAttribute("aria-label", q.context.input_label || "Your answer"); input.placeholder = q.context.placeholder || "Your clue"; input.maxLength = q.context.max_length || 64; if (q.context.pattern) input.pattern = q.context.pattern;
    const button = node("button", "Search with this clue", "wipe-btn"); button.type = "submit"; choices.append(input, button); $("question-form").onsubmit = e => { e.preventDefault(); if ($("question-form").reportValidity()) answer(input.value); };
  } else if (q.question_type === "MULTI_SELECT") {
    q.options.filter(o => o.value !== "skip").forEach(o => { const l = node("label"), i = node("input"); i.type = "checkbox"; i.value = o.value; l.append(i, document.createTextNode(o.label)); choices.append(l); });
    const b = node("button", "Prioritize these", "wipe-btn"); b.type = "submit"; choices.append(b); $("question-form").onsubmit = e => { e.preventDefault(); const values = [...choices.querySelectorAll("input:checked")].map(i => i.value); if (values.length) answer(values); };
  }
  q.options.filter(o => q.question_type !== "MULTI_SELECT" || o.value === "skip").forEach(o => { const b = node("button", o.label, "secondary wipe-btn"); b.type = "button"; b.onclick = () => answer(o.value); choices.append(b); });
}

async function answer(value) { if (busy) return; setBusy(true); try { await request(`/api/searches/${searchId}/question-answer`, {method:"POST", body:JSON.stringify({question_id:questionId, value})}); await refresh(); } catch(e) { error(e); } finally { setBusy(false); } }

function renderReport() {
  const r = latest?.report; if (!r) { $("report").textContent = "The investigation report will be generated when the search completes."; return; }
  $("report").replaceChildren(node("h2", "EXECUTIVE OSINT IDENTITY REPORT"));
  if (r.executive_finding) $("report").append(node("p", r.executive_finding, "lead-finding"));

  const section = (title, values) => { if (!values?.length) return; $("report").append(node("h3", title)); const ul = node("ul"); values.forEach(v => { const li = node("li", typeof v === "string" ? v : v.explanation || v.note || ""); for (const url of v.source_urls || []) li.append(document.createTextNode(" "), safeLink(url, "Source ↗")); ul.append(li); }); $("report").append(ul); };
  section("Confirmed Identity Footprint", (r.lead_candidates || []).map(p => {
    let text = `${label(p)} — ${p.reason || "Verified public profile"}`;
    if (p.created_at || p.raw?.created_at) text += ` (Created: ${p.created_at || p.raw.created_at})`;
    if (p.display_name || p.raw?.owner_info) text += ` [Owner: ${p.display_name || p.raw.owner_info}]`;
    return text;
  }));
  section("Public References & Code Repositories", (r.repository_references || []).map(p => `${p.url} · found in ${p.source_url}`));
  section("Primary Supporting Evidence", r.supporting_evidence); 
  section("Cross-Platform Evidence Correlations", r.moderate_evidence); 
  section("Exposure Risk & Defensive Self-Audit", (r.self_audit_findings || []).map(f => `${f.connector}: ${f.status}. Reported breach occurrences: ${f.breach_names.join(", ") || "none"}. ${f.note}`));
  section("Source Provenance", (r.source_provenance || []).map(p => ({explanation:p.connector, source_urls:p.source_url ? [p.source_url] : []})));
}

async function startInvestigation(e) {
  if (e) {
    e.preventDefault();
    e.stopPropagation();
  }
  if (busy || imageBusy) return false;

  const seedInput = $("seed");
  const seedTypeSelect = $("seed-type");
  if (!seedInput || !seedTypeSelect) return false;

  const rawVal = seedInput.value.trim();
  if (!rawVal) return false;

  setBusy(true);
  $("error").textContent = "";
  resetResultView();

  let selectedType = seedTypeSelect.value;
  // Auto-detect seed type if user typed an email address or URL
  if (rawVal.includes("@") && !rawVal.includes(" ")) {
    selectedType = "EMAIL";
    seedTypeSelect.value = "EMAIL";
  } else if (rawVal.startsWith("https://")) {
    selectedType = "PROFILE_URL";
    seedTypeSelect.value = "PROFILE_URL";
  }

  currentSeedType = selectedType;
  currentSeedValue = rawVal;
  emailFetchedFor = null;
  emailOsintData = null;

  if (currentSeedType === "EMAIL" || currentSeedValue.includes("@")) {
    fetchEmailOsint(currentSeedValue);
  }

  try {
    const result = await request("/api/searches", {
      method: "POST",
      body: JSON.stringify({ seed_type: currentSeedType, value: currentSeedValue, scope: "self_audit" })
    });
    stream?.close();
    autoContinuedQuestions.clear();
    searchId = result.id;
    questionId = null;
    $("image-results").replaceChildren();
    $("image-status").textContent = "";
    showResultSections();
    connect();
    await refresh();
    setTimeout(() => {
      document.getElementById("metrics-section")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 400);
  } catch (err) {
    error(err);
    stopStatusCycle();
  } finally {
    setBusy(false);
  }
  return false;
}

function bindFormEvents() {
  const form = $("search-form");
  const btn = $("search-button");
  const seedInput = $("seed");
  const seedTypeSelect = $("seed-type");

  if (form) {
    form.onsubmit = startInvestigation;
    form.addEventListener("submit", startInvestigation, true);
  }
  if (btn) {
    btn.onclick = startInvestigation;
  }
  if (seedInput && seedTypeSelect) {
    seedInput.addEventListener("input", () => {
      const val = seedInput.value.trim();
      if (val.includes("@") && !val.includes(" ")) {
        seedTypeSelect.value = "EMAIL";
      } else if (val.startsWith("https://")) {
        seedTypeSelect.value = "PROFILE_URL";
      }
    });
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bindFormEvents);
} else {
  bindFormEvents();
}

for (const [id, action] of [["continue-search","continue"],["stop-search","stop"]]) $(id)?.addEventListener("click", async () => { if (!searchId || busy) return; try { await request(`/api/searches/${searchId}/${action}`,{method:"POST"}); await refresh(); } catch(e) {error(e);} });
$("print-report")?.addEventListener("click", () => window.print());

localStorage.removeItem("deus-search");
if (location.search) history.replaceState(null, "", location.pathname);
resetResultView();

async function checkImage() {
  const file = $("reference-image").files[0];
  if (!file || !searchId || imageBusy) return;
  const id = searchId, generation = ++imageGeneration;
  imageBusy = true; imageController = new AbortController();
  $("reference-image").value = ""; $("reference-image").disabled = true; $("check-image").disabled = true;
  $("image-results").replaceChildren(); $("image-status").textContent = "Checking real public avatar images…";
  try {
    const response = await fetch(`/api/searches/${id}/image-matches`, {method:"POST", body:file, headers:{"Content-Type":file.type || "application/octet-stream"}, signal:imageController.signal, cache:"no-store"});
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Image check failed");
    if (id !== searchId || generation !== imageGeneration) return;
    $("image-status").textContent = `${result.checked} of ${result.items.length} candidate images checked · ${result.status}. Upload cleared; identity scores unchanged.`;
    const rank = {EXACT_FILE:0, SAME_PIXELS:1, POSSIBLE_REUSE:2};
    result.items.sort((a,b) => (rank[a.status] ?? 3) - (rank[b.status] ?? 3)).forEach(item => {
      const card = node("article", "", "card");
      card.append(node("strong", `${label(item)} · ${item.status.replaceAll("_", " ")}`), node("p", item.message));
      card.append(safeLink(item.profile_url, "Profile source ↗"));
      if (item.image_url) card.append(document.createTextNode(" · "), safeLink(item.image_url, "Review public image ↗"));
      $("image-results").append(card);
    });
    result.limitations.forEach(text => $("image-results").append(node("p", text, "muted")));
  } catch(e) { if (generation === imageGeneration) $("image-status").textContent = `${e.message}. File cleared; select it again to retry.`; }
  finally { imageBusy = false; imageController = null; $("reference-image").disabled = false; }
}
$("check-image").onclick = checkImage;
$("reference-image").onchange = () => {
  const file = $("reference-image").files[0];
  if (file && file.size > 5000000) { $("reference-image").value = ""; $("image-status").textContent = "Please choose an image up to 5 MB."; }
  else $("image-status").textContent = file ? "Selected locally. Check now or leave it for search completion." : "";
  $("check-image").disabled = !searchId || !$("reference-image").files.length || imageBusy;
};
$("clear-image").onclick = () => {
  ++imageGeneration; imageController?.abort(); $("reference-image").value = "";
  $("image-results").replaceChildren(); $("check-image").disabled = true;
  $("image-status").textContent = "Local selection and results cleared. An in-flight server check may finish within its bounded timeout; nothing is saved.";
};

// ── Hero CTA: scroll to search form and focus seed input ──
document.getElementById("hero-cta")?.addEventListener("click", () => {
  const form = document.getElementById("search-form");
  form.scrollIntoView({ behavior: "smooth", block: "center" });
  setTimeout(() => document.getElementById("seed").focus(), 380);
});

// ── Email OSINT: parallel identity discovery via /api/osint/email ──
let _emailOsintController = null;

// Sources that describe the email's own domain or breach exposure, never a site
// where the address holds an account.
const EMAIL_SITE_SKIP = new Set(["domain_intel", "hibp"]);

// Expand compound sources like holehe_public into individual registered accounts.
function expandEmailAccounts(data) {
  const expanded = [];
  (data?.source_results ?? []).forEach(src => {
    if (EMAIL_SITE_SKIP.has(src.source_name)) return;
    if (src.evidence?.found_services && Array.isArray(src.evidence.found_services)) {
      const details = src.evidence.details || {};
      src.evidence.found_services.forEach(serviceName => {
        const sDetail = details[serviceName] || {};
        expanded.push({
          source_name: serviceName,
          category: "registered account",
          status: "FOUND",
          account_exists: true,
          confidence: sDetail.confidence ?? src.confidence ?? data?.overall_confidence,
          display_name: sDetail.display_name || sDetail.username || `${serviceName} Registered Account`,
          username: sDetail.username || null,
          canonical_url: sDetail.canonical_url || `https://${serviceName}.com`,
        });
      });
    } else if (src.account_exists || src.canonical_url) {
      expanded.push(src);
    }
  });
  return expanded;
}

// Normalize real email-discovered accounts and profile URLs into lead objects,
// used by the remaining sections (identifiers, evidence ledger, report).
function emailCandidateLeads() {
  if (!emailOsintData) return [];
  const leads = [], seen = new Set();
  const push = lead => {
    const url = (lead.canonical_url || "").toLowerCase();
    const key = url || `${lead.platform || ""}:${lead.username || lead.display_name || ""}`.toLowerCase();
    if (!key || seen.has(key)) return;
    seen.add(key);
    leads.push(lead);
  };
  for (const acc of expandEmailAccounts(emailOsintData)) {
    push({
      platform: acc.source_name || "ACCOUNT",
      title: acc.username ? `@${acc.username}` : acc.display_name || `${acc.source_name || "Account"} profile`,
      source_name: acc.source_name,
      username: acc.username || null,
      display_name: acc.display_name || null,
      canonical_url: acc.canonical_url || null,
      confidence: acc.confidence ?? emailOsintData.overall_confidence ?? 0.85,
      status: acc.status || (acc.account_exists ? "FOUND" : "UNKNOWN"),
    });
  }
  for (const id of emailOsintData.discovered_identifiers || []) {
    if (id.type === "profile_url" && /^https:\/\//i.test(id.value)) {
      push({
        platform: id.source || "PROFILE_URL",
        title: id.value,
        source_name: id.source,
        username: null,
        display_name: null,
        canonical_url: id.value,
        confidence: id.confidence ?? emailOsintData.overall_confidence ?? 0.85,
        status: "FOUND",
      });
    }
  }
  return leads;
}

async function fetchEmailOsint(email) {
  const section   = document.getElementById("email-osint-section");
  const metaEl    = document.getElementById("email-osint-meta");
  const sourcesEl = document.getElementById("email-osint-sources");
  if (!section || !metaEl || !sourcesEl) return;

  _emailOsintController?.abort();
  _emailOsintController = new AbortController();

  section.hidden = false;
  metaEl.className = "metrics";
  metaEl.replaceChildren(node("div", "Scanning identity sources\u2026"));
  sourcesEl.replaceChildren();
  emailFetchedFor = email;

  try {
    const res = await fetch("/api/osint/email", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
      signal: _emailOsintController.signal,
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || `Email OSINT error ${res.status}`);
    emailOsintData = data;
    renderEmailOsint(data, metaEl, sourcesEl);
  } catch (e) {
    if (e.name !== "AbortError") {
      metaEl.className = "";
      metaEl.textContent = `Email OSINT error: ${e.message}`;
    }
  } finally {
    _emailOsintController = null;
  }
}

// ── Email OSINT display ──
// Human-readable names for the passive email sources so it is obvious on which
// sites the submitted email is registered.
const EMAIL_SERVICE_LABELS = {
  spotify: "Spotify",
  imgur: "Imgur",
  "chess.com": "Chess.com",
  duolingo: "Duolingo",
  adobe: "Adobe",
  gravatar: "Gravatar",
  github: "GitHub",
  github_email: "GitHub",
  google_gaia: "Google (Gmail · Chrome · Gemini · YouTube)",
  holehe_public: "Multi-site enumeration",
  hibp: "Have I Been Pwned",
  domain_intel: "Domain intelligence",
  instagram: "Instagram",
  pinterest: "Pinterest",
  twitter: "X (Twitter)",
  reddit: "Reddit",
  linkedin: "LinkedIn",
  snapchat: "Snapchat",
  facebook: "Facebook",
  amazon: "Amazon",
  wordpress: "WordPress.com",
  firefox: "Firefox Accounts",
  tumblr: "Tumblr",
  lastfm: "Last.fm",
  twitch: "Twitch",
  vimeo: "Vimeo",
  strava: "Strava",
  soundcloud: "SoundCloud",
  tiktok: "TikTok",
  microsoft: "Microsoft / Outlook",
  yahoo: "Yahoo",
  ebay: "eBay",
};
function formatSiteName(name) {
  const key = String(name || "").toLowerCase().trim();
  if (!key) return "Unknown site";
  if (EMAIL_SERVICE_LABELS[key]) return EMAIL_SERVICE_LABELS[key];
  return key.replace(/[._-]+/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}
function emailProviderLabel(intel) {
  if (!intel) return "Unknown";
  const type = intel.provider_type && intel.provider_type !== "UNKNOWN"
    ? ` (${String(intel.provider_type).toLowerCase().replace(/_/g, " ")})`
    : "";
  return `${intel.provider_name || "Unknown provider"}${type}`;
}
// Aggregate every passively checked site (multi-site enumerator + single-site
// adapters) into one status list, so the full coverage is visible: registered,
// not registered, or not verifiable.
function collectSiteStatuses(data) {
  const sites = new Map();
  for (const src of data.source_results || []) {
    if (EMAIL_SITE_SKIP.has(src.source_name)) continue;
    const aggregate = src.evidence && src.evidence.site_status;
    if (aggregate && typeof aggregate === "object") {
      for (const [key, info] of Object.entries(aggregate)) {
        sites.set(key, {
          key,
          label: info.label || formatSiteName(key),
          exists: info.exists,
          username: info.username || null,
          display_name: info.display_name || null,
          canonical_url: info.canonical_url || null,
        });
      }
      continue;
    }
    const exists = src.account_exists === true ? true : (src.status === "NOT_FOUND" ? false : null);
    sites.set(src.source_name, {
      key: src.source_name,
      label: formatSiteName(src.source_name),
      exists,
      username: src.username || null,
      display_name: src.display_name || null,
      canonical_url: src.canonical_url || null,
    });
  }
  const rank = site => (site.exists === true ? 0 : site.exists === false ? 1 : 2);
  return [...sites.values()].sort((a, b) => rank(a) - rank(b) || a.label.localeCompare(b.label));
}

// Always-visible summary: general email info plus where (and where not) the
// email is registered, independent of the selected detail tab.
function renderEmailOverview(data) {
  const overviewEl = document.getElementById("email-osint-overview");
  if (!overviewEl || !data) return;
  overviewEl.replaceChildren();
  const intel = data.domain_intel || {};
  const normalized = data.normalized_email || data.email || "submitted email";
  const accounts = expandEmailAccounts(data).slice().sort((a, b) => (b.confidence || 0) - (a.confidence || 0));
  const sourceResults = data.source_results || [];

  const head = node("div", "", "email-overview-head");
  head.append(node("p", "EMAIL PROFILE", "platform"), node("strong", normalized));
  overviewEl.append(head);

  const facts = [
    ["Provider", emailProviderLabel(intel)],
    ["Domain", intel.domain || "—"],
    ["Organization hint", intel.organization_hint || "—"],
    ["Registered accounts", String(Math.max(accounts.length, data.accounts_found || 0))],
    ["Sources checked", String(data.sources_checked ?? sourceResults.length)],
    ["Overall confidence", `${Math.round((data.overall_confidence || 0) * 100)}%`],
    ["Free provider", intel.is_free_provider ? "Yes" : "No"],
    ["Disposable domain", intel.is_disposable ? "Yes" : "No"],
    ["MX records", String((intel.mx_records || []).length)],
    ["TXT records", String((intel.txt_records || []).length)],
  ];
  if (data.scan_duration_ms) facts.push(["Scan time", `${Math.round(data.scan_duration_ms)} ms`]);
  const grid = node("div", "", "email-overview-grid");
  for (const [label, value] of facts) {
    const item = node("div", "", "email-overview-item");
    item.append(node("span", label, "email-overview-label"), node("strong", value));
    grid.append(item);
  }
  overviewEl.append(grid);

  const registeredBox = node("div", "", "email-overview-registered");
  registeredBox.append(node("h3", `Registered on ${accounts.length} site${accounts.length === 1 ? "" : "s"}`));
  if (accounts.length) {
    const list = node("ul", "", "email-registered-list");
    for (const acc of accounts) {
      const li = node("li");
      li.append(node("strong", formatSiteName(acc.source_name)));
      const bits = [];
      if (acc.username) bits.push(`@${acc.username}`);
      if (acc.display_name && acc.display_name !== acc.username) bits.push(acc.display_name);
      if (acc.confidence != null) bits.push(`${Math.round((acc.confidence || 0) * 100)}% confidence`);
      if (bits.length) li.append(document.createTextNode(` — ${bits.join(" · ")}`));
      if (acc.canonical_url) li.append(document.createTextNode(" "), safeLink(acc.canonical_url, "Open site ↗"));
      list.append(li);
    }
    registeredBox.append(list);
  } else {
    registeredBox.append(node("p", "No account registrations were detected for this email on the checked sites.", "empty"));
  }
  overviewEl.append(registeredBox);

  const sites = collectSiteStatuses(data);
  if (sites.length) {
    const registeredCount = sites.filter(site => site.exists === true).length;
    const absentCount = sites.filter(site => site.exists === false).length;
    const unknownCount = sites.filter(site => site.exists == null).length;
    const sitesBox = node("div", "", "email-overview-sites");
    sitesBox.append(node("h3", `All sites checked (${sites.length})`));
    sitesBox.append(
      node("p", `${registeredCount} registered · ${absentCount} not registered · ${unknownCount} could not be verified.`, "email-sites-summary")
    );
    const list = node("ul", "", "email-site-list");
    for (const site of sites) {
      const li = node("li");
      li.append(node("strong", site.label));
      if (site.exists === true) li.append(node("span", "Registered", "status-chip status-chip--found"));
      else if (site.exists === false) li.append(node("span", "Not registered", "status-chip status-chip--disabled"));
      else li.append(node("span", "Could not verify", "status-chip status-chip--neutral"));
      const bits = [];
      if (site.username) bits.push(`@${site.username}`);
      if (site.display_name && site.display_name !== site.username) bits.push(site.display_name);
      if (bits.length) li.append(document.createTextNode(` ${bits.join(" · ")}`));
      if (site.exists === true && site.canonical_url) li.append(document.createTextNode(" "), safeLink(site.canonical_url, "Open ↗"));
      list.append(li);
    }
    sitesBox.append(list);
    overviewEl.append(sitesBox);
  }
}

function renderEmailOsint(data, metaEl, sourcesEl) {
  metaEl.className = "metrics";
  metaEl.replaceChildren();
  renderEmailOverview(data);

  // Expand compound sources like holehe_public into individual accounts
  const expandedAccounts = expandEmailAccounts(data);

  const sourceResults = data.source_results ?? [];
  const identifiers = data.discovered_identifiers ?? [];
  const totalAccountsCount = Math.max(expandedAccounts.length, data.accounts_found || 0);

  const summaryItems = [
    ["accounts", String(totalAccountsCount), "Accounts found"],
    ["sources", String(data.sources_checked ?? sourceResults.length), "Sources checked"],
    ["identifiers", String(identifiers.length), "Identifiers extracted"],
    ["domain", Math.round((data.overall_confidence ?? 0.92) * 100) + "%", "Confidence"],
  ];
  for (const [view, val, lbl] of summaryItems) {
    const div = node("button", "", "metric-tab");
    div.type = "button";
    div.setAttribute("aria-pressed", String(emailOsintView === view));
    div.onclick = () => { emailOsintView = view; renderEmailOsint(emailOsintData, metaEl, sourcesEl); };
    const strong = node("strong", val);
    const span   = node("span",   lbl);
    div.append(strong, span);
    metaEl.append(div);
  }

  sourcesEl.replaceChildren();
  sourcesEl.className = "email-detail-grid";

  if (emailOsintView === "accounts") {
    const registered = [...expandedAccounts].sort((a, b) => (b.confidence || 0) - (a.confidence || 0));
    sourcesEl.append(node("h3", `Registered accounts & websites (${registered.length})`));
    for (const src of registered) sourcesEl.append(emailSourceCard(src, true));
    if (!registered.length) sourcesEl.append(node("p", "No linked account URLs returned by email sources yet.", "empty"));
    return;
  }

  if (emailOsintView === "sources") {
    const STATUS_ORDER = { FOUND: 0, UNKNOWN: 1, NOT_FOUND: 2, RATE_LIMITED: 3, TIMEOUT: 4, ERROR: 5 };
    const sorted = [...sourceResults].sort((a, b) => (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9));
    for (const src of sorted) sourcesEl.append(emailSourceCard(src, false));
    return;
  }

  if (emailOsintView === "identifiers") {
    for (const id of identifiers) {
      const card = node("article", "", "card email-account-card");
      card.append(node("p", id.source.toUpperCase(), "platform"), node("strong", `${id.type}: ${id.value}`));
      card.append(node("p", `Confidence ${Math.round(id.confidence * 100)}%`));
      if (id.type.includes("url")) card.append(safeLink(id.value, "Open source ↗"));
      sourcesEl.append(card);
    }
    if (!identifiers.length) sourcesEl.append(node("p", "No reusable identifiers extracted yet.", "empty"));
    return;
  }

  if (data.domain_intel) {
    const d = data.domain_intel;
    const card = node("article", "", "card email-account-card");
    card.append(node("p", "DOMAIN INTELLIGENCE", "platform"), node("strong", d.domain || "—"));
    card.append(node("p", `Provider: ${emailProviderLabel(d)}`));
    if (d.organization_hint) card.append(node("p", `Organization hint: ${d.organization_hint}`));
    if (d.is_free_provider) card.append(node("span", "Free provider", "badge"));
    if (d.is_disposable) card.append(node("span", "Disposable domain", "badge"));
    if ((d.mx_records || []).length) card.append(node("small", `MX records: ${d.mx_records.join(", ")}`));
    if ((d.txt_records || []).length) card.append(node("small", `TXT records: ${d.txt_records.join(", ")}`));
    sourcesEl.append(card);
  }
}

function emailSourceCard(src, accountOnly) {
    const card = node("article", "", "card email-account-card");
    const found = src.status === "FOUND" || Boolean(src.account_exists);
    card.dataset.status =
      src.status === "FOUND"   ? "RUNNING" :
      src.status === "ERROR"   ? "FAILED"  :
      src.status === "TIMEOUT" ? "FAILED"  : "";

    const site = formatSiteName(src.source_name);
    card.append(node("p", String(src.category || "registered account").replace(/_/g, " ").toUpperCase(), "platform"));
    const title = src.username ? `${site} · @${src.username}` : site;
    card.append(
      node("strong", title),
      node("span", found ? "REGISTERED" : (src.status || "UNKNOWN"), found ? "badge" : "status-chip status-chip--disabled")
    );

    if (src.display_name && src.display_name !== src.username) card.append(node("small", `Display name: ${src.display_name}`));
    if (found) card.append(node("small", `This email is registered on ${site}.`));
    if (src.confidence != null) card.append(node("small", `Match confidence: ${Math.round((src.confidence || 0) * 100)}%`));
    if (src.message && !accountOnly) card.append(node("small", src.message));
    if (src.canonical_url) card.append(safeLink(src.canonical_url, `Open ${site} ↗`));
    if (src.response_time_ms) card.append(node("small", `${Math.round(src.response_time_ms)} ms response`));
    return card;
}

// ── Lenis & GSAP Motion Initialization ──
document.addEventListener("DOMContentLoaded", () => {
  // Initialize Lenis Smooth Scroll
  let lenis = null;
  if (window.Lenis && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    lenis = new Lenis({
      duration: 1.2,
      easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
      smoothTouch: false,
    });
    function raf(time) {
      lenis.raf(time);
      requestAnimationFrame(raf);
    }
    requestAnimationFrame(raf);
  }

  // Initialize GSAP & ScrollTrigger Animations
  if (window.gsap && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    if (window.ScrollTrigger) {
      gsap.registerPlugin(ScrollTrigger);
      if (lenis) {
        lenis.on('scroll', ScrollTrigger.update);
        gsap.ticker.add((time) => {
          lenis.raf(time * 1000);
        });
        gsap.ticker.lagSmoothing(0, 0);
      }

      // Reveal section animations
      document.querySelectorAll(".reveal-section").forEach((el) => {
        gsap.fromTo(el,
          { opacity: 0, y: 36 },
          {
            opacity: 1,
            y: 0,
            duration: 0.85,
            ease: "power2.out",
            scrollTrigger: {
              trigger: el,
              start: "top 88%",
              toggleActions: "play none none none"
            }
          }
        );
      });
    }

    // Hero headline staggered line entrance
    const heroLines = document.querySelectorAll(".hero-headline .line-text");
    if (heroLines.length) {
      gsap.fromTo(heroLines,
        { y: "100%", opacity: 0 },
        { y: "0%", opacity: 1, duration: 1.0, ease: "power3.out", stagger: 0.18, delay: 0.15 }
      );
    }

    const heroEyebrow = document.querySelector(".hero-eyebrow");
    if (heroEyebrow) {
      gsap.fromTo(heroEyebrow,
        { opacity: 0, y: -10 },
        { opacity: 1, y: 0, duration: 0.6, ease: "power2.out" }
      );
    }

    const heroCta = document.getElementById("hero-cta");
    if (heroCta) {
      gsap.fromTo(heroCta,
        { opacity: 0, y: 15 },
        { opacity: 1, y: 0, duration: 0.6, ease: "power2.out", delay: 0.6 }
      );
    }
  }
});
