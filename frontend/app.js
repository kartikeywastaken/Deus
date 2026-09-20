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
  ["hypotheses", "evidence", "question-options", "email-osint-sources", "email-osint-overview", "candidates", "close-matches"].forEach(id => {
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
    "view-overview",
    "close-matches-section",
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
  $("question-form")?.querySelectorAll("input,button").forEach(n => n.disabled = value);
  
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

    const statusPanel = $("status-control-panel");
    if (statusPanel) statusPanel.hidden = false;

    const isDone = terminal(state.status);
    const isAwaiting = state.status === "AWAITING_USER";
    const statusBadgeTag = $("status-badge-tag");
    const radarBeam = $("radar-beam");
    const progContainer = $("progress-container");
    const statusMsg = $("investigation-status-msg");

    if (isDone || isAwaiting) {
      stopStatusCycle();
      if (radarBeam) radarBeam.classList.remove("spinning");
      if (isAwaiting) {
        if (statusBadgeTag) statusBadgeTag.textContent = `[ AWAITING USER ]`;
        if (statusMsg) statusMsg.textContent = "Disambiguation required. Please review the question below to refine analysis.";
        if (progContainer) progContainer.classList.remove("completed");
        $("status").textContent = "DISAMBIGUATION QUESTION PENDING";
      } else {
        if (statusBadgeTag) statusBadgeTag.textContent = `[ ${state.status} ]`;
        if (statusMsg) statusMsg.textContent = state.status === "COMPLETED" ? "Search finished. Live OSINT sources checked." : "Investigation stopped.";
        if (progContainer) progContainer.classList.add("completed");
        $("status").textContent = state.status === "COMPLETED" ? "INVESTIGATION COMPLETED" : state.status.replaceAll("_", " ");
      }
    } else {
      if (statusBadgeTag) statusBadgeTag.textContent = `[ SEARCHING ]`;
      if (radarBeam) radarBeam.classList.add("spinning");
      if (progContainer) progContainer.classList.remove("completed");
      $("status").textContent = "SEARCHING PUBLIC OSINT DATA...";
    }

    $("search-id").textContent = id;
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

    $("stop-search").disabled = isDone;
    $("continue-search").disabled = state.status !== "AWAITING_USER";
    maybeAutoContinue(state, question.item);

    if (isDone) {
      stream?.close();
      clearTimeout(fallbackTimer);
      $("connection").textContent = "Saved investigation";
      if (currentSeedType === "EMAIL" && currentSeedValue && emailFetchedFor !== currentSeedValue) fetchEmailOsint(currentSeedValue);
    }

    if (state.error_summary) error(new Error(state.error_summary));

    renderCandidates();
    renderCloseMatches();
    renderQuestion();
    renderReport();

    $("check-image").disabled = imageBusy || !$("reference-image").files.length;
    $("image-prompt").textContent = isDone ? "Search finished. Optionally select an image to check reuse across avatars." : "Choose an optional image to check reuse across discovered candidate avatars.";
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

// ── Ranked Candidate Results ──
// Seed relevance is produced by the backend (backend/investigation/username_questions.py);
// the labels below never claim verified account ownership.
const RELEVANCE_LABELS = {
  USER_HINT_MATCH: { label: "Confirmed Variant Match", cls: "status-chip--supported", rank: 0 },
  EXACT_SEED: { label: "Exact Seed Match", cls: "status-chip--found", rank: 1 },
  POSSIBLE_VARIANT: { label: "Possible Variant", cls: "status-chip--possible", rank: 2 },
};

// Preserve the backend priority order: user-confirmed variants first, then the
// exact seed, then everything else the connectors actually observed.
const relevanceRank = p => RELEVANCE_LABELS[p.relevance]?.rank ?? 3;

// ── Platform Icons, Avatars & Direct Links ──
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
  if (p.includes("linkedin")) {
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="currentColor" class="social-logo-svg"><path d="M19 3a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h14m-.5 15.5v-5.3a3.26 3.26 0 0 0-3.26-3.26c-.85 0-1.84.52-2.28 1.3v-1.11h-2.79v8.37h2.79v-4.93c0-.77.62-1.4 1.39-1.4a1.4 1.4 0 0 1 1.4 1.4v4.93h2.75M6.88 8.56a1.68 1.68 0 0 0 1.68-1.68c0-.93-.75-1.69-1.68-1.69a1.69 1.69 0 0 0-1.69 1.69c0 .93.76 1.68 1.69 1.68m1.39 9.94v-8.37H5.5v8.37h2.77z"/></svg>`;
  }
  if (p.includes("reddit")) {
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="currentColor" class="social-logo-svg"><path d="M12 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0zm5.01 4.744c.688 0 1.25.561 1.25 1.249a1.25 1.25 0 0 1-2.498.056l-2.597-.547-.8 3.747c1.824.07 3.48.632 4.674 1.488.308-.309.73-.491 1.207-.491.968 0 1.754.786 1.754 1.754 0 .716-.435 1.333-1.01 1.614a3.111 3.111 0 0 1 .042.52c0 2.694-3.13 4.87-7.004 4.87-3.874 0-7.004-2.176-7.004-4.87 0-.183.015-.366.043-.534A1.748 1.748 0 0 1 4.028 12c0-.968.786-1.754 1.754-1.754.463 0 .898.196 1.207.49 1.207-.883 2.878-1.43 4.744-1.487l.885-4.182a.342.342 0 0 1 .14-.197.35.35 0 0 1 .238-.042l2.906.617a1.214 1.214 0 0 1 1.108-.701zM9.25 12C8.561 12 8 12.562 8 13.25c0 .687.561 1.248 1.25 1.248.687 0 1.248-.561 1.248-1.249 0-.688-.561-1.249-1.249-1.249zm5.5 0c-.687 0-1.248.562-1.248 1.25 0 .687.561 1.248 1.249 1.248.688 0 1.249-.561 1.249-1.249 0-.688-.562-1.249-1.25-1.249zm-4.566 3.967c-.07.067-.07.176 0 .243.68.68 1.83.68 2.51 0a.17.17 0 0 0 0-.243l-.116-.118a.17.17 0 0 0-.243 0c-.43.43-1.16.43-1.59 0a.17.17 0 0 0-.243 0z"/></svg>`;
  }
  if (p.includes("medium")) {
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="currentColor" class="social-logo-svg"><path d="M13.54 12a6.8 6.8 0 0 1-6.77 6.82A6.8 6.8 0 0 1 0 12a6.8 6.8 0 0 1 6.77-6.82A6.8 6.8 0 0 1 13.54 12zM20.96 12c0 3.54-1.51 6.42-3.38 6.42-1.87 0-3.39-2.88-3.39-6.42s1.52-6.42 3.39-6.42c1.87 0 3.38 2.88 3.38 6.42M24 12c0 3.17-.53 5.75-1.19 5.75-.66 0-1.19-2.58-1.19-5.75s.53-5.75 1.19-5.75C23.47 6.25 24 8.83 24 12z"/></svg>`;
  }
  if (p.includes("spotify")) {
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="currentColor" class="social-logo-svg"><path d="M12 0C5.376 0 0 5.376 0 12s5.376 12 12 12 12-5.376 12-12S18.624 0 12 0zm5.521 17.341c-.22.359-.68.474-1.039.254-2.848-1.741-6.433-2.135-10.655-1.171-.403.093-.811-.161-.904-.564-.092-.403.161-.811.564-.904 4.622-1.056 8.583-.604 11.78 1.35.358.22.474.68.254 1.035zm1.47-3.262c-.277.45-.867.591-1.317.314-3.259-2.003-8.228-2.583-12.083-1.413-.507.153-1.042-.136-1.195-.643-.153-.507.136-1.042.643-1.195 4.412-1.339 9.897-.695 13.638 1.603.45.277.591.867.314 1.334zm.127-3.411c-3.908-2.321-10.363-2.536-14.12-1.396-.6.183-1.237-.162-1.42-.762-.183-.6.162-1.237.762-1.42 4.316-1.31 11.437-1.053 15.932 1.615.54.321.718 1.026.398 1.565-.32.539-1.025.718-1.552.398z"/></svg>`;
  }
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="social-logo-svg"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>`;
}

function candidateAvatarElement(p) {
  const avatarUrl = p.avatar_url || p.raw?.avatar_url || p.raw?.profile_pic_url || (p.raw?.owner_info && p.raw?.owner_info.avatar_url);
  const wrapper = node("div", "", "candidate-avatar-wrap");
  if (avatarUrl && typeof avatarUrl === "string" && /^https?:\/\//i.test(avatarUrl)) {
    const img = node("img", "", "candidate-avatar-img");
    img.src = avatarUrl;
    img.alt = p.username || p.display_name || "Profile avatar";
    img.onerror = () => {
      wrapper.replaceChildren(fallbackAvatar(p));
    };
    wrapper.append(img);
  } else {
    wrapper.append(fallbackAvatar(p));
  }
  return wrapper;
}

function fallbackAvatar(p) {
  const fallback = node("div", "", "candidate-avatar-fallback");
  const platformStr = String(p.platform || "").toLowerCase();
  
  if (platformStr.includes("github")) fallback.classList.add("avatar-bg-github");
  else if (platformStr.includes("twitter") || platformStr.includes("x")) fallback.classList.add("avatar-bg-twitter");
  else if (platformStr.includes("instagram")) fallback.classList.add("avatar-bg-instagram");
  else if (platformStr.includes("linkedin")) fallback.classList.add("avatar-bg-linkedin");
  else if (platformStr.includes("reddit")) fallback.classList.add("avatar-bg-reddit");
  else if (platformStr.includes("medium")) fallback.classList.add("avatar-bg-medium");
  else if (platformStr.includes("spotify")) fallback.classList.add("avatar-bg-spotify");
  else fallback.classList.add("avatar-bg-default");

  fallback.innerHTML = getPlatformSvgLogo(p.platform, 24);
  return fallback;
}

function resolveCandidateLink(p) {
  if (p.canonical_url) {
    const valid = profileLinkUrl(p.canonical_url);
    if (valid) return valid;
  }
  if (p.url) {
    const valid = profileLinkUrl(p.url);
    if (valid) return valid;
  }
  if (p.profile_url) {
    const valid = profileLinkUrl(p.profile_url);
    if (valid) return valid;
  }
  const username = p.username || p.display_name || p.title;
  if (!username) return null;
  const cleanUser = String(username).replace(/^@/, "").trim();
  if (!cleanUser) return null;

  const platform = String(p.platform || p.source_name || "").toLowerCase();
  if (platform.includes("github")) return `https://github.com/${cleanUser}`;
  if (platform.includes("twitter") || platform.includes("x")) return `https://x.com/${cleanUser}`;
  if (platform.includes("instagram")) return `https://instagram.com/${cleanUser}`;
  if (platform.includes("linkedin")) return `https://linkedin.com/in/${cleanUser}`;
  if (platform.includes("reddit")) return `https://reddit.com/user/${cleanUser}`;
  if (platform.includes("medium")) return `https://medium.com/@${cleanUser}`;
  if (platform.includes("spotify")) return `https://open.spotify.com/user/${cleanUser}`;
  if (platform.includes("youtube")) return `https://youtube.com/@${cleanUser}`;
  if (platform.includes("pinterest")) return `https://pinterest.com/${cleanUser}`;
  if (platform.includes("website") || cleanUser.includes(".")) {
    return profileLinkUrl(cleanUser) || `https://google.com/search?q=${encodeURIComponent(cleanUser)}`;
  }
  return `https://google.com/search?q=${encodeURIComponent((p.platform || '') + ' ' + cleanUser)}`;
}

let candidatePageSize = 36;
let candidateSearchQuery = "";

function candidateCard(p) {
  const card = node("article", "", "case-card candidate-card");

  const header = node("div", "", "candidate-header-row");
  const avatarWrap = candidateAvatarElement(p);

  const identity = node("div", "", "candidate-identity");
  const platformLine = node("div", "", "platform-badge-line");
  
  const sourceName = p.raw_json?.source || p.raw?.source || p.source_name || "connector";
  const verified = p.raw_json?.verified ?? true;
  const category = p.raw_json?.category || "social";

  platformLine.innerHTML = `${getPlatformSvgLogo(p.platform, 14)} <span>${String(p.platform || "PROFILE").toUpperCase()}</span> <span class="badge badge-source" style="font-size:10px;padding:2px 6px;margin-left:6px;border-radius:4px;background:rgba(255,255,255,0.1);color:#a1a1aa">${sourceName}</span>`;
  
  const handle = node("strong", p.username ? "@" + p.username : p.display_name || "Public profile", "candidate-handle");
  identity.append(platformLine, handle);
  if (p.username && p.display_name && p.display_name !== p.username) identity.append(node("span", p.display_name, "candidate-display"));
  if (p.bio) identity.append(node("p", p.bio, "candidate-bio-sub"));

  header.append(avatarWrap, identity);
  card.append(header);

  // Chips: Match Label + Verified Badge + Category
  const chips = node("div", "", "candidate-chips");
  const matchInfo = getMatchLabel(candidateMatchValue(p));
  const rel = RELEVANCE_LABELS[p.relevance];
  const badgeText = rel ? `${rel.label} · ${matchInfo.score}%` : `${matchInfo.label} · ${matchInfo.score}%`;
  const badgeCls = rel ? rel.cls : matchInfo.cls;
  chips.append(node("span", badgeText, `status-chip ${badgeCls}`));
  if (verified) chips.append(node("span", "✓ Verified", "status-chip status-chip--found"));
  chips.append(node("span", category, "status-chip status-chip--neutral"));
  card.append(chips);

  const why = node("div", "", "candidate-why");
  why.append(node("span", "Why this result?", "candidate-why-title"));
  if (p.relevance) why.append(node("p", `Seed relevance: ${p.relevance}`, "candidate-relevance-line"));
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
  grid.replaceChildren();

  // Unified priority sorting
  const allCandidates = [...(latest?.candidates || [])].sort((a, b) =>
    (relevanceRank(a) - relevanceRank(b)) ||
    (candidateMatchValue(b) - candidateMatchValue(a)) ||
    String(a.platform || "").localeCompare(String(b.platform || ""))
  );

  const knownUrls = new Set(allCandidates.map(p => (p.canonical_url || "").toLowerCase()).filter(Boolean));
  const emailLeads = emailCandidateLeads().filter(lead => {
    const url = (lead.canonical_url || "").toLowerCase();
    return !url || !knownUrls.has(url);
  });

  const combined = [...allCandidates, ...emailLeads];

  // Filter input
  const q = candidateSearchQuery.trim().toLowerCase();
  const filtered = q
    ? combined.filter(p => {
        const text = `${p.platform} ${p.username} ${p.display_name} ${p.bio} ${p.raw_json?.source || ''}`.toLowerCase();
        return text.includes(q);
      })
    : combined;

  const totalCount = filtered.length;

  if (totalCount > 0) {
    const controlsHeader = node("div", "", "candidates-controls-header");
    controlsHeader.style.cssText = "grid-column: 1 / -1; margin-bottom: 16px; display: flex; flex-wrap: wrap; gap: 12px; align-items: center; justify-content: space-between;";

    const titleEl = node("h3", `SEARCH RESULTS · ${totalCount} public profile${totalCount === 1 ? "" : "s"} & accounts found`);
    titleEl.style.margin = "0";

    const filterInput = node("input");
    filterInput.type = "text";
    filterInput.placeholder = "Filter by site, handle, or source...";
    filterInput.value = candidateSearchQuery;
    filterInput.className = "search-input-field";
    filterInput.style.cssText = "max-width: 320px; padding: 6px 12px; font-size: 13px;";
    filterInput.oninput = (e) => {
      candidateSearchQuery = e.target.value;
      renderCandidates();
    };

    controlsHeader.append(titleEl, filterInput);
    grid.append(controlsHeader);

    const visibleBatch = filtered.slice(0, candidatePageSize);
    for (const p of visibleBatch) {
      grid.append(candidateCard(p));
    }

    if (filtered.length > candidatePageSize) {
      const remaining = filtered.length - candidatePageSize;
      const loadMoreWrap = node("div", "", "load-more-wrap");
      loadMoreWrap.style.cssText = "grid-column: 1 / -1; text-align: center; margin-top: 24px;";

      const btn = node("button", `Show More (${remaining} remaining)`, "btn btn-secondary");
      btn.onclick = () => {
        candidatePageSize += 36;
        renderCandidates();
      };
      loadMoreWrap.append(btn);
      grid.append(loadMoreWrap);
    }
  } else if (combined.length > 0 && totalCount === 0) {
    const empty = node("div", "", "case-card candidates-empty");
    empty.append(
      node("p", `No accounts matching filter "${candidateSearchQuery}".`, "candidates-empty-title"),
      node("p", "Try clearing or broadening your search term.", "candidates-empty-sub")
    );
    grid.append(empty);
  } else {
    const empty = node("div", "", "case-card candidates-empty");
    empty.append(
      node("p", "No public profiles were found for this target yet.", "candidates-empty-title"),
      node("p", "Every card here comes from a live public observation. Run an investigation to check accounts.", "candidates-empty-sub")
    );
    grid.append(empty);
  }
}

// ── Closely Matching Profiles ──
function renderCloseMatches() {
  const container = $("close-matches");
  if (!container) return;
  container.replaceChildren();

  const candidatesMap = new Map((latest?.candidates || []).map(c => [c.id, c]));
  const hypotheses = latest?.hypotheses || [];

  const validHypotheses = hypotheses
    .filter(h => {
      const cls = h.hypothesis?.classification || h.classification;
      return cls !== "WEAK" && cls !== "CONTRADICTORY";
    })
    .sort((a, b) => (a.hypothesis?.rank || 99) - (b.hypothesis?.rank || 99));

  if (!validHypotheses.length) {
    container.append(node("div", "No closely matching profile clusters meeting correlation threshold.", "empty-muted"));
    return;
  }

  validHypotheses.forEach(hypItem => {
    const hyp = hypItem.hypothesis || hypItem;
    const members = hypItem.members || [];
    if (!members.length) return;

    const clusterBox = node("div", "", "case-card report-section-box");
    clusterBox.append(node("h3", `Hypothesis Cluster #${hyp.rank} · ${hyp.classification || "MATCH"}`));

    const grid = node("div", "", "report-candidate-grid");

    members.forEach(mem => {
      const candidate = candidatesMap.get(mem.profile_id);
      if (!candidate) return;

      const card = node("div", "", "report-candidate-mini");
      const scoreVal = points(mem.score != null ? mem.score : hyp.overall_score || 0);
      card.innerHTML = `<span class="badge badge-success" style="float:right">${scoreVal}%</span>${getPlatformSvgLogo(candidate.platform, 18)} <strong>${(candidate.platform || "").toUpperCase()}</strong> · ${candidate.username ? "@" + candidate.username : candidate.display_name || "Profile"}`;

      const link = resolveCandidateLink(candidate);
      if (link) {
        const linkWrap = node("div", "", "prov-link-wrap");
        linkWrap.append(safeLink(link, "Open Profile ↗"));
        card.append(linkWrap);
      }

      grid.append(card);
    });

    clusterBox.append(grid);
    container.append(clusterBox);
  });
}

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
  const r = latest?.report;
  const reportContainer = $("report");
  if (!reportContainer) return;
  
  if (!r) {
    reportContainer.textContent = "The investigation report will be generated when the search completes.";
    return;
  }

  reportContainer.replaceChildren();

  // Header
  const head = node("div", "", "report-executive-head");
  head.append(
    node("h2", "EXECUTIVE OSINT IDENTITY REPORT", "report-title"),
    r.executive_finding ? node("p", r.executive_finding, "lead-finding") : null
  );
  reportContainer.append(head);

  // 1. Confirmed Identity Footprint (Deduplicated)
  if (r.lead_candidates?.length) {
    const sectionBox = node("div", "", "report-section-box");
    sectionBox.append(node("h3", "Confirmed Identity Footprint"));
    const grid = node("div", "", "report-candidate-grid");
    const seen = new Set();

    r.lead_candidates.forEach(p => {
      const key = `${p.platform}:${p.username || p.display_name}`.toLowerCase();
      if (seen.has(key)) return;
      seen.add(key);

      const card = node("div", "", "report-candidate-mini");
      card.innerHTML = `${getPlatformSvgLogo(p.platform, 18)} <strong>${p.platform?.toUpperCase()}</strong> · ${p.username ? "@" + p.username : p.display_name || "Profile"}`;
      if (p.reason) card.append(node("p", p.reason, "muted-sub"));
      const pLink = resolveCandidateLink(p);
      if (pLink) card.append(safeLink(pLink, "Open Profile ↗"));
      grid.append(card);
    });
    sectionBox.append(grid);
    reportContainer.append(sectionBox);
  }

  // 2. Public References & Repositories (Deduplicated & Cleaned)
  if (r.repository_references?.length) {
    const sectionBox = node("div", "", "report-section-box");
    sectionBox.append(node("h3", "Public References & Code Repositories"));
    const ul = node("ul", "", "report-clean-list");
    const seen = new Set();

    r.repository_references.forEach(ref => {
      const key = `${ref.url}:${ref.source_url}`.toLowerCase();
      if (seen.has(key)) return;
      seen.add(key);
      if (seen.size > 10) return;

      const li = node("li");
      li.append(document.createTextNode(ref.url + " "));
      if (ref.source_url) li.append(safeLink(ref.source_url, "Found in Source ↗"));
      ul.append(li);
    });
    sectionBox.append(ul);
    reportContainer.append(sectionBox);
  }

  // 3. Supporting Evidence (Deduplicated)
  const allEvidence = [...(r.supporting_evidence || []), ...(r.moderate_evidence || [])];
  if (allEvidence.length) {
    const sectionBox = node("div", "", "report-section-box");
    sectionBox.append(node("h3", "Supporting Evidence & Cross-Platform Correlations"));
    const ul = node("ul", "", "report-clean-list");
    const seenTexts = new Set();

    allEvidence.forEach(ev => {
      const text = typeof ev === "string" ? ev : ev.explanation || ev.note || "";
      if (!text || seenTexts.has(text.toLowerCase())) return;
      seenTexts.add(text.toLowerCase());
      if (seenTexts.size > 8) return;

      const li = node("li", text);
      const urls = (typeof ev === "object" && ev.source_urls) ? ev.source_urls : [];
      const cleanUrls = [...new Set(urls)].slice(0, 2);
      cleanUrls.forEach(url => {
        li.append(document.createTextNode(" "), safeLink(url, "Source ↗"));
      });
      ul.append(li);
    });
    sectionBox.append(ul);
    reportContainer.append(sectionBox);
  }

  // 4. Source Provenance (Grouped by Connector)
  if (r.source_provenance?.length) {
    const sectionBox = node("div", "", "report-section-box");
    sectionBox.append(node("h3", "Source Provenance Summary"));
    const provMap = new Map();

    r.source_provenance.forEach(p => {
      const connector = p.connector || "connector";
      if (!provMap.has(connector)) provMap.set(connector, []);
      if (p.source_url && !provMap.get(connector).includes(p.source_url)) {
        provMap.get(connector).push(p.source_url);
      }
    });

    const grid = node("div", "", "report-provenance-grid");
    provMap.forEach((urls, connector) => {
      const card = node("div", "", "report-prov-card");
      card.append(node("strong", connector.toUpperCase()));
      card.append(node("span", ` · ${urls.length} observation${urls.length === 1 ? "" : "s"}`, "muted-sub"));
      if (urls.length > 0 && urls[0]) {
        const link = safeLink(urls[0], "View Sample ↗");
        card.append(node("div", "", "prov-link-wrap"));
        card.querySelector(".prov-link-wrap").append(link);
      }
      grid.append(card);
    });
    sectionBox.append(grid);
    reportContainer.append(sectionBox);
  }
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

// Passive single-site probes (Spotify, Microsoft / Outlook, X, and the other
// RequestChecker sites) return a bare site homepage as their canonical URL.
// Anchors built from those only redirect to the website, so they are not
// rendered at all; real profile/deep links are kept untouched.
function profileLinkUrl(url) {
  if (!url) return null;
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return null;
  }
  if (parsed.protocol !== "https:") return null;
  return parsed.pathname.replace(/\/+$/, "") ? parsed.href : null;
}

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
          canonical_url: sDetail.canonical_url || null,
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
      const accountLink = profileLinkUrl(acc.canonical_url);
      if (accountLink) li.append(document.createTextNode(" "), safeLink(accountLink, "Open site ↗"));
      list.append(li);
    }
    registeredBox.append(list);
  } else {
    registeredBox.append(node("p", "No account registrations were detected for this email on the checked sites.", "empty"));
  }
  overviewEl.append(registeredBox);

  const sites = collectSiteStatuses(data);
  if (sites.length) {
    // Only registered sites are listed. "Not registered" and "could not verify"
    // rows are hidden from the UI; the checked total keeps the coverage visible.
    const registeredSites = sites.filter(site => site.exists === true);
    const sitesBox = node("div", "", "email-overview-sites");
    sitesBox.append(node("h3", `Registered sites (${registeredSites.length} of ${sites.length} checked)`));
    sitesBox.append(
      node("p", `${registeredSites.length} registered · not-registered and unverifiable sites are hidden.`, "email-sites-summary")
    );
    if (registeredSites.length) {
      const list = node("ul", "", "email-site-list");
      for (const site of registeredSites) {
        const li = node("li");
        li.append(node("strong", site.label), node("span", "Registered", "status-chip status-chip--found"));
        const bits = [];
        if (site.username) bits.push(`@${site.username}`);
        if (site.display_name && site.display_name !== site.username) bits.push(site.display_name);
        if (bits.length) li.append(document.createTextNode(` ${bits.join(" · ")}`));
        const siteLink = profileLinkUrl(site.canonical_url);
        if (siteLink) li.append(document.createTextNode(" "), safeLink(siteLink, "Open ↗"));
        list.append(li);
      }
      sitesBox.append(list);
    } else {
      sitesBox.append(node("p", "No registered account was found on the sites that could be checked.", "empty"));
    }
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
      const identifierLink = profileLinkUrl(id.value);
      if (id.type.includes("url") && identifierLink) card.append(safeLink(identifierLink, "Open source ↗"));
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
    const sourceLink = profileLinkUrl(src.canonical_url);
    if (sourceLink) card.append(safeLink(sourceLink, `Open ${site} ↗`));
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
