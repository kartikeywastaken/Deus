const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('jsdom');
const assert = require('assert');

async function runSmokeTests() {
  console.log("Starting frontend smoke tests...");

  const htmlPath = path.join(__dirname, '../frontend/index.html');
  const appJsPath = path.join(__dirname, '../frontend/app.js');

  const htmlContent = fs.readFileSync(htmlPath, 'utf8');
  const appJsContent = fs.readFileSync(appJsPath, 'utf8');

  function createDomEnv() {
    const virtualConsole = new VirtualConsole();
    virtualConsole.on("jsdomError", (err) => {
      // Ignore external script/css loading errors in node jsdom test
      if (err.type === "resource-loading" || err.message.includes("requestSubmit") || err.message.includes("requestAnimationFrame")) return;
      console.error(err);
    });

    const dom = new JSDOM(htmlContent, {
      url: "http://localhost/",
      runScripts: "dangerously",
      virtualConsole,
      beforeParse(window) {
        window.requestAnimationFrame = (cb) => setTimeout(cb, 16);
        window.cancelAnimationFrame = (id) => clearTimeout(id);
        window.Element.prototype.scrollIntoView = function() {};
        window.HTMLFormElement.prototype.requestSubmit = function() {
          const event = new window.Event("submit", { bubbles: true, cancelable: true });
          this.dispatchEvent(event);
        };
      }
    });

    const window = dom.window;
    window.requestAnimationFrame = (cb) => setTimeout(cb, 16);
    window.cancelAnimationFrame = (id) => clearTimeout(id);
    window.matchMedia = window.matchMedia || function() {
      return { matches: false, addListener: () => {}, removeListener: () => {} };
    };

    return dom;
  }

  // --- Test Case 1: USERNAME Search ---
  {
    console.log("Test 1: USERNAME Search & SSE EventSource triggering...");
    const dom = createDomEnv();
    const window = dom.window;
    const document = window.document;

    const fetchCalls = [];
    window.fetch = async (url, options = {}) => {
      fetchCalls.push({ url, options });
      if (url === "/api/searches") {
        return {
          ok: true,
          status: 200,
          json: async () => ({ id: "search-123" })
        };
      }
      if (url.startsWith("/api/searches/search-123")) {
        if (url.endsWith("/candidates")) {
          return { ok: true, json: async () => ({ items: [{ platform: "github", username: "rubberpirate", score: 0.9 }] }) };
        }
        if (url.endsWith("/report")) {
          return { ok: true, json: async () => ({ report_data: { executive_finding: "Test finding" } }) };
        }
        return { ok: true, json: async () => ({ status: "COMPLETED", items: [] }) };
      }
      return { ok: true, json: async () => ({}) };
    };

    class MockEventSource {
      constructor(url) {
        this.url = url;
        setTimeout(() => { if (this.onopen) this.onopen(); }, 10);
      }
      addEventListener(evt, cb) {}
      close() {}
    }
    window.EventSource = MockEventSource;

    const scriptEl = document.createElement("script");
    scriptEl.textContent = appJsContent;
    document.body.appendChild(scriptEl);
    document.dispatchEvent(new window.Event("DOMContentLoaded"));

    const seedInput = document.getElementById("seed");
    const seedTypeSelect = document.getElementById("seed-type");
    const form = document.getElementById("search-form");

    seedInput.value = "rubberpirate";
    seedTypeSelect.value = "USERNAME";

    const submitEvent = new window.Event("submit", { bubbles: true, cancelable: true });
    form.dispatchEvent(submitEvent);

    await new Promise(r => setTimeout(r, 100));

    const postSearchCall = fetchCalls.find(c => c.url === "/api/searches");
    assert(postSearchCall, "POST /api/searches should have fired");
    const body = JSON.parse(postSearchCall.options.body);
    assert.strictEqual(body.seed_type, "USERNAME");
    assert.strictEqual(body.value, "rubberpirate");
    assert.strictEqual(body.self_audit_confirmed, true);

    assert.strictEqual(document.getElementById("metrics-section").hidden, false, "metrics-section should be visible");
    assert.strictEqual(document.getElementById("view-overview").hidden, false, "view-overview should be visible");
    assert.strictEqual(document.getElementById("search-button").disabled, false, "search-button should be re-enabled");

    console.log("✓ Test 1 Passed (USERNAME search)");
  }

  // --- Test Case 2: PROFILE_URL Search ---
  {
    console.log("Test 2: PROFILE_URL Search...");
    const dom = createDomEnv();
    const window = dom.window;
    const document = window.document;

    const fetchCalls = [];
    window.fetch = async (url, options = {}) => {
      fetchCalls.push({ url, options });
      if (url === "/api/searches") {
        return { ok: true, status: 200, json: async () => ({ id: "search-456" }) };
      }
      return { ok: true, json: async () => ({ status: "COMPLETED", items: [] }) };
    };
    window.EventSource = class { addEventListener() {} close() {} };

    const scriptEl = document.createElement("script");
    scriptEl.textContent = appJsContent;
    document.body.appendChild(scriptEl);
    document.dispatchEvent(new window.Event("DOMContentLoaded"));

    const seedInput = document.getElementById("seed");
    const form = document.getElementById("search-form");

    seedInput.value = "https://github.com/octocat";
    seedInput.dispatchEvent(new window.Event("input"));

    const submitEvent = new window.Event("submit", { bubbles: true, cancelable: true });
    form.dispatchEvent(submitEvent);

    await new Promise(r => setTimeout(r, 100));

    const postSearchCall = fetchCalls.find(c => c.url === "/api/searches");
    assert(postSearchCall, "POST /api/searches should fire for PROFILE_URL");
    const body = JSON.parse(postSearchCall.options.body);
    assert.strictEqual(body.seed_type, "PROFILE_URL");
    assert.strictEqual(body.value, "https://github.com/octocat");

    assert.strictEqual(document.getElementById("search-button").disabled, false);
    console.log("✓ Test 2 Passed (PROFILE_URL search flow)");
  }

  // --- Test Case 3: EMAIL Search ---
  {
    console.log("Test 3: EMAIL Search...");
    const dom = createDomEnv();
    const window = dom.window;
    const document = window.document;

    const fetchCalls = [];
    window.fetch = async (url, options = {}) => {
      fetchCalls.push({ url, options });
      if (url === "/api/osint/email") {
        return {
          ok: true,
          status: 200,
          text: async () => JSON.stringify({
            email: "test@example.com",
            provider: "Google",
            summary: { registered: 1, not_registered: 0, cant_check: 0, scan_ms: 120 },
            sites: [{ id: "github", label: "GitHub", status: "REGISTERED", username: "test" }]
          })
        };
      }
      return { ok: true, json: async () => ({}) };
    };

    const scriptEl = document.createElement("script");
    scriptEl.textContent = appJsContent;
    document.body.appendChild(scriptEl);
    document.dispatchEvent(new window.Event("DOMContentLoaded"));

    const seedInput = document.getElementById("seed");
    const form = document.getElementById("search-form");

    seedInput.value = "test@example.com";
    seedInput.dispatchEvent(new window.Event("input"));

    const submitEvent = new window.Event("submit", { bubbles: true, cancelable: true });
    form.dispatchEvent(submitEvent);

    await new Promise(r => setTimeout(r, 100));

    const emailCall = fetchCalls.find(c => c.url === "/api/osint/email");
    assert(emailCall, "POST /api/osint/email should fire");
    const body = JSON.parse(emailCall.options.body);
    assert.strictEqual(body.email, "test@example.com");
    assert.strictEqual(body.self_audit_confirmed, true);

    const emailSection = document.getElementById("email-osint-section");
    assert.strictEqual(emailSection.hidden, false, "email-osint-section should be visible");
    assert.strictEqual(document.getElementById("search-button").disabled, false, "search-button should be re-enabled after email scan");

    console.log("✓ Test 3 Passed (EMAIL search flow)");
  }

  // --- Test Case 4: HTTP 500 Error display ---
  {
    console.log("Test 4: HTTP 500 Error display & un-hiding error element...");
    const dom = createDomEnv();
    const window = dom.window;
    const document = window.document;

    window.fetch = async (url) => {
      return {
        ok: false,
        status: 500,
        statusText: "Internal Server Error",
        json: async () => ({ detail: "Database connection failed" })
      };
    };

    const scriptEl = document.createElement("script");
    scriptEl.textContent = appJsContent;
    document.body.appendChild(scriptEl);
    document.dispatchEvent(new window.Event("DOMContentLoaded"));

    const seedInput = document.getElementById("seed");
    const form = document.getElementById("search-form");

    seedInput.value = "erroruser";
    document.getElementById("seed-type").value = "USERNAME";

    const submitEvent = new window.Event("submit", { bubbles: true, cancelable: true });
    form.dispatchEvent(submitEvent);

    await new Promise(r => setTimeout(r, 100));

    const errEl = document.getElementById("error");
    assert.strictEqual(errEl.hidden, false, "Error element MUST be un-hidden on HTTP 500 error");
    assert(errEl.textContent.includes("Database connection failed"), "Error text should match server detail");
    assert.strictEqual(document.getElementById("search-button").disabled, false, "Button MUST be re-enabled after error");

    console.log("✓ Test 4 Passed (HTTP 500 error display & un-hiding)");
  }

  console.log("\nALL FRONTEND SMOKE TESTS PASSED SUCCESSFULLY!");
}

runSmokeTests().catch(err => {
  console.error("Smoke test failed:", err);
  process.exit(1);
});
