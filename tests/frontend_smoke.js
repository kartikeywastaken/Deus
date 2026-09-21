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
        if (!window.URL.createObjectURL) {
          window.URL.createObjectURL = () => "blob:http://localhost/fake-blob-uuid";
          window.URL.revokeObjectURL = () => {};
        }
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

  // --- Test Suite: Seed Classification & Endpoint Routing ---
  const seedCases = [
    { input: "user@example.com", expectedEndpoint: "/api/osint/email", expectedSeedType: "EMAIL", expectedValue: "user@example.com" },
    { input: "@octocat", expectedEndpoint: "/api/searches", expectedSeedType: "USERNAME", expectedValue: "octocat" },
    { input: "octocat", expectedEndpoint: "/api/searches", expectedSeedType: "USERNAME", expectedValue: "octocat" }
  ];

  console.log("\nRunning Seed Classification & Endpoint Routing tests...");
  for (const c of seedCases) {
    const dom = createDomEnv();
    const window = dom.window;
    const document = window.document;

    const fetchCalls = [];
    window.fetch = async (url, options = {}) => {
      fetchCalls.push({ url, options });
      if (url === "/api/searches") {
        return { ok: true, status: 200, json: async () => ({ id: "search-smoke-1" }) };
      }
      if (url === "/api/osint/email") {
        return { ok: true, status: 200, text: async () => JSON.stringify({ email: c.input, sites: [], breaches: [] }) };
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

    seedInput.value = c.input;
    seedInput.dispatchEvent(new window.Event("input"));

    const submitEvent = new window.Event("submit", { bubbles: true, cancelable: true });
    form.dispatchEvent(submitEvent);

    await new Promise(r => setTimeout(r, 50));

    const targetCall = fetchCalls.find(fc => fc.url === c.expectedEndpoint);
    assert(targetCall, `Input '${c.input}' should fire request to ${c.expectedEndpoint}`);

    const body = JSON.parse(targetCall.options.body);
    if (c.expectedEndpoint === "/api/searches") {
      assert.strictEqual(body.seed_type, c.expectedSeedType, `Input '${c.input}' expected seed_type ${c.expectedSeedType}, got ${body.seed_type}`);
      assert.strictEqual(body.value, c.expectedValue, `Input '${c.input}' expected value ${c.expectedValue}, got ${body.value}`);
    } else {
      assert.strictEqual(body.email, c.expectedValue, `Input '${c.input}' expected email ${c.expectedValue}, got ${body.email}`);
    }

    console.log(`✓ Seed test passed for: "${c.input}" -> ${c.expectedEndpoint} [${c.expectedSeedType}]`);
  }

  // --- Test Case: HTTP 500 Error display ---
  {
    console.log("\nTesting HTTP 500 Error display & un-hiding error element...");
    const dom = createDomEnv();
    const window = dom.window;
    const document = window.document;

    window.fetch = async () => {
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

    await new Promise(r => setTimeout(r, 50));

    const errEl = document.getElementById("error");
    assert.strictEqual(errEl.hidden, false, "Error element MUST be un-hidden on HTTP 500 error");
    assert(errEl.textContent.includes("Database connection failed"), "Error text should match server detail");
    assert.strictEqual(document.getElementById("search-button").disabled, false, "Button MUST be re-enabled after error");

    console.log("✓ HTTP 500 Error display test passed");
  }

  // --- Test Case: Photo Attachment, Upload & Matching Polling ---
  {
    console.log("\nTesting Photo Attachment, Upload & Photo Matching Polling...");
    const dom = createDomEnv();
    const window = dom.window;
    const document = window.document;

    const fetchCalls = [];
    window.fetch = async (url, options = {}) => {
      fetchCalls.push({ url, options });
      if (url === "/api/searches") {
        return { ok: true, status: 200, json: async () => ({ id: "search-photo-1" }) };
      }
      if (url === "/api/searches/search-photo-1/photo") {
        if (options.method === "DELETE") {
          return { ok: true, status: 200, json: async () => ({ detail: "photo session cleared" }) };
        }
        return { ok: true, status: 200, json: async () => ({ token: "token-smoke-123", width: 800, height: 600 }) };
      }
      if (url.includes("/api/searches/search-photo-1/photo-matches")) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            status: "done",
            total: 2,
            checked: 2,
            pending: 0,
            counts: { same_photo: 1, possible_match: 0, no_match: 1, no_avatar: 0, unavailable: 0, too_small: 0 },
            matches: [
              {
                profile_id: "p1",
                platform: "GitHub",
                username: "octocat",
                profile_url: "https://github.com/octocat",
                avatar_url: "https://github.com/octocat.png",
                verdict: "SAME_PHOTO",
                strength: 0.96,
                method: "crop_match"
              }
            ]
          })
        };
      }
      if (url.includes("/candidates")) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            items: [
              { id: "p1", platform: "GitHub", username: "octocat", canonical_url: "https://github.com/octocat", avatar_url: "https://github.com/octocat.png", identity_score: 0.9 },
              { id: "p2", platform: "Twitter", username: "octocat", canonical_url: "https://twitter.com/octocat", avatar_url: "https://twitter.com/avatar.png", identity_score: 0.8 }
            ]
          })
        };
      }
      return { ok: true, json: async () => ({ status: "COMPLETED", items: [] }) };
    };

    window.EventSource = class { addEventListener() {} close() {} };

    const scriptEl = document.createElement("script");
    scriptEl.textContent = appJsContent;
    document.body.appendChild(scriptEl);
    document.dispatchEvent(new window.Event("DOMContentLoaded"));

    const photoInput = document.getElementById("photo-attach-input");
    const fakeFile = new window.File(["fake photo bytes"], "test.jpg", { type: "image/jpeg" });

    Object.defineProperty(photoInput, "files", {
      value: [fakeFile],
      writable: false,
    });
    photoInput.dispatchEvent(new window.Event("change", { bubbles: true }));

    const previewChip = document.getElementById("photo-chip-preview");
    assert.strictEqual(previewChip.style.display, "inline-flex", "Photo chip preview MUST be visible after selecting photo");

    const seedInput = document.getElementById("seed");
    const form = document.getElementById("search-form");
    seedInput.value = "octocat";

    const submitEvent = new window.Event("submit", { bubbles: true, cancelable: true });
    form.dispatchEvent(submitEvent);

    await new Promise(r => setTimeout(r, 100));

    const photoUploadCall = fetchCalls.find(fc => fc.url === "/api/searches/search-photo-1/photo" && fc.options.method === "POST");
    assert(photoUploadCall, "POST photo to /api/searches/search-photo-1/photo MUST occur after search starts");

    const matchPollCall = fetchCalls.find(fc => fc.url.includes("/photo-matches"));
    assert(matchPollCall, "Polling GET /photo-matches MUST occur");

    const summaryEl = document.getElementById("photo-match-summary");
    assert.strictEqual(summaryEl.style.display, "block", "Photo match summary MUST be displayed");
    assert(summaryEl.textContent.includes("1 same photo"), "Summary text must mention 1 same photo");

    const removeBtn = document.getElementById("photo-chip-remove");
    removeBtn.dispatchEvent(new window.Event("click", { bubbles: true }));

    await new Promise(r => setTimeout(r, 50));

    const deleteCall = fetchCalls.find(fc => fc.url.includes("/photo?token=") && fc.options.method === "DELETE");
    assert(deleteCall, "Removing attached photo MUST fire DELETE /api/searches/:id/photo?token=");

    console.log("✓ Photo Attachment, Upload & Matching test passed");
  }

  console.log("\nALL FRONTEND SMOKE TESTS PASSED SUCCESSFULLY!");
}

runSmokeTests().catch(err => {
  console.error("Smoke test failed:", err);
  process.exit(1);
});
