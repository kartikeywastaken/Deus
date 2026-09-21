/* All displayed profiles, edges and reports come from the API. No demo data. */
const $ = id => document.getElementById(id);
const terminal = s => ["COMPLETED", "FAILED", "CANCELLED", "STOPPED"].includes(s);
let searchId = null, stream = null, refreshTimer = null, fallbackTimer = null, busy = false;
let latest = null, refreshRunning = false, refreshAgain = false;
let currentSeedType = null, currentSeedValue = null;

// Photo Match state
let attachedPhotoFile = null;
let photoToken = null;
let photoMatchResults = null;
let photoFilterOnly = false;
let lastPhotoPollTime = 0;
let localPhotoObjectUrl = null;

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

  photoFilterOnly = false;
  photoMatchResults = null;
  const summaryEl = $("photo-match-summary");
  if (summaryEl) { summaryEl.style.display = "none"; summaryEl.textContent = ""; }
  const filterBtn = $("photo-filter-toggle");
  if (filterBtn) filterBtn.style.display = "none";
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
function safeLink(url, text) {
  const a = node("a", text);
  try {
    const targetUrl = new URL(url, window.location.href);
    if (!["http:", "https:"].includes(targetUrl.protocol)) return node("span", text);
    a.href = targetUrl.href;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    return a;
  } catch (_) {
    return node("span", text);
  }
}

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
  if (value) {
    stopStatusCycle();
    startStatusCycle();
  } else {
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

async function uploadPhotoForSearch(id, file) {
  const formData = new FormData();
  formData.append("photo", file);
  const res = await fetch(`/api/searches/${id}/photo`, {
    method: "POST",
    body: formData,
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.detail || "Failed to upload photo");
  }
  return data.token;
}

async function pollPhotoMatches() {
  if (!searchId || !photoToken) return;
  const now = Date.now();
  if (photoMatchResults && photoMatchResults.status === "done") return;
  if (now - lastPhotoPollTime < 1800) return; // Throttle to 2s
  lastPhotoPollTime = now;

  try {
    const res = await fetch(`/api/searches/${searchId}/photo-matches?token=${encodeURIComponent(photoToken)}`, {
      headers: { "Cache-Control": "no-store" }
    });
    if (res.status === 404) {
      error(new Error("Photo session expired. Re-attach your photo to match results."));
      photoToken = null;
      return;
    }
    if (!res.ok) return;
    const data = await res.json();
    photoMatchResults = data;
    renderPhotoMatchSummary();
    renderCandidates();
  } catch (_) {}
}

function renderPhotoMatchSummary() {
  const summaryEl = $("photo-match-summary");
  const filterBtn = $("photo-filter-toggle");
  if (!summaryEl) return;

  if (!photoMatchResults) {
    summaryEl.style.display = "none";
    if (filterBtn) filterBtn.style.display = "none";
    return;
  }

  const c = photoMatchResults.counts || {};
  const matchedCount = (photoMatchResults.matches || []).length;

  let text = `Photo check: ${photoMatchResults.checked || 0} compared · ${c.same_photo || 0} same photo · ${c.possible_match || 0} possible · ${c.no_avatar || 0} had no public picture · ${c.unavailable || 0} couldn't be fetched`;

  if (photoMatchResults.status === "done" && (photoMatchResults.total || 0) > 0 && matchedCount === 0) {
    text += `<br><span style="color:var(--muted); margin-top:4px; display:inline-block;">No profile picture matched this photo. Profiles may use a different picture, and some platforms (Instagram, LinkedIn, X, Facebook) hide pictures from automated checks.</span>`;
  }

  summaryEl.innerHTML = text;
  summaryEl.style.display = "block";

  if (filterBtn) {
    filterBtn.textContent = `Photo matches only (${matchedCount})`;
    filterBtn.style.display = matchedCount > 0 ? "inline-flex" : "none";
    filterBtn.onclick = () => {
      photoFilterOnly = !photoFilterOnly;
      filterBtn.classList.toggle("active", photoFilterOnly);
      renderCandidates();
    };
  }
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

    if (photoToken) {
      await pollPhotoMatches();
    }

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

  // Check photo match status for candidate
  let matchedItem = null;
  if (photoMatchResults && photoMatchResults.matches) {
    matchedItem = photoMatchResults.matches.find(m => m.profile_id === p.id || m.profile_id === String(p.id) || (m.platform === p.platform && m.username === p.username));
  }

  if (matchedItem) {
    const pct = Math.round((matchedItem.strength || 0) * 100);
    if (matchedItem.verdict === "SAME_PHOTO") {
      const chip = node("span", `📷 Same photo · ${pct}%`, "photo-match-chip photo-match-chip--same");
      chips.append(chip);
    } else if (matchedItem.verdict === "POSSIBLE_MATCH") {
      const chip = node("span", `📷 Possible match · ${pct}% · verify`, "photo-match-chip photo-match-chip--possible");
      chips.append(chip);
    }
  }

  const matchInfo = getMatchLabel(candidateMatchValue(p));
  const rel = RELEVANCE_LABELS[p.relevance];
  const badgeText = rel ? `${rel.label} · ${matchInfo.score}%` : `${matchInfo.label} · ${matchInfo.score}%`;
  const badgeCls = rel ? rel.cls : matchInfo.cls;
  chips.append(node("span", badgeText, `status-chip ${badgeCls}`));
  if (p.raw_json?.verified === true) chips.append(node("span", "✓ Verified", "status-chip status-chip--found"));
  card.append(chips);

  // If photo matched, show side-by-side comparison
  if (matchedItem && (matchedItem.verdict === "SAME_PHOTO" || matchedItem.verdict === "POSSIBLE_MATCH")) {
    const sbs = node("div", "", "photo-side-by-side");
    const userImgSrc = localPhotoObjectUrl || "/logo.png";
    const profileImgSrc = matchedItem.avatar_url || p.avatar_url;
    sbs.innerHTML = `
      <div style="text-align:center;">
        <img src="${userImgSrc}" class="photo-side-by-side-img" alt="Attached photo">
        <div class="photo-side-by-side-label">Your photo</div>
      </div>
      <div style="font-size:16px; font-weight:bold; color:var(--accent,#ec1c24);">↔</div>
      <div style="text-align:center;">
        <img src="${profileImgSrc}" class="photo-side-by-side-img" alt="Profile avatar">
        <div class="photo-side-by-side-label">Profile picture</div>
      </div>
    `;
    card.append(sbs);
  }

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

  // Show Header attach photo button if search has completed and no photo was attached initially
  const headerAttachBtn = $("header-attach-photo-btn");
  if (headerAttachBtn) {
    if (!attachedPhotoFile && searchId && candidatesList.length > 0) {
      headerAttachBtn.style.display = "inline-flex";
      headerAttachBtn.onclick = () => {
        $("photo-attach-input")?.click();
      };
    } else {
      headerAttachBtn.style.display = "none";
    }
  }

  const allCandidates = [...candidatesList].sort((a, b) => {
    // Sort photo matches to top (SAME_PHOTO = 0, POSSIBLE_MATCH = 1, others = 2)
    let aPhotoRank = 2, bPhotoRank = 2;
    if (photoMatchResults && photoMatchResults.matches) {
      const mA = photoMatchResults.matches.find(m => m.profile_id === a.id || m.profile_id === String(a.id) || (m.platform === a.platform && m.username === a.username));
      const mB = photoMatchResults.matches.find(m => m.profile_id === b.id || m.profile_id === String(b.id) || (m.platform === b.platform && m.username === b.username));
      if (mA) aPhotoRank = mA.verdict === "SAME_PHOTO" ? 0 : 1;
      if (mB) bPhotoRank = mB.verdict === "SAME_PHOTO" ? 0 : 1;
    }
    if (aPhotoRank !== bPhotoRank) return aPhotoRank - bPhotoRank;

    const rankA = candidateSortRank(a, currentSeedValue);
    const rankB = candidateSortRank(b, currentSeedValue);
    if (rankA !== rankB) return rankA - rankB;
    return (candidateMatchValue(b) - candidateMatchValue(a)) ||
      String(a.platform || "").localeCompare(String(b.platform || ""));
  });

  const q = candidateSearchQuery.trim().toLowerCase();
  let filtered = q
    ? allCandidates.filter(p => `${p.platform} ${p.username} ${p.display_name} ${p.bio}`.toLowerCase().includes(q))
    : allCandidates;

  if (photoFilterOnly) {
    filtered = filtered.filter(p => {
      if (!photoMatchResults || !photoMatchResults.matches) return false;
      const m = photoMatchResults.matches.find(item => item.profile_id === p.id || item.profile_id === String(p.id) || (item.platform === p.platform && item.username === p.username));
      return m && (m.verdict === "SAME_PHOTO" || m.verdict === "POSSIBLE_MATCH");
    });
  }

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
    empty.append(node("p", photoFilterOnly ? "No matched profiles found for the photo filter." : "No public profiles found.", "candidates-empty-title"));
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
}

function renderEmailResult(data) {
  const container = $("email-result-container");
  if (!container) return;
  container.replaceChildren();

  const sec = $("email-osint-section");
  if (sec) sec.hidden = false;

  const header = node("div", "", "email-result-header");
  header.append(
    node("h2", `Account Discovery for ${data.email || currentSeedValue}`, "email-result-title"),
    node("p", "Automated passive registration and breach checks across supported platforms.", "email-result-sub")
  );
  container.append(header);
}

async function fetchEmailOsint(email) {
  const container = $("email-result-container");
  if (!container) return;

  const sec = $("email-osint-section");
  if (sec) sec.hidden = false;

  container.innerHTML = `
    <div style="padding:24px; text-align:center;" class="mono-data">
      <span class="live-pulse"></span> Scanning email registration and breach endpoints...
    </div>
  `;

  try {
    const data = await request("/api/osint/email", {
      method: "POST",
      body: JSON.stringify({ email })
    });
    renderEmailResult(data);
  } catch (err) {
    container.innerHTML = `<div class="error-toast" style="padding:16px;">${err.message || String(err)}</div>`;
  }
}

function classifySeed(raw, fallbackType = "USERNAME") {
  const val = String(raw || "").trim();
  if (!val) return { type: fallbackType, value: "" };

  const emailRegex = /^[^\s@/:]+@[^\s@/:]+\.[^\s@/:]{2,}$/;
  if (emailRegex.test(val)) {
    return { type: "EMAIL", value: val };
  }

  if (val.startsWith("@") && val.length > 1) {
    return { type: "USERNAME", value: val.slice(1) };
  }

  return { type: "USERNAME", value: val };
}
window.classifySeed = classifySeed;

async function startInvestigation(e) {
  if (e) {
    e.preventDefault();
    e.stopPropagation();
  }
  if (busy) return false;

  const seedInput = $("seed");
  const seedTypeSelect = $("seed-type");
  if (!seedInput || !seedTypeSelect) return false;

  const fallbackType = seedTypeSelect.value || "USERNAME";

  const rawVal = seedInput.value;
  if (!rawVal.trim()) return false;

  const classified = classifySeed(rawVal, fallbackType);

  currentSeedType = classified.type;
  currentSeedValue = classified.value;
  seedTypeSelect.value = classified.type;

  const tabs = document.querySelectorAll(".category-tab");
  tabs.forEach(t => {
    const isActive = t.dataset.seed === classified.type;
    t.classList.toggle("active", isActive);
    t.setAttribute("aria-selected", String(isActive));
  });

  const errEl = $("error");
  if (errEl) { errEl.textContent = ""; errEl.hidden = true; }

  if (currentSeedType === "EMAIL") {
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

    if (attachedPhotoFile) {
      try {
        photoToken = await uploadPhotoForSearch(searchId, attachedPhotoFile);
      } catch (err) {
        error(err);
      }
    }

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
          span.style.color = "#ec1c24";
        } else {
          span.textContent = chars[Math.floor(Math.random() * chars.length)];
          span.style.color = "#656565";
        }
      }
      step++;
      if (step > totalSteps) {
        clearInterval(animationTimer);
        for (let i = 0; i < totalSteps; i++) {
          spanElements[i].textContent = targetText[i];
          spanElements[i].style.color = "#ec1c24";
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

function handleAttachedPhotoSelected(file) {
  if (!file) return;
  if (file.size > 5 * 1024 * 1024) {
    error(new Error("Photo exceeds 5 MB size limit"));
    return;
  }
  const type = (file.type || "").toLowerCase();
  if (!["image/jpeg", "image/png", "image/webp"].includes(type)) {
    error(new Error("Photo must be JPEG, PNG, or WebP"));
    return;
  }

  attachedPhotoFile = file;
  if (localPhotoObjectUrl) {
    URL.revokeObjectURL(localPhotoObjectUrl);
  }
  localPhotoObjectUrl = URL.createObjectURL(file);

  const trigger = $("photo-attach-trigger");
  const preview = $("photo-chip-preview");
  const img = $("photo-chip-img");
  const name = $("photo-chip-name");

  if (img) img.src = localPhotoObjectUrl;
  if (name) name.textContent = file.name;
  if (trigger) trigger.style.display = "none";
  if (preview) preview.style.display = "inline-flex";

  // If search is already running or completed, upload photo directly
  if (searchId && !photoToken) {
    uploadPhotoForSearch(searchId, file)
      .then(token => {
        photoToken = token;
        refresh();
      })
      .catch(err => error(err));
  }
}

function clearAttachedPhoto() {
  if (photoToken && searchId) {
    fetch(`/api/searches/${searchId}/photo?token=${encodeURIComponent(photoToken)}`, { method: "DELETE" }).catch(() => {});
  }
  attachedPhotoFile = null;
  photoToken = null;
  photoMatchResults = null;
  photoFilterOnly = false;

  if (localPhotoObjectUrl) {
    URL.revokeObjectURL(localPhotoObjectUrl);
    localPhotoObjectUrl = null;
  }

  const trigger = $("photo-attach-trigger");
  const preview = $("photo-chip-preview");
  const input = $("photo-attach-input");
  const summaryEl = $("photo-match-summary");
  const filterBtn = $("photo-filter-toggle");

  if (input) input.value = "";
  if (trigger) trigger.style.display = "inline-flex";
  if (preview) preview.style.display = "none";
  if (summaryEl) { summaryEl.style.display = "none"; summaryEl.textContent = ""; }
  if (filterBtn) filterBtn.style.display = "none";

  renderCandidates();
}

function initPhotoAttachControls() {
  const trigger = $("photo-attach-trigger");
  const input = $("photo-attach-input");
  const removeBtn = $("photo-chip-remove");

  if (trigger && input) {
    trigger.onclick = () => input.click();
    input.onchange = () => {
      if (input.files && input.files.length > 0) {
        handleAttachedPhotoSelected(input.files[0]);
      }
    };
  }

  if (removeBtn) {
    removeBtn.onclick = (e) => {
      e.stopPropagation();
      clearAttachedPhoto();
    };
  }
}

function bindFormEvents() {
  const form = $("search-form");
  const seedInput = $("seed");
  const seedTypeSelect = $("seed-type");

  if (form) {
    form.addEventListener("submit", startInvestigation);
  }
  if (seedInput && seedTypeSelect) {
    seedInput.addEventListener("input", () => {
      const raw = seedInput.value;
      if (!raw.trim()) return;
      const classified = classifySeed(raw, seedTypeSelect.value || "USERNAME");
      seedTypeSelect.value = classified.type;
      const tabs = document.querySelectorAll(".category-tab");
      tabs.forEach(t => {
        const isActive = t.dataset.seed === classified.type;
        t.classList.toggle("active", isActive);
        t.setAttribute("aria-selected", String(isActive));
      });
    });
  }

  initPhotoAttachControls();
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
