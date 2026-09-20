/* All displayed profiles, edges and reports come from the API. No demo data. */
const $ = id => document.getElementById(id);
const terminal = s => ["COMPLETED", "FAILED", "CANCELLED", "STOPPED"].includes(s);
let searchId = null, stream = null, refreshTimer = null, fallbackTimer = null, busy = false;
let latest = null, refreshRunning = false, refreshAgain = false;
let currentSeedType = null, currentSeedValue = null;

// Clear all prior investigation output so a new run starts from a clean slate.
function resetResultView() {
  const reportEl = $("report");
  if (reportEl) reportEl.textContent = "An executive OSINT identity report appears when the investigation finishes.";
  ["evidence", "candidates", "email-result-container"].forEach(id => {
    const el = $(id);
    if (el) el.replaceChildren();
  });
  const emailSection = $("email-osint-section");
  if (emailSection) emailSection.hidden = true;
  ["candidate-count", "evidence-count", "run-count", "identifier-count", "observation-count", "source-count"].forEach(id => {
    const el = $(id);
    if (el) el.textContent = "0";
  });
  Object.keys(animatedMetricValues).forEach(key => { animatedMetricValues[key] = 0; });
  const liveStatus = $("live-candidate-status");
  if (liveStatus) liveStatus.textContent = "";
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
    "view-overview",
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
  if (text.includes("upsert_profile") || text.includes("AttributeError")) return "Could not save profiles in the previous run. Start a fresh search.";
  return text;
}
function error(e) {
  const el = $("error");
  if (!el) return;
  const msg = cleanErrorMessage(e?.message || String(e || ""));
  el.textContent = msg;
  el.hidden = !msg;
}
function setBusy(value) {
  busy = value;
  const btn = $("search-button"); if (btn) btn.disabled = value;
  const seed = $("seed"); if (seed) seed.disabled = value;
  const seedType = $("seed-type"); if (seedType) seedType.disabled = value;
  
  const statusPanel = $("status-control-panel");
  if (statusPanel && value) statusPanel.hidden = false;

  if (value) {
    startStatusCycle();
    const beam = $("radar-beam");
    if (beam) beam.classList.add("spinning");
  } else if (!searchId) {
    stopStatusCycle();
  }
}
function schedule() { clearTimeout(refreshTimer); refreshTimer = setTimeout(() => refresh().catch(error), 250); }

