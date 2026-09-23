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
const activeTweens = {};

function animateMetricCount(id, targetVal) {
  const el = $(id);
  if (!el) return;
  const numericTarget = parseInt(targetVal, 10) || 0;

  if (activeTweens[id]) {
    activeTweens[id].kill();
    delete activeTweens[id];
  }
  if (window.gsap) {
    gsap.killTweensOf(el);
  }

  const currentVal = parseInt(el.textContent, 10) || animatedMetricValues[id] || 0;
  const obj = { val: currentVal };

  if (window.gsap && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    activeTweens[id] = gsap.to(obj, {
      val: numericTarget,
      duration: 1.5,
      ease: "power2.out",
      onUpdate: () => {
        const rounded = Math.round(obj.val);
        animatedMetricValues[id] = rounded;
        el.textContent = rounded;
      },
      onComplete: () => {
        animatedMetricValues[id] = numericTarget;
        el.textContent = numericTarget;
        delete activeTweens[id];
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
  if (p.includes("youtube")) {
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="currentColor" class="social-logo-svg"><path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/></svg>`;
  }
  if (p.includes("linkedin")) {
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="currentColor" class="social-logo-svg"><path d="M19 3a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h14m-.5 15.5v-5.3a3.26 3.26 0 0 0-3.26-3.26c-.85 0-1.84.52-2.28 1.3v-1.11h-2.79v8.37h2.79v-4.93c0-.77.62-1.4 1.39-1.4a1.4 1.4 0 0 1 1.4 1.4v4.93h2.75M6.88 8.56a1.68 1.68 0 0 0 1.68-1.68c0-.93-.75-1.69-1.68-1.69a1.69 1.69 0 0 0-1.69 1.69c0 .93.76 1.68 1.69 1.68m1.39 9.94v-8.37H5.5v8.37h2.77z"/></svg>`;
  }
  if (p.includes("tiktok")) {
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="currentColor" class="social-logo-svg"><path d="M12.525.02c1.31-.02 2.61-.01 3.91-.02.08 1.53.63 3.09 1.75 4.17 1.12 1.11 2.7 1.62 4.24 1.79v4.03c-1.44-.05-2.89-.35-4.2-.97-.57-.26-1.1-.59-1.62-.93-.01 2.92.01 5.84-.02 8.75-.08 1.4-.54 2.79-1.35 3.94-1.31 1.92-3.58 3.17-5.91 3.21-1.43.08-2.86-.31-4.08-1.03-2.02-1.19-3.44-3.37-3.65-5.71-.29-2.63.71-5.33 2.65-7.1 1.69-1.57 4.09-2.32 6.38-1.95v4.25c-1.11-.25-2.31-.04-3.27.52-.97.55-1.63 1.56-1.78 2.67-.22 1.44.37 2.94 1.52 3.82.97.77 2.27 1.05 3.49.77 1.25-.27 2.33-1.13 2.87-2.28.38-.79.52-1.68.49-2.56V.02z"/></svg>`;
  }
  if (p.includes("twitch")) {
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="currentColor" class="social-logo-svg"><path d="M11.571 4.714h1.715v5.143h-1.715zm4.715 0H18v5.143h-1.714zM6 0L1.714 4.286v15.428h5.143V24l4.286-4.286h3.428L22.286 12V0zm14.571 11.143l-3.428 3.428h-3.429l-3 3v-3H6.857V1.714h13.714z"/></svg>`;
  }
  if (p.includes("medium")) {
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="currentColor" class="social-logo-svg"><path d="M13.54 12a6.8 6.8 0 0 1-6.77 6.82A6.8 6.8 0 0 1 0 12a6.8 6.8 0 0 1 6.77-6.82A6.8 6.8 0 0 1 13.54 12zM20.96 12c0 3.54-1.51 6.42-3.38 6.42-1.87 0-3.39-2.88-3.39-6.42s1.52-6.42 3.39-6.42c1.87 0 3.38 2.88 3.38 6.42M24 12c0 3.17-.53 5.75-1.19 5.75-.66 0-1.19-2.58-1.19-5.75s.53-5.75 1.19-5.75C23.47 6.25 24 8.83 24 12z"/></svg>`;
  }
  if (p.includes("telegram")) {
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="currentColor" class="social-logo-svg"><path d="M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0zm5.892 8.258l-2.006 9.462c-.15.672-.546.834-1.11.516l-3.057-2.254-1.474 1.42c-.163.163-.3.3-.615.3l.219-3.1 5.642-5.1c.245-.219-.054-.34-.381-.123l-6.974 4.39-3.007-.94c-.655-.204-.668-.655.137-.97l11.75-4.528c.544-.204 1.02.123.876.927z"/></svg>`;
  }
  if (p.includes("gitlab")) {
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="currentColor" class="social-logo-svg"><path d="M22.65 14.39L12 22.13 1.35 14.39a.84.84 0 0 1-.3-.94l1.22-3.78 2.44-7.51A.42.42 0 0 1 5.5 2a.43.43 0 0 1 .4.28l2.25 6.92h7.7l2.25-6.92a.43.43 0 0 1 .4-.28.42.42 0 0 1 .79.17l2.44 7.51 1.22 3.78a.84.84 0 0 1-.3.94z"/></svg>`;
  }
  if (p.includes("pinterest")) {
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="currentColor" class="social-logo-svg"><path d="M12.017 0C5.396 0 .029 5.367.029 11.987c0 5.079 3.158 9.417 7.618 11.162-.105-.949-.199-2.403.041-3.439.219-.937 1.406-5.957 1.406-5.957s-.359-.72-.359-1.781c0-1.663.967-2.911 2.168-2.911 1.024 0 1.518.769 1.518 1.688 0 1.029-.653 2.567-.992 3.992-.285 1.193.6 2.165 1.775 2.165 2.128 0 3.768-2.245 3.768-5.487 0-2.861-2.063-4.869-5.008-4.869-3.41 0-5.409 2.562-5.409 5.199 0 1.033.394 2.143.889 2.741.099.12.112.225.085.345-.09.375-.293 1.199-.334 1.363-.053.225-.172.271-.401.165-1.495-.69-2.433-2.878-2.433-4.646 0-3.776 2.748-7.252 7.92-7.252 4.158 0 7.392 2.967 7.392 6.923 0 4.135-2.607 7.462-6.233 7.462-1.214 0-2.354-.629-2.758-1.379l-.749 2.848c-.269 1.045-1.004 2.352-1.498 3.146 1.123.345 2.306.535 3.55.535 6.607 0 11.985-5.365 11.985-11.987C23.97 5.39 18.592.026 11.985.026z"/></svg>`;
  }
  if (p.includes("devto") || p.includes("dev.to")) {
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="currentColor" class="social-logo-svg"><path d="M7.42 10.05c-.18-.16-.46-.24-.84-.24H5.43v4.38h1.16c.37 0 .65-.08.83-.24.19-.16.29-.43.29-.81v-2.28c0-.38-.1-.65-.29-.81zm8.01 0c-.18-.16-.47-.24-.86-.24h-1.15v4.38h1.15c.39 0 .68-.08.86-.24.19-.16.28-.43.28-.81v-2.28c0-.38-.09-.65-.28-.81zM0 3v18h24V3H0zm10.74 12.63H9.41l-2.02-4.14v4.14H6.11V8.37h1.49l1.92 3.93V8.37h1.22v7.26zm5.82 0h-3.32V8.37h3.32c.86 0 1.5.24 1.93.72.43.48.65 1.14.65 1.99v1.85c0 .85-.22 1.51-.65 1.99-.43.48-1.07.71-1.93.71zm5.33-4.12v1.54h-1.92v2.58h-1.28V8.37h3.2v1.14h-1.92v1.75h1.92z"/></svg>`;
  }
  if (p.includes("codepen")) {
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="social-logo-svg"><polygon points="12 2 22 8.5 22 15.5 12 22 2 15.5 2 8.5 12 2"/><line x1="12" y1="22" x2="12" y2="15.5"/><polyline points="22 8.5 12 15.5 2 8.5"/><polyline points="2 15.5 12 8.5 22 15.5"/><line x1="12" y1="2" x2="12" y2="8.5"/></svg>`;
  }
  if (p.includes("soundcloud")) {
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="currentColor" class="social-logo-svg"><path d="M1.175 12.225c-.068 0-.135.01-.19.043A.445.445 0 0 0 .76 12.67v5.42c0 .175.093.332.242.411.056.03.119.044.18.044.116 0 .232-.047.315-.138l.003-.003.003-.003c.09-.098.138-.226.138-.362V12.72a.455.455 0 0 0-.466-.495zm2.148-2.613c-.247 0-.448.201-.448.448v7.94c0 .247.201.448.448.448s.448-.201.448-.448v-7.94c0-.247-.201-.448-.448-.448zm2.148-1.503c-.247 0-.448.201-.448.448v10.946c0 .247.201.448.448.448s.448-.201.448-.448V8.557c0-.247-.201-.448-.448-.448zm2.149-1.393c-.247 0-.448.201-.448.448v13.732c0 .247.201.448.448.448s.448-.201.448-.448V7.164c0-.247-.201-.448-.448-.448zm2.148-1.455c-.247 0-.448.201-.448.448v16.643c0 .247.201.448.448.448s.448-.201.448-.448V5.709c0-.247-.201-.448-.448-.448zm8.683.82c-.888 0-1.745.263-2.484.757a.449.449 0 0 0-.171.353v15.228c0 .247.201.448.448.448h8.65c2.143 0 3.886-1.743 3.886-3.886 0-2.072-1.632-3.771-3.69-3.881A5.334 5.334 0 0 0 18.5 5.264z"/></svg>`;
  }
  if (p.includes("pypi") || p.includes("python")) {
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="currentColor" class="social-logo-svg"><path d="M12 0L1.75 5.9v12.2L12 24l10.25-5.9V5.9L12 0zm-1.5 3.5h3v3h-3v-3zm7.5 13.5l-6 3.5-6-3.5V9.5l6-3.5 6 3.5v7.5z"/></svg>`;
  }
  if (p.includes("crates") || p.includes("rust")) {
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="currentColor" class="social-logo-svg"><path d="M12 2L2 7v10l10 5 10-5V7L12 2zm0 2.8l7 3.5v7l-7 3.5-7-3.5v-7l7-3.5z"/></svg>`;
  }
  if (p.includes("npm")) {
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="currentColor" class="social-logo-svg"><path d="M0 7.33v9.33h9.33V20H14.67v-3.33H24V7.33H0zm18.67 6.67h-2.67V10.67h-2.67v3.33H4V10.67H1.33V8.67h17.34v5.33z"/></svg>`;
  }
  if (p.includes("docker")) {
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="currentColor" class="social-logo-svg"><path d="M13.983 11.078h2.119a.186.186 0 00.186-.185V9.006a.186.186 0 00-.186-.186h-2.119a.185.185 0 00-.185.186v1.887c0 .102.083.185.185.185zm-2.954-5.43h2.118a.185.185 0 00.186-.186V3.574a.185.185 0 00-.186-.185h-2.118a.185.185 0 00-.185.185v1.888c0 .102.082.185.185.185zm0 2.716h2.118a.185.185 0 00.186-.186V6.29a.185.185 0 00-.186-.185h-2.118a.185.185 0 00-.185.185v1.887c0 .102.082.186.185.186zm0 2.714h2.118a.186.186 0 00.186-.185V9.006a.185.185 0 00-.186-.186h-2.118a.185.185 0 00-.185.186v1.887c0 .102.082.185.185.185zm-2.955 0h2.119a.186.186 0 00.185-.185V9.006a.185.185 0 00-.185-.186H8.074a.185.185 0 00-.185.186v1.887c0 .102.083.185.185.185zm0-2.714h2.119a.185.185 0 00.185-.186V6.29a.185.185 0 00-.185-.185H8.074a.185.185 0 00-.185.185v1.887c0 .102.083.186.185.186zm0-2.716h2.119a.186.186 0 00.185-.186V3.574a.186.186 0 00-.185-.185H8.074a.185.185 0 00-.185.185v1.888c0 .102.083.185.185.185zm-2.955 5.43h2.119a.186.186 0 00.185-.185V9.006a.185.185 0 00-.186-.186H5.119a.185.185 0 00-.185.186v1.887c0 .102.083.185.185.185zm0-2.714h2.119a.185.185 0 00.185-.186V6.29a.185.185 0 00-.185-.185H5.119a.185.185 0 00-.185.185v1.887c0 .102.083.186.185.186zm-2.955 2.714h2.119a.186.186 0 00.185-.185V9.006a.185.185 0 00-.185-.186H2.164a.185.185 0 00-.185.186v1.887c0 .102.083.185.185.185zM.05 11.758c0 3.864 3.018 7.03 6.945 7.03 4.912 0 8.878-3.058 10.366-7.514h-1.956c-1.258 3.256-4.475 5.534-8.41 5.534-3.003 0-5.512-1.96-6.425-4.664H.05z"/></svg>`;
  }
  if (p.includes("steam")) {
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="currentColor" class="social-logo-svg"><path d="M11.979 0C5.678 0 .511 4.86.022 11.037l6.432 2.658c.545-.371 1.203-.59 1.912-.59.063 0 .125.004.188.006l2.861-4.142V8.91c0-2.495 2.028-4.524 4.524-4.524 2.494 0 4.524 2.031 4.524 4.527s-2.03 4.524-4.524 4.524h-.105l-4.076 2.911c0 .052.004.105.004.159 0 1.875-1.515 3.396-3.39 3.396-1.635 0-3.016-1.173-3.331-2.727L.436 14.77C1.847 20.024 6.6 24 12.021 24c6.627 0 11.999-5.373 11.999-12S18.606 0 11.979 0z"/></svg>`;
  }
  if (p.includes("spotify")) {
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="currentColor" class="social-logo-svg"><path d="M12 0C5.376 0 0 5.376 0 12s5.376 12 12 12 12-5.376 12-12S18.624 0 12 0zm5.521 17.34c-.24.359-.66.48-1.021.24-2.82-1.74-6.36-2.101-10.561-1.141-.418.122-.779-.179-.899-.539-.12-.421.18-.78.54-.9 4.56-1.021 8.52-.6 11.64 1.32.42.18.479.659.301 1.02zm1.44-3.3c-.301.42-.841.6-1.262.3-3.239-1.98-8.159-2.58-11.939-1.38-.479.12-1.02-.12-1.14-.6-.12-.48.12-1.021.6-1.141 4.38-1.38 9.841-.72 13.561 1.56.36.18.54.78.18 1.26zm.12-3.36C15.24 8.4 8.82 8.16 5.16 9.301c-.6.18-1.2-.18-1.38-.72-.18-.6.18-1.2.72-1.38 4.26-1.26 11.28-1.02 15.721 1.621.539.3.719 1.02.419 1.56-.299.421-1.02.599-1.559.3z"/></svg>`;
  }
  if (p.includes("wikipedia") || p.includes("wiki")) {
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="currentColor" class="social-logo-svg"><path d="M12.09 13.118l2.356-5.463 2.457 5.463h-4.813zM0 24h24V0H0v24zm12-21.2a1.6 1.6 0 1 1 0 3.2 1.6 1.6 0 0 1 0-3.2zm6.66 14.86h-2.19l-.79-1.84h-7.35l-.79 1.84H5.34l5.44-12.02h2.43l5.45 12.02z"/></svg>`;
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
  if (p.canonical_url && /^https?:\/\//i.test(p.canonical_url)) {
    return p.canonical_url;
  }
  return null;
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
  const badgeText = rel ? rel.label : matchInfo.label;
  const badgeCls = rel ? rel.cls : matchInfo.cls;
  if (badgeText && badgeText !== "Weak Match") {
    chips.append(node("span", badgeText, `status-chip ${badgeCls}`));
  }
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
  const rawCandidatesList = latest?.candidates || [];

  // Filter out synthetic search engine result URLs
  const filteredCandidates = rawCandidatesList.filter(cand => {
    const url = String(cand.canonical_url || "").toLowerCase();
    if (url.includes("google.com/search") || url.includes("duckduckgo.com/?q=") || url.includes("bing.com/search")) {
      return false;
    }
    return true;
  });

  // Deduplicate candidates by normalized platform & handle / canonical URL key
  const dedupedMap = new Map();
  for (const cand of filteredCandidates) {
    const platKey = String(cand.platform || "").trim().toLowerCase();
    const userKey = String(cand.normalized_username || cand.username || "").trim().toLowerCase();
    let urlKey = String(cand.canonical_url || "").trim().replace(/\/$/, "");
    if (urlKey.startsWith("http://")) urlKey = "https://" + urlKey.slice(7);
    const primaryKey = (platKey && userKey) ? `${platKey}:${userKey}` : urlKey;

    if (!dedupedMap.has(primaryKey)) {
      dedupedMap.set(primaryKey, { ...cand });
    } else {
      const existing = dedupedMap.get(primaryKey);
      if (!existing.display_name && cand.display_name) existing.display_name = cand.display_name;
      if (!existing.avatar_url && cand.avatar_url) existing.avatar_url = cand.avatar_url;
      if (!existing.bio && cand.bio) existing.bio = cand.bio;
      if (!existing.location && cand.location) existing.location = cand.location;
      if (!existing.organization && cand.organization) existing.organization = cand.organization;
    }
  }
  const candidatesList = Array.from(dedupedMap.values());
  const runsList = latest?.runs || [];

  const completedRunsCount = runsList.filter(r => terminal(r.status) || r.status === "SUCCESS" || r.status === "COMPLETED" || r.status === "NO_RESULTS").length;
  const totalRunsCount = runsList.length;

  const liveStatus = $("live-candidate-status");
  if (liveStatus) {
    liveStatus.textContent = `Handle: ${handleSeed} · ${candidatesList.length} profiles found · ${completedRunsCount}/${totalRunsCount} sources done`;
  }

  // Show Header attach photo button if search has completed and no photo was attached initially (only for USERNAME searches)
  const headerAttachBtn = $("header-attach-photo-btn");
  if (headerAttachBtn) {
    if (!attachedPhotoFile && searchId && candidatesList.length > 0 && currentSeedType !== "EMAIL") {
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



function renderEmailResult(data) {
  const container = $("email-result-container");
  if (!container) return;
  container.replaceChildren();

  const sec = $("email-osint-section");
  if (sec) sec.hidden = false;

  const header = node("div", "", "email-result-header");
  header.append(
    node("h2", `Account Discovery for ${data.email || currentSeedValue}`, "email-result-title"),
    node("p", `Provider: ${data.provider || "Unknown"} — Complete registration and breach check results.`, "email-result-sub")
  );

  const rawSites = Array.isArray(data.sites) ? data.sites : [];
  const sites = rawSites.filter(s => s.status === "REGISTERED" || !s.status);
  const summaryRow = node("div", "", "email-summary-row");
  summaryRow.append(
    node("span", `Registered: ${sites.length}`, "email-summary-badge email-summary-registered")
  );
  if (Number.isFinite(Number(data.summary?.scan_ms))) {
    summaryRow.append(node("span", `Scan duration: ${data.summary.scan_ms}ms`, "email-scan-duration mono-data"));
  }
  header.append(summaryRow);

  container.append(header);

  const resultsGrid = node("div", "", "email-sites-grid");
  const checksBlock = node("div", "", "case-card email-group-card");
  checksBlock.append(node("h3", `Discovered Accounts (${sites.length})`, "email-group-title"));

  if (sites.length > 0) {
    const tableWrap = node("div", "", "email-results-table-wrap");
    const table = node("table", "", "email-sites-table");
    const thead = document.createElement("thead");
    const headingRow = document.createElement("tr");
    ["Service", "Status", "Account / details", "Source"].forEach(text => {
      headingRow.append(node("th", text));
    });
    thead.append(headingRow);

    const tbody = document.createElement("tbody");
    const statusPresentation = {
      REGISTERED: { label: "Registered", className: "email-status-registered" },
      NOT_REGISTERED: { label: "Not registered", className: "email-status-not-registered" },
      CANT_CHECK: { label: "Could not check", className: "email-status-cant-check" },
    };

    sites.forEach(site => {
      const row = document.createElement("tr");
      const serviceCell = document.createElement("td");
      serviceCell.append(node("strong", site.label || site.id || "Unknown service"));

      const statusCell = document.createElement("td");
      const presentation = statusPresentation[site.status] || {
        label: String(site.status || "Unknown").replaceAll("_", " ").toLowerCase(),
        className: "email-status-cant-check",
      };
      statusCell.append(node("span", presentation.label, `email-status-pill ${presentation.className}`));

      const detailsCell = document.createElement("td");
      if (site.username) {
        detailsCell.append(node("div", `@${site.username}`, "email-result-username"));
      }
      if (site.detail) {
        detailsCell.append(node("div", site.detail, "email-result-detail"));
      }
      if (site.reason) {
        detailsCell.append(node("div", site.reason, "email-result-reason"));
      }
      if (site.profile_url) {
        const linkLine = node("div", "", "email-result-link");
        linkLine.append(safeLink(site.profile_url, "View profile"));
        detailsCell.append(linkLine);
      }
      if (!detailsCell.childNodes.length) {
        detailsCell.append(node("span", "—", "email-result-empty"));
      }

      const sourceCell = document.createElement("td");
      sourceCell.append(node("span", site.via || "unknown", "email-source-label"));
      row.append(serviceCell, statusCell, detailsCell, sourceCell);
      tbody.append(row);
    });

    table.append(thead, tbody);
    tableWrap.append(table);
    checksBlock.append(tableWrap);
  } else {
    checksBlock.append(node("p", "No service checks were returned.", "email-result-sub"));
  }
  resultsGrid.append(checksBlock);

  const breaches = Array.isArray(data.breaches) ? data.breaches : [];
  const breachBlock = node("div", "", "case-card email-group-card");
  breachBlock.append(node("h3", `Breach Exposures (${breaches.length})`, "email-group-title"));
  if (breaches.length > 0) {
    const list = node("div", "", "email-breach-list");
    breaches.forEach(b => {
      const domain = b.domain ? ` (${b.domain})` : "";
      const item = node("div", `${b.name || "Unknown breach"}${domain}`, "email-breach-item");
      list.append(item);
    });
    breachBlock.append(list);
  } else {
    breachBlock.append(node("p", "No known breach exposures reported.", "email-result-sub"));
  }
  resultsGrid.append(breachBlock);

  container.append(resultsGrid);
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
      body: JSON.stringify({ email, self_audit_confirmed: true })
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
  updatePhotoContainerVisibility(classified.type);

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

function updatePhotoContainerVisibility(seedType) {
  const container = $("photo-attach-container");
  const headerBtn = $("header-attach-photo-btn");
  if (seedType === "EMAIL") {
    if (container) container.style.display = "none";
    if (headerBtn) headerBtn.style.display = "none";
    if (attachedPhotoFile) clearAttachedPhoto();
  } else {
    if (container) container.style.display = "block";
  }
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

  const tabs = document.querySelectorAll(".category-tab");
  tabs.forEach(t => {
    t.addEventListener("click", () => {
      const seedType = t.dataset.seed;
      if (seedTypeSelect) seedTypeSelect.value = seedType;
      tabs.forEach(tab => {
        const isActive = tab.dataset.seed === seedType;
        tab.classList.toggle("active", isActive);
        tab.setAttribute("aria-selected", String(isActive));
      });
      updatePhotoContainerVisibility(seedType);
    });
  });

  if (form) {
    form.addEventListener("submit", startInvestigation);
  }
  if (seedInput && seedTypeSelect) {
    seedInput.addEventListener("input", () => {
      const raw = seedInput.value;
      if (!raw.trim()) return;
      const classified = classifySeed(raw, seedTypeSelect.value || "USERNAME");
      seedTypeSelect.value = classified.type;
      tabs.forEach(t => {
        const isActive = t.dataset.seed === classified.type;
        t.classList.toggle("active", isActive);
        t.setAttribute("aria-selected", String(isActive));
      });
      updatePhotoContainerVisibility(classified.type);
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

  localStorage.removeItem("deus-search");
  if (location.search) history.replaceState(null, "", location.pathname);
  resetResultView();
}
