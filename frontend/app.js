const API_BASE = window.OSINT_API_BASE || (window.location.protocol === "file:" ? "http://127.0.0.1:8765" : "");

const searchForm = document.querySelector("#search-form");
const questionForm = document.querySelector("#question-form");
const questionSection = document.querySelector("#question-section");
const statusNode = document.querySelector("#status");
const errorNode = document.querySelector("#error");
const candidatesNode = document.querySelector("#candidates");
const questionNode = document.querySelector("#question");
const questionOptions = document.querySelector("#question-options");
const reportNode = document.querySelector("#report");

let currentSearchId = null;
let currentQuestionId = null;
let pollingTimer = null;
let busy = false;

searchForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setBusy(true);
  clearResults();
  try {
    const response = await request("/api/searches", {
      method: "POST",
      body: JSON.stringify({
        seed_type: document.querySelector("#seed-type").value,
        value: document.querySelector("#seed").value,
      }),
    });
    currentSearchId = response.id;
    localStorage.setItem("deus-search", currentSearchId);
    await refresh();
  } catch (error) {
    showError(error);
  } finally {
    setBusy(false);
  }
});

async function refresh() {
  if (!currentSearchId) return;
  const requestedId = currentSearchId;
  const [search, candidates, hypotheses, question, report, runs] = await Promise.all([
    request(`/api/searches/${currentSearchId}`),
    request(`/api/searches/${currentSearchId}/candidates`),
    request(`/api/searches/${currentSearchId}/hypotheses`),
    request(`/api/searches/${currentSearchId}/question`),
    request(`/api/searches/${currentSearchId}/report`),
    request(`/api/searches/${currentSearchId}/connector-runs`),
  ]);
  if (requestedId !== currentSearchId) return;

  const running = runs.items.filter(run => run.status === "RUNNING").map(run => run.connector);
  statusNode.textContent = `Status: ${search.status} · ${candidates.items.length} candidates${running.length ? ` · Running ${running.join(", ")}` : ""}`;
  renderCandidates(candidates.items || candidates);
  renderQuestion(question);
  renderReport(report, hypotheses.items || hypotheses);
  clearTimeout(pollingTimer);
  if (!["COMPLETED", "CANCELLED", "FAILED", "AWAITING_USER"].includes(search.status)) {
    pollingTimer = setTimeout(poll, 1500);
  }
}

async function poll() {
  try { await refresh(); }
  catch (error) { showError(error); pollingTimer = setTimeout(poll, 3000); }
}

function renderCandidates(items) {
  candidatesNode.classList.remove("empty");
  candidatesNode.innerHTML = "";
  if (!items.length) {
    candidatesNode.textContent = "No candidates discovered.";
    return;
  }
  for (const item of items) {
    const article = document.createElement("article");
    article.className = `candidate ${String(item.classification || "ambiguous").toLowerCase()}`;
    const title = document.createElement("strong");
    title.textContent = `${item.platform} ${item.username ? `@${item.username}` : item.display_name || "profile"}`;
    const detail = document.createElement("span");
    detail.textContent = item.relevance === "USER_HINT_MATCH" ? "Matches your username clue · ownership unverified" : `${item.classification || "candidate"} identity evidence`;
    article.append(title, detail);
    if (item.reason) {
      const reason = document.createElement("p");
      reason.textContent = item.reason;
      article.append(reason);
    }
    if (item.canonical_url?.startsWith("https://")) {
      const link = document.createElement("a");
      link.href = item.canonical_url;
      link.textContent = "View public source";
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      article.append(link);
    }
    candidatesNode.append(article);
  }
}