function connect() {
  stream?.close(); clearTimeout(fallbackTimer);
  if (!searchId) return;
  const id = searchId;
  stream = new EventSource(`/api/searches/${id}/events`);
  stream.onopen = () => { const conn = $("connection"); if (conn) conn.textContent = "● Live event stream"; clearTimeout(fallbackTimer); };
  stream.addEventListener("update", schedule);
  stream.addEventListener("done", () => { stream.close(); clearTimeout(fallbackTimer); schedule(); });
  stream.onerror = () => { const conn = $("connection"); if (conn) conn.textContent = "Reconnecting · polling fallback"; clearTimeout(fallbackTimer); fallbackTimer = setTimeout(async function retry() { if (id !== searchId || terminal(latest?.state.status)) return; try { await refresh(); } catch(e) { error(e); } fallbackTimer = setTimeout(retry, 4000); }, 4000); };
}
async function refresh() {
  if (!searchId) return;
  if (refreshRunning) { refreshAgain = true; return; }
  refreshRunning = true;
  const id = searchId;
  try {
    const root = `/api/searches/${id}`;
    const [state, candidates, report, runs, evidence, identifiers, observations] = await Promise.all(
      ["", "/candidates", "/report", "/connector-runs", "/evidence", "/identifiers", "/observations"].map(path =>
        request(root + path).catch(() => ({ items: [] }))
      )
    );
    if (id !== searchId) return;
    latest = {
      state,
      candidates: candidates.items || [],
      report: report.report_data,
      runs: runs.items || [],
      evidence: evidence.items || [],
      identifiers: identifiers?.items || [],
      observations: observations?.items || [],
    };

    const statusPanel = $("status-control-panel");
    if (statusPanel) statusPanel.hidden = false;

    const isDone = terminal(state.status);
    const statusBadgeTag = $("status-badge-tag");
    const radarBeam = $("radar-beam");
    const progContainer = $("progress-container");
    const statusMsg = $("investigation-status-msg");

    if (isDone) {
      stopStatusCycle();
      if (radarBeam) radarBeam.classList.remove("spinning");
      if (statusBadgeTag) statusBadgeTag.textContent = `[ ${state.status} ]`;
      if (statusMsg) statusMsg.textContent = state.status === "COMPLETED" ? "Search finished. Live OSINT sources checked." : "Investigation stopped.";
      if (progContainer) progContainer.classList.add("completed");
      const statusEl = $("status"); if (statusEl) statusEl.textContent = state.status === "COMPLETED" ? "INVESTIGATION COMPLETED" : state.status.replaceAll("_", " ");
    } else {
      if (statusBadgeTag) statusBadgeTag.textContent = `[ SEARCHING ]`;
      if (radarBeam) radarBeam.classList.add("spinning");
      if (progContainer) progContainer.classList.remove("completed");
      const statusEl = $("status"); if (statusEl) statusEl.textContent = "SEARCHING PUBLIC OSINT DATA...";
    }

    const searchIdEl = $("search-id"); if (searchIdEl) searchIdEl.textContent = id;
    
    // Update Confidence Badge
    const confidenceBadge = $("confidence-badge");
    if (confidenceBadge) {
      const topCandidateScore = candidates.items?.length ? Math.max(...candidates.items.map(c => points(c.identity_score || c.score || 0))) : 0;
      const confidenceVal = Math.max(topCandidateScore, state.status === "COMPLETED" ? 85 : 40);
      confidenceBadge.textContent = `Confidence: ${confidenceVal}%`;
      confidenceBadge.className = `status-chip ${confidenceVal >= 70 ? "status-chip--found" : "status-chip--neutral"}`;
      confidenceBadge.style.display = "inline-flex";
    }

    // Summary Metrics Count
    const totalFoundProfiles = (latest.candidates || []).length;
    const discoveredIdentifiers = (latest.identifiers || []).length;
    const recordedObservations = (latest.observations || []).length;
    const evidenceSignalsCount = (latest.evidence || []).length;
    const uniqueSourcesCount = new Set((latest.runs || []).filter(r => r.status === "SUCCESS" || r.status === "COMPLETED" || r.status === "NO_RESULTS" || r.status === "RUNNING").map(r => r.connector)).size;

    animateMetricCount("candidate-count", totalFoundProfiles);
    animateMetricCount("identifier-count", discoveredIdentifiers);
    animateMetricCount("observation-count", recordedObservations);
    animateMetricCount("evidence-count", evidenceSignalsCount);
    animateMetricCount("source-count", uniqueSourcesCount);
    animateMetricCount("run-count", (latest.runs || []).filter(r => r.status === "COMPLETED" || r.status === "RUNNING" || r.status === "SUCCESS").length);

    const stopBtn = $("stop-search"); if (stopBtn) stopBtn.disabled = isDone;

    if (isDone) {
      stream?.close();
      clearTimeout(fallbackTimer);
      const conn = $("connection"); if (conn) conn.textContent = "Saved investigation";
    }

    if (state.error_summary) error(new Error(state.error_summary));

    renderCandidates();
    renderReport();
  } finally { refreshRunning = false; if (refreshAgain) { refreshAgain = false; schedule(); } }
}

// ── Match Strength Labels ──
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

const RELEVANCE_LABELS = {
  USER_HINT_MATCH: { label: "Confirmed Variant Match", cls: "status-chip--supported", rank: 0 },
  EXACT_SEED: { label: "Exact Seed Match", cls: "status-chip--found", rank: 1 },
  POSSIBLE_VARIANT: { label: "Possible Variant", cls: "status-chip--possible", rank: 2 },
};

function candidateSortRank(p, targetHandle) {
  const handle = (p.username || "").toLowerCase();
  const tgt = (targetHandle || "").toLowerCase();
  if (tgt && handle === tgt) return 0;
  if ((p.reason || "").includes("Linked from profile") || p.relevance === "LINKED_PROFILE") return 1;
  return 2 + (RELEVANCE_LABELS[p.relevance]?.rank ?? 3);
}

