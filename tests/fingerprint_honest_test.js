const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('jsdom');
const assert = require('assert');

async function runFingerprintHonestyTests() {
  console.log("Starting fingerprint.js honesty & fallback tests...");

  const htmlPath = path.join(__dirname, '../frontend/index.html');
  const fingerprintJsPath = path.join(__dirname, '../frontend/fingerprint.js');

  const htmlContent = fs.readFileSync(htmlPath, 'utf8');
  const fingerprintJsContent = fs.readFileSync(fingerprintJsPath, 'utf8');

  async function createTestDom(webglVendor, webglRenderer, fontRestricted = false, geoFails = false) {
    const virtualConsole = new VirtualConsole();
    virtualConsole.on("jsdomError", () => {});

    const dom = new JSDOM(htmlContent, {
      url: "http://localhost/",
      runScripts: "dangerously",
      virtualConsole,
      beforeParse(window) {
        window.requestAnimationFrame = (cb) => setTimeout(cb, 16);
        window.cancelAnimationFrame = (id) => clearTimeout(id);
        window.matchMedia = window.matchMedia || function() {
          return { matches: false, addListener: () => {}, removeListener: () => {} };
        };

        const origGetContext = window.HTMLCanvasElement.prototype.getContext;
        window.HTMLCanvasElement.prototype.getContext = function(type, ...args) {
          if (fontRestricted && type === '2d') {
            return null;
          }
          if (type === 'webgl' || type === 'experimental-webgl') {
            if (webglVendor === null) return null;
            return {
              getExtension(ext) {
                if (webglVendor === 'RESTRICTED') return null;
                if (ext === 'WEBGL_debug_renderer_info') {
                  return {
                    UNMASKED_VENDOR_WEBGL: 0x9245,
                    UNMASKED_RENDERER_WEBGL: 0x9246
                  };
                }
                return null;
              },
              getParameter(param) {
                if (param === 0x9245) return webglVendor;
                if (param === 0x9246) return webglRenderer;
                if (param === 0x84E8) return 8192;
                return null;
              },
              getSupportedExtensions() { return ['EXT_texture_filter_anisotropic']; }
            };
          }
          return origGetContext.call(this, type, ...args);
        };

        window.fetch = async (url) => {
          if (geoFails) {
            throw new Error("Network offline / IP API error");
          }
          return {
            ok: true,
            json: async () => ({ city: "Stockholm", region: "AB", country_name: "Sweden", org: "Telia Sweden", ip: "192.0.2.1" })
          };
        };
      }
    });

    const window = dom.window;
    const document = window.document;

    const scriptEl = document.createElement("script");
    scriptEl.textContent = fingerprintJsContent;
    document.body.appendChild(scriptEl);
    document.dispatchEvent(new window.Event("DOMContentLoaded"));

    // Wait for async initTypewriterStream to complete signal population
    await new Promise(r => setTimeout(r, 200));

    return { window, document };
  }

  // --- Test 1: ARM Mali GPU ---
  console.log("\n1. Testing ARM Mali GPU detection...");
  {
    const { document } = await createTestDom("ARM", "Mali-G78");
    const valGpuModel = document.getElementById("val-gpu-model");
    assert(valGpuModel.textContent.includes("ARM Mali GPU"), `Expected 'ARM Mali GPU', got: '${valGpuModel.textContent}'`);
    assert(!valGpuModel.textContent.includes("Intel"), "Should NEVER default to Intel for Mali GPU");
    console.log("✓ ARM Mali GPU correctly detected as 'ARM Mali GPU'");
  }

  // --- Test 2: Qualcomm Adreno GPU ---
  console.log("\n2. Testing Qualcomm Adreno GPU detection...");
  {
    const { document } = await createTestDom("Qualcomm", "Adreno (TM) 650");
    const valGpuModel = document.getElementById("val-gpu-model");
    assert(valGpuModel.textContent.includes("Qualcomm Adreno GPU"), `Expected 'Qualcomm Adreno GPU', got: '${valGpuModel.textContent}'`);
    assert(!valGpuModel.textContent.includes("Intel"), "Should NEVER default to Intel for Adreno GPU");
    console.log("✓ Qualcomm Adreno GPU correctly detected as 'Qualcomm Adreno GPU'");
  }

  // --- Test 3: Restricted / Disabled WebGL ---
  console.log("\n3. Testing Restricted WebGL GPU handling...");
  {
    const { document } = await createTestDom("RESTRICTED", "RESTRICTED");
    const valGpuModel = document.getElementById("val-gpu-model");
    assert(valGpuModel.textContent.includes("GPU vendor undetermined"), `Expected 'GPU vendor undetermined', got: '${valGpuModel.textContent}'`);
    assert(!valGpuModel.textContent.includes("Intel graphics"), "Should NEVER report Intel graphics when WebGL is restricted");
    console.log("✓ Restricted WebGL correctly reports 'GPU vendor undetermined'");
  }

  // --- Test 4: Font Canvas Restriction ---
  console.log("\n4. Testing Font metric canvas restriction handling...");
  {
    const { document } = await createTestDom("Intel", "HD Graphics 630", true);
    const valFonts = document.getElementById("val-fonts-detected");
    assert(valFonts.textContent.includes("Font metric canvas inspection restricted"), `Expected restricted font message, got: '${valFonts.textContent}'`);
    assert(!valFonts.textContent.includes("you write code"), "Should NEVER claim user writes code when font canvas is restricted");
    console.log("✓ Restricted font canvas correctly reports 'Font metric canvas inspection restricted'");
  }

  // --- Test 5: Geo-IP Lookup Failure ---
  console.log("\n5. Testing Geo-IP lookup failure handling...");
  {
    const { document } = await createTestDom("Intel", "HD Graphics 630", false, true);
    const valLocation = document.getElementById("val-location-city");
    const valNetwork = document.getElementById("val-network");
    assert(valLocation.textContent.includes("restricted") || valLocation.textContent.includes("Unavailable"), `Expected offline/unavailable location, got: '${valLocation.textContent}'`);
    assert(!valLocation.textContent.includes("Guntur"), "Should NEVER substitute hardcoded Guntur on failure");
    assert(!valNetwork.textContent.includes("Cloudflare London"), "Should NEVER substitute hardcoded Cloudflare London on failure");
    console.log("✓ Geo-IP failure correctly reports offline/unavailable without fake hardcoded location");
  }

  console.log("\nALL FINGERPRINT HONESTY TESTS PASSED SUCCESSFULLY!");
}

runFingerprintHonestyTests().catch(err => {
  console.error("Test failed:", err);
  process.exit(1);
});