function renderQuestion(payload) {
  const item = payload && (payload.item || payload);
  if (!item || !item.id || item.status === "answered") {
    currentQuestionId = null;
    questionSection.hidden = true;
    return;
  }
  currentQuestionId = item.id;
  questionNode.textContent = item.question_text;
  questionOptions.innerHTML = "";
  if (item.question_type === "MULTI_SELECT") {
    for (const option of item.options.filter(o => o.value !== "skip")) {
      const label = document.createElement("label");
      const input = document.createElement("input");
      input.type = "checkbox"; input.name = "choice"; input.value = option.value;
      label.append(input, document.createTextNode(option.label));
      questionOptions.append(label);
    }
    const submit = document.createElement("button");
    submit.type = "submit"; submit.textContent = "Prioritize selected platforms";
    questionOptions.append(submit);
    questionForm.onsubmit = event => {
      event.preventDefault();
      const values = [...questionOptions.querySelectorAll("input:checked")].map(n => n.value);
      if (values.length) answerQuestion(values);
    };
  } else if (item.question_type === "TEXT") {
    const label = document.createElement("label");
    label.textContent = item.context?.input_label || "Your answer";
    const input = document.createElement("input");
    input.name = "answer";
    input.required = true;
    input.maxLength = item.context?.max_length || 64;
    input.placeholder = item.context?.placeholder || "";
    if (item.context?.pattern) input.pattern = item.context.pattern;
    label.append(input);
    const submit = document.createElement("button");
    submit.type = "submit";
    submit.textContent = "Search with this clue";
    questionOptions.append(label, submit);
    questionForm.onsubmit = event => {
      event.preventDefault();
      if (questionForm.reportValidity()) answerQuestion(input.value);
    };
  } else {
    questionForm.onsubmit = event => event.preventDefault();
  }
  for (const option of item.options || []) {
    if (item.question_type === "MULTI_SELECT" && option.value !== "skip") continue;
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = option.label;
    button.addEventListener("click", () => answerQuestion(option.value));
    questionOptions.append(button);
  }
  questionSection.hidden = false;
}

async function answerQuestion(value) {
  if (busy) return;
  setBusy(true);
  try {
    await request(`/api/searches/${currentSearchId}/question-answer`, {
      method: "POST",
      body: JSON.stringify({ question_id: currentQuestionId, value }),
    });
    await refresh();
  } catch (error) {
    showError(error);
  } finally {
    setBusy(false);
  }
}

function renderReport(payload, hypotheses) {
  const report = payload && (payload.report_data || payload.item?.report_data);
  if (!report) {
    reportNode.className = "report empty";
    reportNode.textContent = hypotheses.length
      ? "Investigation is awaiting a useful answer."
      : "The report appears after the investigation completes.";
    return;
  }
  reportNode.className = "report";
  reportNode.innerHTML = "";
  const heading = document.createElement("h3");
  heading.textContent = report.executive_finding;
  reportNode.append(heading);
  addList("Supporting evidence", report.supporting_evidence || []);
  addList("Moderate evidence", report.moderate_evidence || []);
  addList("Contradictions", report.contradictions || []);
  addList("How the answer changed the search", report.answer_impact || []);
  addList("Limitations", report.limitations || []);
  addList("Collection status", (report.connector_runs || []).map(run => `${run.connector}: ${run.status}${run.error ? ` — ${run.error}` : ""}`));
}

function addList(title, values) {
  const heading = document.createElement("strong");
  heading.textContent = title;
  const list = document.createElement("ul");
  for (const value of values) {
    const item = document.createElement("li");
    item.textContent = typeof value === "string" ? value : value.explanation || JSON.stringify(value);
    list.append(item);
  }
  reportNode.append(heading, list);
}

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = response.status === 204 ? null : await response.json();
  if (!response.ok) throw new Error(payload?.detail || `Request failed (${response.status})`);
  return payload;
}

function clearResults() {
  clearTimeout(pollingTimer);
  currentSearchId = null;
  errorNode.textContent = "";
  candidatesNode.textContent = "Searching…";
  questionSection.hidden = true;
  reportNode.textContent = "Investigation running…";
}

function setBusy(value) {
  busy = value;
  searchForm.querySelector("button").disabled = busy;
  questionOptions.querySelectorAll("button,input").forEach(node => { node.disabled = busy; });
  statusNode.textContent = busy ? "Working…" : statusNode.textContent;
}

function showError(error) {
  errorNode.textContent = error instanceof Error ? error.message : String(error);
}

document.querySelector("#stop-search").addEventListener("click", async () => {
  if (!currentSearchId) return;
  try { await request(`/api/searches/${currentSearchId}/stop`, {method: "POST"}); await refresh(); }
  catch (error) { showError(error); }
});
document.querySelector("#continue-search").addEventListener("click", async () => {
  if (!currentSearchId) return;
  try { await request(`/api/searches/${currentSearchId}/continue`, {method: "POST"}); await refresh(); }
  catch (error) { showError(error); }
});
currentSearchId = localStorage.getItem("deus-search");
if (currentSearchId) refresh().catch(showError);