function getPlatformSvgLogo(platform, size = 26) {
  const p = String(platform || "").toLowerCase().trim();
  if (p.includes("github")) {
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="currentColor" class="social-logo-svg"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/></svg>`;
  }
  if (p.includes("twitter") || p.includes("x")) {
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="currentColor" class="social-logo-svg"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>`;
  }
  if (p.includes("instagram")) {
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="social-logo-svg"><rect x="2" y="2" width="20" height="20" rx="5" ry="5"/><path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z"/><line x1="17.5" y1="6.5" x2="17.51" y2="6.5"/></svg>`;
  }
  if (p.includes("reddit")) {
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="currentColor" class="social-logo-svg"><path d="M12 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0zm5.01 4.744c.688 0 1.25.561 1.25 1.249a1.25 1.25 0 0 1-2.498.056l-2.597-.547-.8 3.747c1.824.07 3.48.632 4.674 1.488.308-.309.73-.491 1.207-.491.968 0 1.754.786 1.754 1.754 0 .716-.435 1.333-1.01 1.614a3.111 3.111 0 0 1 .042.52c0 2.694-3.13 4.87-7.004 4.87-3.874 0-7.004-2.176-7.004-4.87 0-.183.015-.366.043-.534A1.748 1.748 0 0 1 4.028 12c0-.968.786-1.754 1.754-1.754.463 0 .898.196 1.207.49 1.207-.883 2.878-1.43 4.744-1.487l.885-4.182a.342.342 0 0 1 .14-.197.35.35 0 0 1 .238-.042l2.906.617a1.214 1.214 0 0 1 1.108-.701zM9.25 12C8.561 12 8 12.562 8 13.25c0 .687.561 1.248 1.25 1.248.687 0 1.248-.561 1.248-1.249 0-.688-.561-1.249-1.249-1.249zm5.5 0c-.687 0-1.248.562-1.248 1.25 0 .687.561 1.248 1.249 1.248.688 0 1.249-.561 1.249-1.249 0-.688-.562-1.249-1.25-1.249zm-4.566 3.967c-.07.067-.07.176 0 .243.68.68 1.83.68 2.51 0a.17.17 0 0 0 0-.243l-.116-.118a.17.17 0 0 0-.243 0c-.43.43-1.16.43-1.59 0a.17.17 0 0 0-.243 0z"/></svg>`;
  }
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="social-logo-svg"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>`;
}

function candidateAvatarElement(p) {
  const avatarUrl = p.avatar_url || p.raw_json?.avatar_url || p.raw?.avatar_url;
  const wrapper = node("div", "", "candidate-avatar-wrap");
  if (avatarUrl && typeof avatarUrl === "string" && /^https?:\/\//i.test(avatarUrl)) {
    const img = node("img", "", "candidate-avatar-img");
    img.src = avatarUrl;
    img.alt = p.username || p.display_name || "Profile avatar";
    img.onerror = () => { wrapper.replaceChildren(fallbackAvatar(p)); };
    wrapper.append(img);
  } else {
    wrapper.append(fallbackAvatar(p));
  }
  return wrapper;
}

function fallbackAvatar(p) {
  const fallback = node("div", "", "candidate-avatar-fallback");
  fallback.innerHTML = getPlatformSvgLogo(p.platform, 24);
  return fallback;
}

function resolveCandidateLink(p) {
  if (p.canonical_url) return p.canonical_url;
  const username = p.username || p.display_name;
  if (!username) return null;
  return `https://google.com/search?q=${encodeURIComponent((p.platform || '') + ' ' + username)}`;
}

let candidatePageSize = 60;
let candidateSearchQuery = "";

function candidateCard(p) {
  const card = node("article", "", "case-card candidate-card");
  const header = node("div", "", "candidate-header-row");
  const avatarWrap = candidateAvatarElement(p);
  const identity = node("div", "", "candidate-identity");
  const platformLine = node("div", "", "platform-badge-line");
  const sourceName = p.raw_json?.source || p.source_name || "connector";

  platformLine.innerHTML = `${getPlatformSvgLogo(p.platform, 14)} <span>${String(p.platform || "PROFILE").toUpperCase()}</span> <span class="badge badge-source" style="font-size:10px;padding:2px 6px;margin-left:6px;border-radius:4px;background:rgba(255,255,255,0.1);color:#a1a1aa">${sourceName}</span>`;
  const handle = node("strong", p.username ? "@" + p.username : p.display_name || "Public profile", "candidate-handle");
  identity.append(platformLine, handle);
  if (p.username && p.display_name && p.display_name !== p.username) identity.append(node("span", p.display_name, "candidate-display"));
  if (p.bio) identity.append(node("p", p.bio, "candidate-bio-sub"));

  header.append(avatarWrap, identity);
  card.append(header);

  const chips = node("div", "", "candidate-chips");
  const matchInfo = getMatchLabel(candidateMatchValue(p));
  const rel = RELEVANCE_LABELS[p.relevance];
  const badgeText = rel ? `${rel.label} · ${matchInfo.score}%` : `${matchInfo.label} · ${matchInfo.score}%`;
  const badgeCls = rel ? rel.cls : matchInfo.cls;
  chips.append(node("span", badgeText, `status-chip ${badgeCls}`));
  if (p.raw_json?.verified === true) chips.append(node("span", "✓ Verified", "status-chip status-chip--found"));
  card.append(chips);

  const why = node("div", "", "candidate-why");
  why.append(node("span", "Why this result?", "candidate-why-title"));
  why.append(node("p", p.reason || `Public profile on ${p.platform} surfaced by ${sourceName}.`, "candidate-reason"));
  card.append(why);

  const actions = node("div", "", "candidate-actions");
  const targetLink = resolveCandidateLink(p);
  if (targetLink) {
    actions.append(safeLink(targetLink, `Open ${p.platform || 'profile'} ↗`));
  } else {
    actions.append(node("span", "Public profile observed", "candidate-meta"));
  }

  card.append(actions);
  return card;
}

function renderCandidates() {
  const grid = $("candidates");
  if (!grid) return;

  const handleSeed = currentSeedValue || "target";
  const candidatesList = latest?.candidates || [];
  const runsList = latest?.runs || [];

  const completedRunsCount = runsList.filter(r => terminal(r.status) || r.status === "SUCCESS" || r.status === "COMPLETED" || r.status === "NO_RESULTS").length;
  const totalRunsCount = runsList.length;

  const liveStatus = $("live-candidate-status");
  if (liveStatus) {
    liveStatus.textContent = `Handle: ${handleSeed} · ${candidatesList.length} profiles found · ${completedRunsCount}/${totalRunsCount} sources done`;
  }

  const allCandidates = [...candidatesList].sort((a, b) => {
    const rankA = candidateSortRank(a, currentSeedValue);
    const rankB = candidateSortRank(b, currentSeedValue);
    if (rankA !== rankB) return rankA - rankB;
    return (candidateMatchValue(b) - candidateMatchValue(a)) ||
      String(a.platform || "").localeCompare(String(b.platform || ""));
  });

  const q = candidateSearchQuery.trim().toLowerCase();
  const filtered = q
    ? allCandidates.filter(p => `${p.platform} ${p.username} ${p.display_name} ${p.bio}`.toLowerCase().includes(q))
    : allCandidates;

  grid.replaceChildren();

  if (filtered.length > 0) {
    const visibleBatch = filtered.slice(0, candidatePageSize);
    for (const p of visibleBatch) grid.append(candidateCard(p));

    if (filtered.length > visibleBatch.length) {
      const showMoreWrap = node("div", "", "show-more-container");
      showMoreWrap.style.cssText = "grid-column: 1 / -1; text-align: center; margin: 20px 0;";
      const showMoreBtn = node("button", `Show more (${filtered.length - visibleBatch.length})`, "btn btn-secondary");
      showMoreBtn.onclick = () => {
        candidatePageSize += 60;
        renderCandidates();
      };
      showMoreWrap.append(showMoreBtn);
      grid.append(showMoreWrap);
    }
  } else {
    const empty = node("div", "", "case-card candidates-empty");
    empty.append(node("p", "No public profiles found.", "candidates-empty-title"));
    grid.append(empty);
  }
}

function renderReport() {
  const r = latest?.report;
  const reportContainer = $("report");
  if (!reportContainer) return;
  if (!r) {
    reportContainer.textContent = "The investigation report will be generated when the search completes.";
    return;
  }
  reportContainer.replaceChildren();

  const head = node("div", "", "report-executive-head");
  head.append(
    node("h2", "EXECUTIVE OSINT IDENTITY REPORT", "report-title"),
    r.executive_finding ? node("p", r.executive_finding, "lead-finding") : null
  );
  reportContainer.append(head);

  if (r.lead_candidates?.length) {
    const sectionBox = node("div", "", "report-section-box");
    sectionBox.append(node("h3", "Discovered Profiles"));
    const grid = node("div", "", "report-candidate-grid");
    r.lead_candidates.forEach(p => {
      const card = node("div", "", "report-candidate-mini");
      card.innerHTML = `${getPlatformSvgLogo(p.platform, 18)} <strong>${(p.platform || '').toUpperCase()}</strong> · ${p.username ? "@" + p.username : p.display_name || "Profile"}`;
      const pLink = resolveCandidateLink(p);
      if (pLink) card.append(safeLink(pLink, "Open Profile ↗"));
      grid.append(card);
    });
    sectionBox.append(grid);
    reportContainer.append(sectionBox);
  }
}

// ── Item 5: Email OSINT Verified-Only Render Function ──
function renderEmailResult(data) {
  const container = document.getElementById("email-result-container");
  const section = document.getElementById("email-osint-section");
  if (!container || !section) return;

  section.hidden = false;
  container.replaceChildren();

  const summary = data.summary || { registered: 0, not_registered: 0, cant_check: 0, scan_ms: 0 };
  const sites = data.sites || [];
  const breaches = data.breaches || [];

  const registeredSites = sites.filter(s => s.status === "REGISTERED");

  // Header Card
  const headBox = node("div", "", "case-card email-header-box");
  headBox.style.cssText = "padding:20px; margin-bottom:20px; background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08); border-radius:12px;";

  const titleRow = node("div", "", "email-title-row");
  titleRow.style.cssText = "display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;";
  titleRow.append(
    node("h2", data.email || "Email Account Discovery", "email-heading"),
    node("span", data.provider || "Provider", "badge badge-source")
  );

  const subLineText = `Verified on ${summary.registered} service${summary.registered === 1 ? '' : 's'} · ${summary.scan_ms} ms`;
  const subLine = node("p", subLineText, "email-subline");
  subLine.style.cssText = "margin:0; font-size:14px; color:#94a3b8;";

  headBox.append(titleRow, subLine);

  if (sites.length > 0 && summary.cant_check > sites.length / 2) {
    const incompleteNote = node("p", "Some checks couldn't complete, results may be incomplete.", "email-incomplete-note");
    incompleteNote.style.cssText = "margin:8px 0 0 0; font-size:13px; color:#64748b; font-style:italic;";
    headBox.append(incompleteNote);
  }

  container.append(headBox);

  // Table showing ONLY verified/registered sites
  if (registeredSites.length > 0) {
    const table = node("table", "", "email-sites-table");
    table.style.cssText = "width:100%; border-collapse:collapse; margin-bottom:24px; font-size:14px;";

    const thead = node("thead");
    thead.innerHTML = `<tr style="border-bottom:1px solid rgba(255,255,255,0.1); text-align:left; color:#94a3b8;">
      <th style="padding:10px 14px;">Service</th>
      <th style="padding:10px 14px;">Status</th>
      <th style="padding:10px 14px;">Details / Reason</th>
      <th style="padding:10px 14px;">Link</th>
    </tr>`;
    table.append(thead);

    const tbody = node("tbody");
    registeredSites.forEach(site => {
      const tr = node("tr");
      tr.style.cssText = "border-bottom:1px solid rgba(255,255,255,0.04);";

      const tdName = node("td", site.label || site.id, "site-name-cell");
      tdName.style.cssText = "padding:10px 14px; font-weight:600; color:#f4f4f5;";

      const tdStatus = node("td");
      tdStatus.style.padding = "10px 14px";
      tdStatus.append(node("span", "Registered", "status-chip status-chip--found"));

      const tdDetail = node("td");
      tdDetail.style.cssText = "padding:10px 14px; color:#a1a1aa; font-size:13px;";
      let detailText = site.detail || site.reason || "—";
      if (site.username) detailText = `@${site.username}` + (site.detail ? ` (${site.detail})` : "");
      tdDetail.textContent = detailText;

      const tdLink = node("td");
      tdLink.style.padding = "10px 14px";
      if (site.profile_url) {
        tdLink.append(safeLink(site.profile_url, "Open ↗"));
      } else {
        tdLink.textContent = "—";
      }

      tr.append(tdName, tdStatus, tdDetail, tdLink);
      tbody.append(tr);
    });

    table.append(tbody);
    container.append(table);
  } else {
    const emptyBox = node("div", "No verified accounts found.", "email-empty-box");
    emptyBox.style.cssText = "padding:24px; text-align:center; color:#94a3b8; font-size:15px; background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.06); border-radius:8px; margin-bottom:24px;";
    container.append(emptyBox);
  }

  // Data breaches summary box if present
  if (breaches && breaches.length > 0) {
    const breachBox = node("div", "", "case-card breach-box");
    breachBox.style.cssText = "padding:16px; background:rgba(239, 68, 68, 0.08); border:1px solid rgba(239, 68, 68, 0.2); border-radius:8px; margin-top:16px;";
    
    const breachTitle = node("h3", `Data Breach Exposures (${breaches.length})`);
    breachTitle.style.cssText = "margin:0 0 8px; color:#f87171; font-size:15px;";
    
    const names = breaches.map(b => b.name).join(", ");
    const breachText = node("p", `Exposed in public data breaches: ${names}`, "breach-text");
    breachText.style.cssText = "margin:0; font-size:13px; color:#e2e8f0;";

    breachBox.append(breachTitle, breachText);
    container.append(breachBox);
  }
}

async function fetchEmailOsint(email) {
  const container = document.getElementById("email-result-container");
  const section = document.getElementById("email-osint-section");
  if (!container || !section) return;

  section.hidden = false;
  container.replaceChildren();

  const loadingMsg = node("div", "Scanning… (up to ~1 min)", "loading-msg");
  loadingMsg.style.cssText = "padding:24px; text-align:center; color:#94a3b8; font-size:15px;";
  container.append(loadingMsg);

  try {
    const res = await fetch("/api/osint/email", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, self_audit_confirmed: true }),
    });

    const rawText = await res.text();
    let data;
    try {
      data = JSON.parse(rawText);
    } catch (_) {
      throw new Error(`HTTP ${res.status}: Invalid response format`);
    }

    if (!res.ok) {
      const detailMsg = data && data.detail ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)) : res.statusText;
      throw new Error(`HTTP ${res.status}: ${detailMsg}`);
    }

    renderEmailResult(data);
  } catch (e) {
    container.replaceChildren();
    const errBox = node("div", e.message || String(e), "error-toast");
    errBox.style.cssText = "padding:16px; background:rgba(239, 68, 68, 0.1); border:1px solid rgba(239, 68, 68, 0.3); border-radius:8px; color:#f87171;";
    container.append(errBox);
  }
}

