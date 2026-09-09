/* All displayed profiles, edges and reports come from the API. No demo data. */
const $ = id => document.getElementById(id);
const terminal = s => ["COMPLETED", "FAILED", "CANCELLED"].includes(s);
let searchId = null, stream = null, refreshTimer = null, fallbackTimer = null, busy = false;
let latest = null, questionId = null, refreshRunning = false, refreshAgain = false;
let imageBusy = false, imageController = null, imageGeneration = 0;
const node = (tag, text = "", cls = "") => { const n = document.createElement(tag); n.textContent = text; if (cls) n.className = cls; return n; };
const label = p => `${p.platform} ${p.username ? "@" + p.username : p.display_name || "profile"}`;
const points = v => Math.round(Math.max(0, Math.min(1, v || 0)) * 100);
function safeLink(url, text) { const a = node("a", text); try { if (new URL(url).protocol !== "https:") return node("span", text); } catch { return node("span", text); } a.href = url; a.target = "_blank"; a.rel = "noopener noreferrer"; return a; }
async function request(path, options = {}) {
  const response = await fetch(path, {headers:{"Content-Type":"application/json"}, ...options});
  const payload = await response.json();
  if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : JSON.stringify(payload.detail || response.status));
  return payload;
}
function error(e) { $("error").textContent = e.message || String(e); }
function setBusy(value) { busy = value; $("search-button").disabled = value; $("question-form").querySelectorAll("input,button").forEach(n => n.disabled = value); }
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
    $("candidate-count").textContent = candidates.items.length; $("hypothesis-count").textContent = hypotheses.items.length; $("evidence-count").textContent = evidence.items.length; $("run-count").textContent = runs.items.length;
    $("stop-search").disabled = terminal(state.status); $("continue-search").disabled = state.status !== "AWAITING_USER";
    if (terminal(state.status)) { stream?.close(); clearTimeout(fallbackTimer); $("connection").textContent = "Saved investigation"; }
    if (state.error_summary) error(new Error(state.error_summary));
    renderCandidates(); renderRuns(); renderHypotheses(); renderQuestion(); renderEvidence(); renderReport(); renderGraph();
    $("check-image").disabled = imageBusy || !$("reference-image").files.length;
    $("image-prompt").textContent = terminal(state.status) ? "Search finished. Optionally select an image to check reuse across the collected avatars, or try another image." : "Choose an optional image; it will be checked when this search completes. You can also check the current candidates now.";
    if (state.status === "COMPLETED" && $("reference-image").files.length && !imageBusy) checkImage();
  } finally { refreshRunning = false; if (refreshAgain) { refreshAgain = false; schedule(); } }
}
function renderCandidates() {
  $("candidates").replaceChildren();
  const sections = [
    ["PUBLICLY_LINKED", "Publicly linked accounts — association, not verified ownership"],
    ["HAS_PUBLIC_CONTEXT", "Candidates with public context"],
    ["POSSIBLE_MATCH_NO_CONTEXT", "Possible matches but nothing to analyze"]
  ];
  for (const [kind, heading] of sections) {
  const items = latest.candidates.filter(p => (p.analysis_status || "POSSIBLE_MATCH_NO_CONTEXT") === kind);
  if (items.length) $("candidates").append(node("h3", heading));
  for (const p of items) {
    const card = node("article", "", "card"), top = node("div", "", "card-top"), title = node("div");
    title.append(node("p", p.platform, "platform"), node("strong", p.username ? "@" + p.username : p.display_name || "Public profile"));
    top.append(title, node("span", `${points(p.score)}/100 relevance`, "score"));
    card.append(top, node("p", p.reason || "Unconfirmed candidate"));
    card.append(node("p", `Identity evidence: ${points(p.identity_score)}/100 · ${p.classification || "unassessed"}${p.seed_match_bonus ? " · +15 exact-seed relevance" : ""}`));
    if (p.relevance === "USER_HINT_MATCH") card.append(node("p", "Matches your username clue · ownership unverified", "badge"));
    for (const edge of p.linked_accounts || []) card.append(node("p", `Public link: ${edge.source_url} → ${edge.target_url}`));
    card.append(safeLink(p.canonical_url, "Open public source ↗")); $("candidates").append(card);
  }
  }
  if (!latest.candidates.length) $("candidates").append(node("p", "No candidates collected yet. Failed checks do not prove absence.", "empty"));
}
function renderRuns() {
  $("runs").className = ""; $("runs").replaceChildren();
  latest.runs.forEach(r => { const n = node("div", "", "run"); n.dataset.status = r.status; n.append(node("strong", r.connector), node("span", r.status, "badge")); if (r.error) n.append(node("small", r.error));
    if (r.site_checks?.length) { const detail = node("details"), list = node("ul"); detail.append(node("summary", "Per-site check results")); r.site_checks.forEach(s => list.append(node("li", `${s.site}: ${s.status}${s.http_status ? " · HTTP " + s.http_status : ""}`))); detail.append(list); n.append(detail); }
    if (r.unsupported_sites?.length) n.append(node("small", "Not in this tool’s installed database: " + r.unsupported_sites.join(", ")));
    $("runs").append(n); });
}
function renderHypotheses() {
  $("hypotheses").replaceChildren(); const byId = new Map(latest.candidates.map(p => [p.id, p]));
  latest.hypotheses.forEach(h => { const card = node("div", "", "cluster"); card.append(node("strong", `Cluster ${h.rank} · ${h.classification}`)); const bar = node("div", "", "bar"), fill = node("span"); fill.style.width = points(h.overall_score) + "%"; bar.append(fill); card.append(bar, node("p", `${points(h.overall_score)}/100 identity evidence`)); const list = node("ul"); h.memberships.forEach(m => list.append(node("li", byId.has(m.profile_id) ? label(byId.get(m.profile_id)) : m.profile_id))); card.append(list); $("hypotheses").append(card); });
}
function renderQuestion() {
  const q = latest.question; $("question-section").hidden = !q;
  if (!q) { questionId = null; return; }
  if (questionId === q.id) return; questionId = q.id;
  $("question").textContent = q.question_text; $("question-reason").textContent = q.reason; const choices = $("question-options"); choices.replaceChildren();
  $("question-form").onsubmit = e => e.preventDefault();
  if (q.question_type === "TEXT") {
    const input = node("input"); input.type = "text"; input.required = true; input.name = "answer"; input.setAttribute("aria-label", q.context.input_label || "Your answer"); input.placeholder = q.context.placeholder || "Your clue"; input.maxLength = q.context.max_length || 64; if (q.context.pattern) input.pattern = q.context.pattern;
    const button = node("button", "Search with this clue"); button.type = "submit"; choices.append(input, button); $("question-form").onsubmit = e => { e.preventDefault(); if ($("question-form").reportValidity()) answer(input.value); };
  } else if (q.question_type === "MULTI_SELECT") {
    q.options.filter(o => o.value !== "skip").forEach(o => { const l = node("label"), i = node("input"); i.type = "checkbox"; i.value = o.value; l.append(i, document.createTextNode(o.label)); choices.append(l); });
    const b = node("button", "Prioritize these"); b.type = "submit"; choices.append(b); $("question-form").onsubmit = e => { e.preventDefault(); const values = [...choices.querySelectorAll("input:checked")].map(i => i.value); if (values.length) answer(values); };
  }
  q.options.filter(o => q.question_type !== "MULTI_SELECT" || o.value === "skip").forEach(o => { const b = node("button", o.label, "secondary"); b.type = "button"; b.onclick = () => answer(o.value); choices.append(b); });
}
async function answer(value) { if (busy) return; setBusy(true); try { await request(`/api/searches/${searchId}/question-answer`, {method:"POST", body:JSON.stringify({question_id:questionId, value})}); await refresh(); } catch(e) { error(e); } finally { setBusy(false); } }
function renderEvidence() {
  $("evidence").replaceChildren(); $("evidence").className = ""; const byId = new Map(latest.candidates.map(p => [p.id, p]));
  latest.evidence.forEach(e => { const card = node("article", "", "signal " + e.direction.toLowerCase()); card.append(node("strong", e.signal_type.replaceAll("_", " ")), node("p", e.explanation)); const pair = [e.left_profile_id, e.right_profile_id].map(id => byId.has(id) ? label(byId.get(id)) : id).join(" ↔ "); card.append(node("p", pair)); const meta = node("div", "", "signal-meta"); [`Direction: ${e.direction}`, `Signal: ${points(e.normalized_score)}/100`, `Reliability: ${points(e.reliability)}/100`, `Contribution: ${e.model_contribution == null ? "not retained" : Number(e.model_contribution).toFixed(3)}`, `Family: ${e.evidence_family}`].forEach(t => meta.append(node("span", t))); card.append(meta); $("evidence").append(card); });
  if (!latest.evidence.length) $("evidence").append(node("p", "No pairwise evidence yet. A singleton can still be a relevant search result.", "empty"));
}
function renderReport() {
  const r = latest.report; if (!r) { $("report").textContent = "The report appears when the search finishes. You can skip a question to continue."; return; }
  $("report").replaceChildren(node("h2", r.executive_finding));
  const section = (title, values) => { if (!values?.length) return; $("report").append(node("h3", title)); const ul = node("ul"); values.forEach(v => { const li = node("li", typeof v === "string" ? v : v.explanation || v.note || ""); for (const url of v.source_urls || []) li.append(document.createTextNode(" "), safeLink(url, "Source ↗")); ul.append(li); }); $("report").append(ul); };
  section("Leading search results", (r.lead_candidates || []).slice(0, 10).map(p => `${label(p)} — ${p.reason}`));
  section("Public-page / repository references — ownership unverified", (r.repository_references || []).map(p => `${p.url} · found in ${p.source_url}`));
  section("Supporting evidence", r.supporting_evidence); section("Moderate evidence", r.moderate_evidence); section("Contradictions", r.contradictions); section("How your answers changed the search", r.answer_impact); section("Limitations", r.limitations);
  section("Collection outcomes", (r.connector_runs || []).map(c => `${c.connector}: ${c.status}${c.error ? " — " + c.error : ""}`));
  section("Defensive self-audit · separate from identity", (r.self_audit_findings || []).map(f => `${f.connector}: ${f.status}. Reported breach names: ${f.breach_names.join(", ") || "none returned"}. ${f.note}`));
  section("Source provenance", (r.source_provenance || []).map(p => ({explanation:p.connector, source_urls:p.source_url ? [p.source_url] : []})));
}
function renderGraph(selected = null) {
  if (!latest) return; const svg = $("graph"), ns = "http://www.w3.org/2000/svg"; svg.replaceChildren();
  const make = (tag, attrs) => { const n = document.createElementNS(ns, tag); Object.entries(attrs).forEach(([k,v]) => n.setAttribute(k, v)); return n; };
  const nodes = latest.graph.nodes.filter(n => n.type !== "hypothesis" || latest.graph.edges.filter(e => e.source === n.id && e.type === "HAS_CANDIDATE").length > 1).slice(0,100), positions = new Map();
  const orbit = nodes.filter(n => n.type !== "search");
  nodes.filter(n => n.type === "search").forEach(n => positions.set(n.id,[550,365]));
  orbit.forEach((n,i) => { const angle = 2*Math.PI*i/Math.max(1,orbit.length); const ring = i%2 ? 280 : 205; positions.set(n.id, [520+ring*Math.cos(angle), 365+ring*Math.sin(angle)]); });
  latest.graph.edges.forEach(e => { const a = positions.get(e.source), b = positions.get(e.target); if (!a || !b) return; const related = !selected || e.source === selected || e.target === selected; const weight = points(Math.abs(e.score || 0))/100; svg.append(make("line", {x1:a[0], y1:a[1], x2:b[0], y2:b[1], stroke:e.type.includes("CONTRADICT") || e.score < 0 ? "#ac554e" : "#167661", "stroke-width":1+3*weight, opacity:related ? .2+.6*weight : .04})); });
  nodes.forEach(n => { const [x,y] = positions.get(n.id); const g = make("g", {tabindex:0, role:"button", "aria-label":n.label}); g.append(make("circle", {cx:x,cy:y,r:n.type === "profile" ? 8 : 11,fill:n.id === selected ? "#ddab47" : n.type === "profile" ? "#167661" : "#8b9b90"})); const t = make("text", {x:x+13,y:y+4}); t.textContent = n.label.length > 27 ? n.label.slice(0,24)+"…" : n.label; g.append(t); const choose = () => { renderGraph(n.id); $("graph-detail").textContent = `${n.label} · ${n.type} · ${latest.graph.edges.filter(e => e.source === n.id || e.target === n.id).length} stored connections`; }; g.onclick = choose; g.onkeydown = e => { if (["Enter"," "].includes(e.key)) {e.preventDefault(); choose();} }; svg.append(g); });
  if (!selected) $("graph-detail").textContent = nodes.length ? `${nodes.length} of ${latest.graph.nodes.length} nodes shown. Layout does not imply identity.` : "No graph data yet.";
}
$("search-form").onsubmit = async e => { e.preventDefault(); if (busy || imageBusy) return; setBusy(true); $("error").textContent = ""; try { const result = await request("/api/searches", {method:"POST",body:JSON.stringify({seed_type:$("seed-type").value,value:$("seed").value,scope:"self_audit",email_self_audit_confirmed:$("seed-type").value === "EMAIL" && $("email-consent").checked})}); stream?.close(); searchId = result.id; questionId = null; $("image-results").replaceChildren(); $("image-status").textContent = ""; localStorage.setItem("deus-search",searchId); history.replaceState(null,"",`?search=${searchId}`); connect(); await refresh(); } catch(err) {error(err);} finally {setBusy(false);} };
$("seed-type").onchange = () => { $("consent-label").hidden = $("seed-type").value !== "EMAIL"; $("email-consent").required = $("seed-type").value === "EMAIL"; };
for (const [id, action] of [["continue-search","continue"],["stop-search","stop"]]) $(id).onclick = async () => { if (!searchId || busy) return; try { await request(`/api/searches/${searchId}/${action}`,{method:"POST"}); await refresh(); } catch(e) {error(e);} };
document.querySelectorAll("[data-view]").forEach(b => b.onclick = () => { document.querySelectorAll(".view").forEach(v => v.hidden = v.id !== `view-${b.dataset.view}`); document.querySelectorAll("[data-view]").forEach(t => t.setAttribute("aria-pressed",String(t === b))); });
$("graph-reset").onclick = () => renderGraph(); $("print-report").onclick = () => window.print();
const saved = new URLSearchParams(location.search).get("search") || localStorage.getItem("deus-search");
if (saved && /^[0-9a-f-]{36}$/i.test(saved)) { searchId = saved; refresh().then(connect).catch(error); }

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
