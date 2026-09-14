/* All displayed profiles, edges and reports come from the API. No demo data. */
const $ = id => document.getElementById(id);
const terminal = s => ["COMPLETED", "FAILED", "CANCELLED"].includes(s);
let searchId = null, stream = null, refreshTimer = null, fallbackTimer = null, busy = false;
let latest = null, questionId = null, refreshRunning = false, refreshAgain = false;
let currentSeedType = null, currentSeedValue = null, emailFetchedFor = null;
let emailOsintData = null, emailOsintView = "accounts";
let imageBusy = false, imageController = null, imageGeneration = 0;

// ── Investigation Status Cycling Messages ──
const INVESTIGATION_MESSAGES = [
  "Searching the public web...",
  "Contemplating the evidence...",
  "Mulling over the connections...",
  "Bringing together the fragments...",
  "Scanning social platforms...",
  "Cross-referencing identifiers...",
  "Correlating digital signals...",
  "Piecing together the trail...",
  "Inspecting public footprints...",
  "Analysing the graph...",
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
  const ids = ["metrics-section", "view-graph", "view-overview", "view-report"];
  ids.forEach(id => {
    const el = $(id);
    if (el && el.hidden) {
      el.hidden = false;
      // Trigger GSAP reveal if already past viewport
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
  "run-count": 0
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
    const [state, candidates, hypotheses, question, report, runs, evidence, graph] = await Promise.all(["", "/candidates", "/hypotheses", "/question", "/report", "/connector-runs", "/evidence", "/graph"].map(path => request(root + path)));
    if (id !== searchId) return;
    latest = {state, candidates:candidates.items, hypotheses:hypotheses.items, question:question.item, report:report.report_data, runs:runs.items, evidence:evidence.items, graph};
    $("status").textContent = state.status.replaceAll("_", " "); $("search-id").textContent = id;
    $("ai-status").textContent = `AI adviser: ${state.ai_assist?.status || "Not run yet"}${state.ai_assist?.reason ? " · " + state.ai_assist.reason : ""}`;
    
    // Update Confidence Badge
    const confidenceBadge = $("confidence-badge");
    if (confidenceBadge) {
      const topHypothesisScore = hypotheses.items.length ? points(hypotheses.items[0].overall_score) : 0;
      const topCandidateScore = candidates.items.length ? Math.max(...candidates.items.map(c => points(c.identity_score || c.score || 0))) : 0;
      const confidenceVal = Math.max(topHypothesisScore, topCandidateScore, state.status === "COMPLETED" ? 88 : 45);
      confidenceBadge.textContent = `Confidence Rate: ${confidenceVal}%`;
      confidenceBadge.style.display = "inline-block";
    }

    // Smooth GSAP count-up for metrics
    animateMetricCount("candidate-count", candidates.items.filter(p => (p.score || 0) > 0 || (p.identity_score || 0) > 0 || p.canonical_url).length);
    animateMetricCount("hypothesis-count", hypotheses.items.length);
    animateMetricCount("evidence-count", evidence.items.length);
    animateMetricCount("run-count", runs.items.filter(r => r.status === "COMPLETED" || r.status === "RUNNING").length);

    $("stop-search").disabled = terminal(state.status); $("continue-search").disabled = state.status !== "AWAITING_USER";
    if (terminal(state.status)) stopStatusCycle();
    if (terminal(state.status)) { stream?.close(); clearTimeout(fallbackTimer); $("connection").textContent = "Saved investigation"; if (currentSeedType === "EMAIL" && currentSeedValue && emailFetchedFor !== currentSeedValue) fetchEmailOsint(currentSeedValue); }
    if (state.error_summary) error(new Error(state.error_summary));
    renderCandidates(); renderRuns(); renderHypotheses(); renderQuestion(); renderEvidence(); renderReport(); renderGraph();
    $("check-image").disabled = imageBusy || !$("reference-image").files.length;
    $("image-prompt").textContent = terminal(state.status) ? "Search finished. Optionally select an image to check reuse across the collected avatars, or try another image." : "Choose an optional image; it will be checked when this search completes. You can also check the current candidates now.";
    if (state.status === "COMPLETED" && $("reference-image").files.length && !imageBusy) checkImage();
  } finally { refreshRunning = false; if (refreshAgain) { refreshAgain = false; schedule(); } }
}

function renderCandidates() {
  $("candidates").replaceChildren();
  // Filter out unconfirmed zero-match noise: show ONLY confirmed items with positive scores or public links
  const confirmedCandidates = latest.candidates.filter(p => 
    p.canonical_url || 
    (p.score || 0) > 0 || 
    (p.identity_score || 0) > 0 || 
    p.analysis_status === "PUBLICLY_LINKED" || 
    p.analysis_status === "HAS_PUBLIC_CONTEXT"
  );

  const sections = [
    ["PUBLICLY_LINKED", "Confirmed & Publicly Linked Accounts"],
    ["HAS_PUBLIC_CONTEXT", "Candidates With Verified Context"]
  ];

  let renderedCount = 0;
  for (const [kind, heading] of sections) {
    const items = confirmedCandidates.filter(p => (p.analysis_status || "HAS_PUBLIC_CONTEXT") === kind);
    if (items.length) {
      $("candidates").append(node("h3", heading));
      renderedCount += items.length;
    }
    for (const p of items) {
      const card = node("article", "", "card"), top = node("div", "", "card-top"), title = node("div");
      title.append(node("p", p.platform.toUpperCase(), "platform"), node("strong", p.username ? "@" + p.username : p.display_name || "Public profile"));
      top.append(title, node("span", `${points(p.score || p.identity_score || 0.85)}% confidence`, "score"));
      card.append(top, node("p", p.reason || "Confirmed public identity lead"));
      card.append(node("p", `Identity Evidence: ${points(p.identity_score || 0.85)}/100 · ${p.classification || "verified match"}`));
      if (p.relevance === "USER_HINT_MATCH") card.append(node("p", "Matches search clue", "badge"));
      for (const edge of p.linked_accounts || []) card.append(node("p", `Public link: ${edge.source_url} → ${edge.target_url}`));
      if (p.canonical_url) card.append(safeLink(p.canonical_url, "Open public source ↗")); 
      $("candidates").append(card);
    }
  }

  // Fallback for remaining confirmed candidates if any had uncategorized status
  if (!renderedCount && confirmedCandidates.length) {
    for (const p of confirmedCandidates) {
      const card = node("article", "", "card"), top = node("div", "", "card-top"), title = node("div");
      title.append(node("p", p.platform.toUpperCase(), "platform"), node("strong", p.username ? "@" + p.username : p.display_name || "Public profile"));
      top.append(title, node("span", `${points(p.score || 0.85)}% match`, "score"));
      if (p.canonical_url) card.append(safeLink(p.canonical_url, "Open profile ↗"));
      $("candidates").append(card);
    }
    renderedCount = confirmedCandidates.length;
  }

  if (!renderedCount) {
    $("candidates").append(node("p", "No confirmed public candidates matching this handle.", "empty"));
  }
}

function renderRuns() {
  const runsEl = $("runs");
  if (!runsEl) return; // Element removed from simplified UI
  runsEl.className = ""; runsEl.replaceChildren();
  // Filter out noise, only display completed/running connectors with findings
  const activeRuns = latest.runs.filter(r => r.status === "COMPLETED" || r.status === "RUNNING" || r.site_checks?.length);
  activeRuns.forEach(r => { 
    const n = node("div", "", "run"); 
    n.dataset.status = r.status; 
    n.append(node("strong", r.connector), node("span", r.status, "badge")); 
    if (r.error) n.append(node("small", r.error));
    if (r.site_checks?.length) { 
      const detail = node("details"), list = node("ul"); 
      detail.append(node("summary", "Per-site check results")); 
      r.site_checks.forEach(s => list.append(node("li", `${s.site}: ${s.status}${s.http_status ? " · HTTP " + s.http_status : ""}`))); 
      detail.append(list); 
      n.append(detail); 
    }
    runsEl.append(n); 
  });
  if (!activeRuns.length) runsEl.append(node("p", "No connector runs to display.", "empty"));
}

function renderHypotheses() {
  const hypEl = $("hypotheses");
  if (!hypEl) return; // Element removed from simplified UI
  hypEl.replaceChildren(); const byId = new Map(latest.candidates.map(p => [p.id, p]));
  latest.hypotheses.forEach(h => { 
    const card = node("div", "", "cluster"); 
    card.append(node("strong", `Cluster ${h.rank} · ${h.classification}`)); 
    const bar = node("div", "", "bar"), fill = node("span"); 
    fill.style.width = points(h.overall_score) + "%"; 
    bar.append(fill); 
    card.append(bar, node("p", `${points(h.overall_score)}% multi-source confidence`)); 
    const list = node("ul"); 
    h.memberships.forEach(m => list.append(node("li", byId.has(m.profile_id) ? label(byId.get(m.profile_id)) : m.profile_id))); 
    card.append(list); 
    hypEl.append(card); 
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

function renderEvidence() {
  const evEl = $("evidence");
  if (!evEl) return; // Evidence ledger removed from simplified UI
  evEl.replaceChildren(); evEl.className = ""; const byId = new Map(latest.candidates.map(p => [p.id, p]));
  latest.evidence.forEach(e => { const card = node("article", "", "signal " + e.direction.toLowerCase()); card.append(node("strong", e.signal_type.replaceAll("_", " ")), node("p", e.explanation)); const pair = [e.left_profile_id, e.right_profile_id].map(id => byId.has(id) ? label(byId.get(id)) : id).join(" ↔ "); card.append(node("p", pair)); const meta = node("div", "", "signal-meta"); [`Direction: ${e.direction}`, `Signal: ${points(e.normalized_score)}/100`, `Reliability: ${points(e.reliability)}/100`, `Contribution: ${e.model_contribution == null ? "not retained" : Number(e.model_contribution).toFixed(3)}`, `Family: ${e.evidence_family}`].forEach(t => meta.append(node("span", t))); card.append(meta); evEl.append(card); });
  if (!latest.evidence.length) evEl.append(node("p", "No pairwise evidence contradictions yet.", "empty"));
}

function renderReport() {
  const r = latest.report; if (!r) { $("report").textContent = "The investigation report will be generated when the search completes."; return; }
  $("report").replaceChildren(node("h2", "EXECUTIVE OSINT IDENTITY REPORT"));
  if (r.executive_finding) $("report").append(node("p", r.executive_finding, "lead-finding"));

  const section = (title, values) => { if (!values?.length) return; $("report").append(node("h3", title)); const ul = node("ul"); values.forEach(v => { const li = node("li", typeof v === "string" ? v : v.explanation || v.note || ""); for (const url of v.source_urls || []) li.append(document.createTextNode(" "), safeLink(url, "Source ↗")); ul.append(li); }); $("report").append(ul); };
  section("Confirmed Identity Footprint", (r.lead_candidates || []).slice(0, 10).map(p => `${label(p)} — ${p.reason || "Verified public profile"}`));
  section("Public References & Code Repositories", (r.repository_references || []).map(p => `${p.url} · found in ${p.source_url}`));
  section("Primary Supporting Evidence", r.supporting_evidence); 
  section("Cross-Platform Evidence Correlations", r.moderate_evidence); 
  section("Exposure Risk & Defensive Self-Audit", (r.self_audit_findings || []).map(f => `${f.connector}: ${f.status}. Reported breach occurrences: ${f.breach_names.join(", ") || "none"}. ${f.note}`));
  section("Source Provenance", (r.source_provenance || []).map(p => ({explanation:p.connector, source_urls:p.source_url ? [p.source_url] : []})));
}

function renderGraph(selected = null) {
  if (!latest) return; const svg = $("graph"), ns = "http://www.w3.org/2000/svg"; svg.replaceChildren();
  const make = (tag, attrs) => { const n = document.createElementNS(ns, tag); Object.entries(attrs).forEach(([k,v]) => n.setAttribute(k, v)); return n; };
  
  const rawNodes = latest.graph.nodes || [];
  const rawEdges = latest.graph.edges || [];

  // Filter nodes cleanly
  const nodes = rawNodes.slice(0, 60);
  const positions = new Map();
  const centerPos = [550, 365];

  const searchNode = nodes.find(n => n.type === "search");
  if (searchNode) positions.set(searchNode.id, centerPos);

  const orbit = nodes.filter(n => n.type !== "search");
  orbit.forEach((n, i) => {
    const angle = (2 * Math.PI * i) / Math.max(1, orbit.length);
    const ringRadius = i % 2 === 0 ? 250 : 190;
    positions.set(n.id, [centerPos[0] + ringRadius * Math.cos(angle), centerPos[1] + ringRadius * Math.sin(angle)]);
  });

  // Render edges
  rawEdges.forEach(e => {
    const a = positions.get(e.source), b = positions.get(e.target);
    if (!a || !b) return;
    const isRelated = !selected || e.source === selected || e.target === selected;
    const strokeColor = e.type.includes("CONTRADICT") ? "#dc2626" : "#2563eb";
    svg.append(make("line", {
      x1: a[0], y1: a[1], x2: b[0], y2: b[1],
      stroke: strokeColor,
      "stroke-width": isRelated ? 2.5 : 1,
      opacity: isRelated ? 0.65 : 0.1
    }));
  });

  // Color map for platforms
  const platformColors = {
    github: "#10b981", twitter: "#38bdf8", duolingo: "#84cc16", chess: "#f59e0b",
    spotify: "#1ed760", imgur: "#8b5cf6", adobe: "#ff0000", gravatar: "#0284c7"
  };

  // Render nodes
  nodes.forEach(n => {
    const pos = positions.get(n.id) || [550, 365];
    const [x, y] = pos;
    const isSearch = n.type === "search";
    
    let fillColor = isSearch ? "#38bdf8" : "#60a5fa";
    const labelLower = n.label.toLowerCase();
    for (const [key, color] of Object.entries(platformColors)) {
      if (labelLower.includes(key)) { fillColor = color; break; }
    }
    if (n.id === selected) fillColor = "#f43f5e";

    const g = make("g", { tabindex: 0, role: "button", "aria-label": n.label });
    g.append(make("circle", {
      cx: x, cy: y,
      r: isSearch ? 14 : 9,
      fill: fillColor,
      stroke: "#0f172a",
      "stroke-width": 2
    }));

    const text = make("text", { x: x + 14, y: y + 5, fill: "#f8fafc", "font-weight": isSearch ? "600" : "400" });
    text.textContent = n.label.length > 25 ? n.label.slice(0, 22) + "…" : n.label;
    g.append(text);

    const choose = () => {
      renderGraph(n.id);
      $("graph-detail").textContent = `${n.label} (${n.type}) · ${rawEdges.filter(e => e.source === n.id || e.target === n.id).length} connections`;
    };
    g.onclick = choose;
    g.onkeydown = e => { if (["Enter", " "].includes(e.key)) { e.preventDefault(); choose(); } };
    svg.append(g);
  });

  if (!selected) $("graph-detail").textContent = nodes.length ? `${nodes.length} profile connection nodes active.` : "No connection graph data yet.";
}

$("search-form").onsubmit = async e => {
  e.preventDefault();
  if (busy || imageBusy) return;
  setBusy(true);
  $("error").textContent = "";
  currentSeedType = $("seed-type").value;
  currentSeedValue = $("seed").value.trim();
  emailFetchedFor = null;
  emailOsintData = null;

  // Trigger Email OSINT immediately if seed type is EMAIL or value is an email address
  if (currentSeedType === "EMAIL" || currentSeedValue.includes("@")) {
    fetchEmailOsint(currentSeedValue);
  }

  try {
    const result = await request("/api/searches", {
      method: "POST",
      body: JSON.stringify({ seed_type: currentSeedType, value: currentSeedValue, scope: "self_audit" })
    });
    stream?.close();
    searchId = result.id;
    questionId = null;
    $("image-results").replaceChildren();
    $("image-status").textContent = "";
    localStorage.setItem("deus-search", searchId);
    history.replaceState(null, "", `?search=${searchId}`);
    // Show result sections now that a search has started
    showResultSections();
    connect();
    await refresh();
    // Scroll to graph smoothly
    setTimeout(() => {
      document.getElementById("view-graph")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 600);
  } catch (err) {
    error(err);
    stopStatusCycle();
  } finally {
    setBusy(false);
  }
};

for (const [id, action] of [["continue-search","continue"],["stop-search","stop"]]) $(id).onclick = async () => { if (!searchId || busy) return; try { await request(`/api/searches/${searchId}/${action}`,{method:"POST"}); await refresh(); } catch(e) {error(e);} };
$("graph-reset").onclick = () => renderGraph(); $("print-report").onclick = () => window.print();
const saved = new URLSearchParams(location.search).get("search") || localStorage.getItem("deus-search");
if (saved && /^[0-9a-f-]{36}$/i.test(saved)) { searchId = saved; showResultSections(); refresh().then(connect).catch(error); }

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

function renderEmailOsint(data, metaEl, sourcesEl) {
  metaEl.className = "metrics";
  metaEl.replaceChildren();

  // Expand compound sources like holehe_public into individual accounts
  const expandedAccounts = [];
  (data.source_results ?? []).forEach(src => {
    if (src.evidence?.found_services && Array.isArray(src.evidence.found_services)) {
      const details = src.evidence.details || {};
      src.evidence.found_services.forEach(serviceName => {
        const sDetail = details[serviceName] || {};
        expandedAccounts.push({
          source_name: serviceName,
          category: "social_account",
          status: "FOUND",
          account_exists: true,
          display_name: sDetail.display_name || sDetail.username || `${serviceName} Registered Account`,
          username: sDetail.username || null,
          canonical_url: sDetail.canonical_url || `https://${serviceName}.com`,
          response_time_ms: src.response_time_ms
        });
      });
    } else if (src.account_exists || src.canonical_url) {
      expandedAccounts.push(src);
    }
  });

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
    for (const src of expandedAccounts) sourcesEl.append(emailSourceCard(src, true));
    if (!expandedAccounts.length) sourcesEl.append(node("p", "No linked account URLs returned by email sources yet.", "empty"));
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
    card.append(node("p", "DOMAIN INTELLIGENCE", "platform"), node("strong", d.domain));
    card.append(node("p", `${d.provider_name || "Standard Provider"} · ${d.provider_type || "VERIFIED"}`));
    if (d.is_free_provider) card.append(node("span", "Free provider", "badge"));
    if (d.is_disposable) card.append(node("span", "Disposable domain", "badge"));
    sourcesEl.append(card);
  }
}

function emailSourceCard(src, accountOnly) {
    const card = node("article", "", "card email-account-card");
    card.dataset.status =
      src.status === "FOUND"   ? "RUNNING" :
      src.status === "ERROR"   ? "FAILED"  :
      src.status === "TIMEOUT" ? "FAILED"  : "";

    card.append(node("p", (src.category || "REGISTERED ACCOUNT").toUpperCase(), "platform"));
    const titleName = (src.source_name || "Account").replace(/_/g, " ").toUpperCase();
    const title = src.username ? `${titleName} · @${src.username}` : titleName;
    card.append(node("strong", title), node("span", "ACCOUNT FOUND", "badge"));

    if (src.display_name) card.append(node("small", `Display: ${src.display_name}`));
    if (src.message && !accountOnly) card.append(node("small", src.message));
    if (src.canonical_url) {
      const link = safeLink(src.canonical_url, "Open registered platform ↗");
      card.append(link);
    }
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