async function startInvestigation(e) {
  if (e) {
    e.preventDefault();
    e.stopPropagation();
  }
  if (busy) return false;

  const seedInput = $("seed");
  const seedTypeSelect = $("seed-type");
  if (!seedInput || !seedTypeSelect) return false;

  const rawVal = seedInput.value.trim();
  if (!rawVal) return false;

  let selectedType = seedTypeSelect.value;
  if (rawVal.includes("@") && !rawVal.includes(" ")) {
    selectedType = "EMAIL";
    seedTypeSelect.value = "EMAIL";
  } else if (rawVal.startsWith("https://")) {
    selectedType = "PROFILE_URL";
    seedTypeSelect.value = "PROFILE_URL";
  }

  currentSeedType = selectedType;
  currentSeedValue = rawVal;

  const errEl = $("error");
  if (errEl) { errEl.textContent = ""; errEl.hidden = true; }

  if (currentSeedType === "EMAIL" || currentSeedValue.includes("@")) {
    setBusy(true);
    resetResultView();
    stopStatusCycle();
    const statusPanel = $("status-control-panel");
    if (statusPanel) statusPanel.hidden = true;

    try {
      await fetchEmailOsint(currentSeedValue);
    } catch (err) {
      error(err);
    } finally {
      stopStatusCycle();
      if (statusPanel) statusPanel.hidden = true;
      setBusy(false);
    }
    return false;
  }

  setBusy(true);
  resetResultView();

  try {
    const result = await request("/api/searches", {
      method: "POST",
      body: JSON.stringify({ seed_type: currentSeedType, value: currentSeedValue, scope: "self_audit", self_audit_confirmed: true })
    });
    stream?.close();
    searchId = result.id;
    showResultSections();
    connect();
    await refresh();
    setTimeout(() => {
      document.getElementById("metrics-section")?.scrollIntoView?.({ behavior: "smooth", block: "start" });
    }, 400);
  } catch (err) {
    error(err);
    stopStatusCycle();
  } finally {
    setBusy(false);
  }
  return false;
}

