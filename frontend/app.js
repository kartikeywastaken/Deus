const API_BASE = window.OSINT_API_BASE || (window.location.protocol === "file:" ? "http://127.0.0.1:8000" : "");

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
    await refresh();
  } catch (error) {
    showError(error);
  } finally {
    setBusy(false);
  }
});

async function refresh() {
  if (!currentSearchId) return;
  const [search, candidates, hypotheses, question, report] = await Promise.all([
    request(`/api/searches/${currentSearchId}`),
    request(`/api/searches/${currentSearchId}/candidates`),
    request(`/api/searches/${currentSearchId}/hypotheses`),
    request(`/api/searches/${currentSearchId}/question`),
    request(`/api/searches/${currentSearchId}/report`),
  ]);

  statusNode.textContent = `Status: ${search.status}`;
  renderCandidates(candidates.items || candidates);
  renderQuestion(question);
  renderReport(report, hypotheses.items || hypotheses);
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
    detail.textContent = `${item.classification || "candidate"}${item.score == null ? "" : ` · score ${Number(item.score).toFixed(1)}`}`;
    article.append(title, detail);
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
    questionSection.hidden = true;
    return;
  }
  currentQuestionId = item.id;
  questionNode.textContent = item.question_text;
  questionOptions.innerHTML = "";
  for (const option of item.options || []) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = option.label;
    button.addEventListener("click", () => answerQuestion(option.value));
    questionOptions.append(button);
  }
  questionSection.hidden = false;
}

async function answerQuestion(value) {
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
  errorNode.textContent = "";
  candidatesNode.textContent = "Searching…";
  questionSection.hidden = true;
  reportNode.textContent = "Investigation running…";
}

function setBusy(busy) {
  searchForm.querySelector("button").disabled = busy;
  statusNode.textContent = busy ? "Working…" : statusNode.textContent;
}

function showError(error) {
  errorNode.textContent = error instanceof Error ? error.message : String(error);
}