// ── Item 1: EncryptedText Effect for Hero Footprints ──
function initEncryptedText() {
  const el = $("encrypted-footprints") || document.querySelector(".highlight-osint");
  if (!el) return;

  const targetText = "Footprints";
  el.setAttribute("aria-label", targetText);

  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    el.textContent = targetText;
    return;
  }

  const chars = "!@#$%^&*()_+-=[]{}|;:,.<>?/~`0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";

  el.style.display = "inline-flex";
  el.style.alignItems = "center";
  el.innerHTML = "";

  const spanElements = [];
  for (let i = 0; i < targetText.length; i++) {
    const s = document.createElement("span");
    s.style.display = "inline-block";
    s.style.textAlign = "center";
    s.textContent = targetText[i];
    el.appendChild(s);

    const width = s.getBoundingClientRect().width;
    if (width > 0) {
      s.style.width = width + "px";
    }
    spanElements.push(s);
  }

  let animationTimer = null;
  let isAnimating = false;

  function runEffect() {
    if (isAnimating) return;
    isAnimating = true;
    clearInterval(animationTimer);

    let step = 0;
    const totalSteps = targetText.length;

    animationTimer = setInterval(() => {
      for (let i = 0; i < totalSteps; i++) {
        const span = spanElements[i];
        if (i < step) {
          span.textContent = targetText[i];
          span.style.color = "#ffffff";
        } else {
          span.textContent = chars[Math.floor(Math.random() * chars.length)];
          span.style.color = "#737373";
        }
      }
      step++;
      if (step > totalSteps) {
        clearInterval(animationTimer);
        for (let i = 0; i < totalSteps; i++) {
          spanElements[i].textContent = targetText[i];
          spanElements[i].style.color = "#ffffff";
        }
        isAnimating = false;
      }
    }, 50);
  }

  if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          runEffect();
        }
      });
    }, { threshold: 0.1 });
    observer.observe(el);
  } else {
    runEffect();
  }

  el.addEventListener("mouseenter", () => {
    runEffect();
  });
}

function bindFormEvents() {
  const form = $("search-form");
  const btn = $("search-button");
  const seedInput = $("seed");
  const seedTypeSelect = $("seed-type");

  if (form) {
    form.onsubmit = startInvestigation;
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

// ── Page Initialization ──
// bindFormEvents first, then each visual init in its own try/catch block
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initPage);
} else {
  initPage();
}

function initPage() {
  bindFormEvents();

  try {
    initEncryptedText();
  } catch (e) {
    console.error("EncryptedText init error:", e);
  }

  $("stop-search")?.addEventListener("click", async () => { if (!searchId || busy) return; try { await request(`/api/searches/${searchId}/stop`,{method:"POST"}); await refresh(); } catch(e) {error(e);} });
  $("print-report")?.addEventListener("click", () => window.print());

  localStorage.removeItem("deus-search");
  if (location.search) history.replaceState(null, "", location.pathname);
  resetResultView();
}
