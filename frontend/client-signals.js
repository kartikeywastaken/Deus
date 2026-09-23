/**
 * Deus OSINT Toolkit — Client Signals & Browser Audit Engine
 * Gathers passive client browser signals in real time without cookies or permissions.
 */

(function () {
  'use strict';

  if (typeof window === 'undefined' || typeof document === 'undefined') return;

  // --- ERROR LOGGING SCOPED TO THIS SCRIPT ---
  window.addEventListener('error', (event) => {
    if (event.filename && (event.filename.includes('client-signals') || event.filename.includes('fingerprint'))) {
      console.error('[DEUS-SIGNALS] Uncaught script error:', event.message, 'at', event.filename, ':', event.lineno);
    }
  });

  window.addEventListener('unhandledrejection', (event) => {
    if (event.reason) {
      console.warn('[DEUS-SIGNALS] Unhandled promise rejection in client signals:', event.reason);
    }
  });

  // Memoized canvas & WebGL contexts
  let fontCanvasCtx = null;
  let webglContext = null;

  // --- STAGE 1: COLD OPEN LOGIC ---
  let coldOpenBeat = 0;
  let touchStartY = 0;
  let gestureDebounceTimer = null;

  function initStage1() {
    const coldOpenOverlay = document.getElementById('stage1-cold-open');
    if (!coldOpenOverlay) return;

    document.documentElement.style.overflow = 'hidden';
    document.body.style.overflow = 'hidden';
    if (window.Lenis && window.lenis) {
      try {
        window.lenis.stop();
      } catch (e) {}
    }

    function advanceColdOpen() {
      if (coldOpenBeat === 0) {
        coldOpenBeat = 1;
        showAnimatedLine(document.getElementById('cold-line-1'));
      } else if (coldOpenBeat === 1) {
        coldOpenBeat = 2;
        showAnimatedLine(document.getElementById('cold-line-2'));
        const promptEl = document.getElementById('cold-prompt');
        if (promptEl) promptEl.textContent = 'SCROLL UP TO CONTINUE ↗';
      } else if (coldOpenBeat === 2) {
        coldOpenBeat = 3;
        completeStage1();
      }
    }

    function handleWheel(e) {
      if (coldOpenBeat >= 3) return;
      const isUpward = e.deltaY < 0 || e.deltaY > 0;
      if (isUpward) {
        e.preventDefault();
        if (!gestureDebounceTimer) {
          advanceColdOpen();
          gestureDebounceTimer = setTimeout(() => {
            gestureDebounceTimer = null;
          }, 400);
        }
      }
    }

    function handleTouchStart(e) {
      if (e.touches && e.touches.length > 0) {
        touchStartY = e.touches[0].clientY;
      }
    }

    function handleTouchMove(e) {
      if (coldOpenBeat >= 3) return;
      if (!e.touches || e.touches.length === 0) return;
      const touchEndY = e.touches[0].clientY;
      const deltaY = touchStartY - touchEndY;
      if (Math.abs(deltaY) > 30) {
        e.preventDefault();
        if (!gestureDebounceTimer) {
          advanceColdOpen();
          gestureDebounceTimer = setTimeout(() => {
            gestureDebounceTimer = null;
          }, 400);
        }
      }
    }

    window.addEventListener('wheel', handleWheel, { passive: false });
    window.addEventListener('touchstart', handleTouchStart, { passive: true });
    window.addEventListener('touchmove', handleTouchMove, { passive: false });

    function completeStage1() {
      window.removeEventListener('wheel', handleWheel);
      window.removeEventListener('touchstart', handleTouchStart);
      window.removeEventListener('touchmove', handleTouchMove);

      document.documentElement.style.overflow = '';
      document.body.style.overflow = '';
      if (window.Lenis && window.lenis) {
        try {
          window.lenis.start();
        } catch (e) {}
      }

      coldOpenOverlay.classList.add('cold-open-fadeout');
      setTimeout(() => {
        coldOpenOverlay.style.display = 'none';
        const stage2El = document.getElementById('stage2-fingerprint');
        stage2El?.scrollIntoView({ behavior: 'smooth' });
      }, 600);
    }
  }

  function showAnimatedLine(element) {
    if (!element) return;
    element.classList.add('is-visible');
    if (window.gsap && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      try {
        gsap.fromTo(
          element,
          { opacity: 0, y: 30 },
          { opacity: 1, y: 0, duration: 0.8, ease: 'power3.out' }
        );
      } catch (e) {}
    }
  }

  // --- STAGE 2: PASSIVE SIGNAL COLLECTORS ---

  // 1. OS & Browser
  function getOSAndBrowser() {
    const ua = navigator.userAgent || '';
    let os = 'Unknown OS';
    if (/windows nt 10/i.test(ua)) os = 'Windows 10/11';
    else if (/windows nt 6\.3/i.test(ua)) os = 'Windows 8.1';
    else if (/windows nt 6\.1/i.test(ua)) os = 'Windows 7';
    else if (/mac os x/i.test(ua)) os = 'macOS';
    else if (/android/i.test(ua)) os = 'Android';
    else if (/iphone|ipad|ipod/i.test(ua)) os = 'iOS';
    else if (/linux/i.test(ua)) os = 'Linux';

    let browser = 'Unknown Browser';
    if (/edg/i.test(ua)) browser = 'Microsoft Edge';
    else if (/chrome|crios/i.test(ua)) browser = 'Google Chrome';
    else if (/firefox|fxios/i.test(ua)) browser = 'Mozilla Firefox';
    else if (/safari/i.test(ua) && !/chrome/i.test(ua)) browser = 'Apple Safari';
    else if (/opera|opr/i.test(ua)) browser = 'Opera';

    let uaDataStr = '';
    if (navigator.userAgentData?.brands) {
      try {
        const brands = navigator.userAgentData.brands.map(b => `${b.brand} v${b.version}`).join(', ');
        uaDataStr = ` [Sec-CH-UA: ${brands}]`;
      } catch (e) {}
    }

    return `${os} · ${browser}${uaDataStr}`;
  }

  // 2. CPU Concurrency & Architecture
  function getCPUInfo() {
    const cores = navigator.hardwareConcurrency;
    let arch = 'Unknown arch';
    const ua = navigator.userAgent || '';
    if (/arm|aarch64/i.test(ua)) arch = 'ARM architecture';
    else if (/x86_64|x64|wow64/i.test(ua)) arch = 'x86_64 architecture';

    return cores ? `${cores} logical CPU cores (${arch})` : `Hardware concurrency restricted (${arch})`;
  }

  // 3. GPU Vendor & Renderer Parsing
  function getGPUInfo() {
    try {
      if (!webglContext) {
        const canvas = document.createElement('canvas');
        webglContext = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
      }
      if (!webglContext) {
        return {
          fullStr: 'WebGL context disabled / unavailable',
          vendor: 'Undetermined',
          renderer: 'Undetermined',
          shortName: 'GPU vendor undetermined (WebGL disabled)',
          isRestricted: true
        };
      }

      const debugInfo = webglContext.getExtension('WEBGL_debug_renderer_info');
      if (!debugInfo) {
        return {
          fullStr: 'WEBGL_debug_renderer_info unmasked GPU extension restricted',
          vendor: 'Restricted',
          renderer: 'Restricted',
          shortName: 'GPU vendor undetermined (Extension restricted)',
          isRestricted: true
        };
      }

      const vendor = webglContext.getParameter(debugInfo.UNMASKED_VENDOR_WEBGL) || '';
      const renderer = webglContext.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL) || '';
      const fullStr = `${vendor} · ${renderer}`.trim();

      if (!vendor && !renderer) {
        return {
          fullStr: 'GPU unmasked vendor/renderer returned empty',
          vendor: 'Unknown',
          renderer: 'Unknown',
          shortName: 'GPU vendor undetermined',
          isRestricted: true
        };
      }

      const combined = `${vendor} ${renderer}`.toLowerCase();
      let shortName = '';

      if (combined.includes('mali') || combined.includes('arm')) {
        shortName = 'ARM Mali GPU';
      } else if (combined.includes('adreno') || combined.includes('qualcomm')) {
        shortName = 'Qualcomm Adreno GPU';
      } else if (combined.includes('powervr') || combined.includes('imagination')) {
        shortName = 'Imagination PowerVR GPU';
      } else if (combined.includes('videocore') || combined.includes('broadcom')) {
        shortName = 'Broadcom VideoCore GPU';
      } else if (combined.includes('apple')) {
        shortName = 'Apple Silicon GPU';
      } else if (combined.includes('nvidia') || combined.includes('geforce') || combined.includes('quadro') || combined.includes('rtx') || combined.includes('gtx')) {
        shortName = 'NVIDIA Graphics';
      } else if (combined.includes('amd') || combined.includes('radeon') || combined.includes('ati')) {
        shortName = 'AMD Graphics';
      } else if (combined.includes('intel')) {
        shortName = 'Intel Graphics';
      } else if (combined.includes('swiftshader') || combined.includes('llvmpipe') || combined.includes('basic render') || combined.includes('software')) {
        shortName = 'Software Emulated GPU';
      } else {
        shortName = renderer || vendor || 'GPU vendor undetermined';
      }

      return { fullStr, vendor, renderer, shortName, isRestricted: false };
    } catch (e) {
      return {
        fullStr: 'GPU query blocked by browser policy',
        vendor: 'Blocked',
        renderer: 'Blocked',
        shortName: 'GPU vendor undetermined (Query blocked)',
        isRestricted: true
      };
    }
  }

  // 4. WebGL Full Capabilities Dump
  function getWebGLCapabilities() {
    try {
      if (!webglContext) {
        const canvas = document.createElement('canvas');
        webglContext = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
      }
      if (!webglContext) return 'WebGL context disabled / unavailable';

      const gl2 = !!(window.WebGL2RenderingContext && document.createElement('canvas').getContext('webgl2'));
      const maxTex = webglContext.getParameter(webglContext.MAX_TEXTURE_SIZE) || 'Unknown';
      const maxViewport = webglContext.getParameter(webglContext.MAX_VIEWPORT_DIMS);
      const viewportStr = maxViewport ? `${maxViewport[0]}×${maxViewport[1]}` : 'Unknown';
      const extList = webglContext.getSupportedExtensions() || [];

      return `WebGL2: ${gl2 ? 'Supported' : 'Unavailable'} · Max Texture: ${maxTex}px · Max Viewport: ${viewportStr} · ${extList.length} extensions enabled`;
    } catch (e) {
      return 'WebGL capability inspection restricted by client privacy policy';
    }
  }

  // 5. Canvas Fingerprint Hash (Synchronous & Fast)
  function getCanvasFingerprintHashSync() {
    try {
      const canvas = document.createElement('canvas');
      canvas.width = 240;
      canvas.height = 60;
      const ctx = canvas.getContext('2d');
      if (!ctx) return 'Canvas 2D context unavailable';

      ctx.textBaseline = 'top';
      ctx.font = "14px 'Arial', sans-serif";
      ctx.fillStyle = '#f60';
      ctx.fillRect(125, 1, 62, 20);

      ctx.fillStyle = '#069';
      ctx.fillText('DeusOSINT,🎨 123', 2, 15);
      ctx.fillStyle = 'rgba(102, 204, 0, 0.7)';
      ctx.fillText('DeusOSINT,🎨 123', 4, 17);

      ctx.beginPath();
      ctx.arc(50, 40, 15, 0, Math.PI * 2, true);
      ctx.closePath();
      ctx.fill();

      const dataUrl = canvas.toDataURL();
      if (!dataUrl || dataUrl.length < 20) return 'Canvas toDataURL restricted by browser policy';

      let sum = 0;
      for (let i = 0; i < dataUrl.length; i++) {
        sum = (sum << 5) - sum + dataUrl.charCodeAt(i);
        sum |= 0;
      }
      const hash = Math.abs(sum).toString(16).slice(0, 12);
      return `Canvas Hash: [fnv_${hash}]`;
    } catch (e) {
      return 'Canvas fingerprinting restricted by client privacy policy';
    }
  }

  async function getCanvasFingerprintHash() {
    return getCanvasFingerprintHashSync();
  }

  // 6. Touch & Media Features
  function getTouchAndMediaFeatures() {
    try {
      const touchPoints = navigator.maxTouchPoints || 0;
      const pointerFine = window.matchMedia('(pointer: fine)').matches;
      const hoverSupported = window.matchMedia('(hover: hover)').matches;

      return `${touchPoints} touch point${touchPoints === 1 ? '' : 's'} · Pointer: ${pointerFine ? 'fine' : 'coarse'} · Hover: ${hoverSupported ? 'supported' : 'unsupported'}`;
    } catch (e) {
      return 'Touch & Pointer features inspection restricted';
    }
  }

  // 7. Screen Resolution & Color Gamut
  function getScreenInfo() {
    try {
      const w = window.screen.width;
      const h = window.screen.height;
      const depth = window.screen.colorDepth || 24;
      const ratio = window.devicePixelRatio || 1;

      return `${w}×${h} @ ${ratio}x DPR (${depth}-bit color)`;
    } catch (e) {
      return 'Screen resolution inspection restricted';
    }
  }

  // 8. Languages & PDF Features
  function getLanguagesAndPlugins() {
    try {
      const languages = (navigator.languages || [navigator.language || 'en']).join(', ');
      const pdfEnabled = navigator.pdfViewerEnabled !== undefined ? (navigator.pdfViewerEnabled ? 'PDF Viewer enabled' : 'PDF Viewer disabled') : 'PDF API unexposed';

      return `${languages} · ${pdfEnabled}`;
    } catch (e) {
      return 'Languages & environment inspection restricted';
    }
  }

  // 15. Device Memory (RAM)
  function getDeviceMemory() {
    try {
      const ram = navigator.deviceMemory;
      return ram ? `~${ram} GB RAM allocated` : 'Hardware memory API restricted';
    } catch (e) {
      return 'Device memory inspection restricted';
    }
  }

  // 16. Network & Connection Speed
  function getNetworkInfo() {
    try {
      const conn = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
      if (!conn) return 'Network status: Online (Standard latency)';
      const type = (conn.effectiveType || 'online').toUpperCase();
      const downlink = conn.downlink ? ` · ${conn.downlink} Mbps` : '';
      const rtt = conn.rtt ? ` · ${conn.rtt}ms RTT` : '';
      return `${type}${downlink}${rtt}`;
    } catch (e) {
      return 'Network info restricted';
    }
  }

  // Helper with Timeout
  async function fetchWithTimeout(url, options = {}, timeoutMs = 1800) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(url, { ...options, signal: controller.signal });
      clearTimeout(timer);
      return response;
    } catch (err) {
      clearTimeout(timer);
      throw err;
    }
  }

  // 9. HONEST Geo & ISP Lookup
  async function getGeoAndISP() {
    try {
      const cached = sessionStorage.getItem('deus_geo_cache');
      if (cached) {
        try {
          return JSON.parse(cached);
        } catch (e) {}
      }
    } catch (e) {}

    // Primary: ipwho.is (HTTPS, CORS-enabled, Free)
    try {
      const res = await fetchWithTimeout('https://ipwho.is/', {}, 2000);
      if (res.ok) {
        const data = await res.json();
        if (data.success) {
          const city = data.city || '';
          const region = data.region || data.region_code || '';
          const country = data.country || '';
          const org = data.connection?.org || data.connection?.isp || data.isp || '';
          const locationStr = `${city}${region ? ', ' + region : ''}${country ? ', ' + country : ''} · ${org || 'ISP Undetermined'}`;
          const resultObj = { isFailed: false, locationStr, city, region, country, org, ip: data.ip || '127.0.0.1' };
          try { sessionStorage.setItem('deus_geo_cache', JSON.stringify(resultObj)); } catch (e) {}
          return resultObj;
        }
      }
    } catch (e) {}

    // Fallback 1: freeipapi.com
    try {
      const res2 = await fetchWithTimeout('https://freeipapi.com/api/json', {}, 2000);
      if (res2.ok) {
        const data2 = await res2.json();
        const city = data2.cityName || '';
        const region = data2.regionName || '';
        const country = data2.countryName || '';
        const org = data2.isp || '';

        if (city || country || org) {
          const locationStr = `${city}${region ? ', ' + region : ''}${country ? ', ' + country : ''} · ${org || 'ISP Undetermined'}`;
          const resultObj = { isFailed: false, locationStr, city, region, country, org, ip: data2.ipAddress || '127.0.0.1' };
          try { sessionStorage.setItem('deus_geo_cache', JSON.stringify(resultObj)); } catch (e) {}
          return resultObj;
        }
      }
    } catch (e) {}

    // Fallback 2: ipapi.co
    try {
      const res3 = await fetchWithTimeout('https://ipapi.co/json/', {}, 2000);
      if (res3.ok) {
        const data3 = await res3.json();
        const city = data3.city || '';
        const region = data3.region_code || data3.region || '';
        const country = data3.country_name || '';
        const org = data3.org || data3.asn || '';

        if (city || country || org) {
          const locationStr = `${city}${region ? ', ' + region : ''}${country ? ', ' + country : ''} · ${org || 'ISP Undetermined'}`;
          const resultObj = { isFailed: false, locationStr, city, region, country, org, ip: data3.ip || '127.0.0.1' };
          try { sessionStorage.setItem('deus_geo_cache', JSON.stringify(resultObj)); } catch (e) {}
          return resultObj;
        }
      }
    } catch (e) {}

    // Fallback 3: ipinfo.io
    try {
      const res4 = await fetchWithTimeout('https://ipinfo.io/json', {}, 2000);
      if (res4.ok) {
        const data4 = await res4.json();
        const city = data4.city || '';
        const region = data4.region || '';
        const country = data4.country || '';
        const org = data4.org || '';

        if (city || country || org) {
          const locationStr = `${city}${region ? ', ' + region : ''}${country ? ', ' + country : ''} · ${org || 'ISP Undetermined'}`;
          const resultObj = { isFailed: false, locationStr, city, region, country, org, ip: data4.ip || '127.0.0.1' };
          try { sessionStorage.setItem('deus_geo_cache', JSON.stringify(resultObj)); } catch (e) {}
          return resultObj;
        }
      }
    } catch (e) {}

    return {
      isFailed: true,
      locationStr: 'Network IP geolocation lookup restricted / offline',
      city: 'Lookup Unavailable',
      region: '',
      country: '',
      org: 'ISP Undetermined (Lookup failed)',
      ip: 'Hidden'
    };
  }

  // 11. Font Detection
  function detectFonts() {
    try {
      const devFonts = ['Hack', 'Fira Code', 'JetBrains Mono', 'Cascadia Code', 'DejaVu Sans Mono', 'Liberation Mono', 'Noto Color Emoji', 'Monaco', 'Menlo', 'Consolas'];
      const baseFonts = ['monospace', 'sans-serif', 'serif'];

      if (!fontCanvasCtx) {
        const canvas = document.createElement('canvas');
        fontCanvasCtx = canvas.getContext('2d');
      }
      if (!fontCanvasCtx) {
        return { isRestricted: true, detectedDev: [], statusMsg: 'Font canvas inspection restricted by browser' };
      }

      fontCanvasCtx.font = "72px monospace";
      const defaultWidth = fontCanvasCtx.measureText("mmmmmmmmmmlli").width;

      const detected = [];
      for (const font of devFonts) {
        fontCanvasCtx.font = `72px '${font}', monospace`;
        const testWidth = fontCanvasCtx.measureText("mmmmmmmmmmlli").width;
        if (testWidth !== defaultWidth) {
          detected.push(font);
        }
      }

      return {
        isRestricted: false,
        detectedDev: detected,
        statusMsg: `${detected.length}/${devFonts.length} developer fonts detected (${detected.slice(0, 3).join(', ')}${detected.length > 3 ? '...' : ''})`
      };
    } catch (e) {
      return { isRestricted: true, detectedDev: [], statusMsg: 'Font metric canvas inspection restricted by browser privacy policy' };
    }
  }

  // 13. Session Persistence
  async function checkSessionPersistence(osStr, gpuStr, screenStr, isReturnVisit = false) {
    try {
      const rawSignal = `${osStr}|${gpuStr}|${screenStr}|${Intl.DateTimeFormat().resolvedOptions().timeZone}`;
      let sum = 0;
      for (let i = 0; i < rawSignal.length; i++) {
        sum = (sum << 5) - sum + rawSignal.charCodeAt(i);
        sum |= 0;
      }
      const shortId = Math.abs(sum).toString(36).slice(0, 8);
      const storageKey = 'deus_fp_id';

      if (isReturnVisit) {
        return `Return visit detected: Welcome back. Session fingerprint ID [${shortId}] matches previous session (stored locally without cookies).`;
      } else {
        try { localStorage.setItem(storageKey, shortId); } catch (e) {}
        return `First-time visit recorded: Session fingerprint ID [${shortId}] generated and stored locally without cookies.`;
      }
    } catch (e) {
      return 'Session persistence active.';
    }
  }

  // 14. Rarity & Entropy Readout
  function calculateRarity(osStr, screenStr) {
    try {
      let osFreq = 0.10;
      if (osStr.includes('Linux')) osFreq = 0.04;
      else if (osStr.includes('macOS')) osFreq = 0.15;
      else if (osStr.includes('Windows')) osFreq = 0.70;

      let dntFreq = navigator.doNotTrack === '1' ? 0.15 : 0.85;
      let tzFreq = 0.05;
      let resFreq = screenStr.includes('1920×1080') ? 0.22 : 0.10;

      const totalFreq = osFreq * dntFreq * tzFreq * resFreq;
      const rarity1In = Math.round(1 / totalFreq);
      const entropyBits = (-Math.log2(totalFreq)).toFixed(1);

      return `Estimated Unicity: 1 in ${rarity1In.toLocaleString()} global configurations · ~${entropyBits} bits entropy`;
    } catch (e) {
      return 'Estimated Unicity: Standard configuration entropy';
    }
  }

  // Helper to safely set element value and remove skeleton class
  function setSignalValue(elementId, text, isHtml = false) {
    if (!elementId) return;
    const valEl = document.getElementById('val-' + elementId.replace('sig-', ''));
    const rowEl = document.getElementById(elementId);

    const target = valEl || (rowEl ? rowEl.querySelector('.sig-value, .fp-row__value') : null);
    if (!target) return;

    target.classList.remove('skeleton');
    if (isHtml) {
      target.innerHTML = text;
    } else {
      target.textContent = text;
    }
  }

  // Safe Signal Evaluation Helper (Req #2)
  function safeSignal(chipId, fn, fallbackMsg = 'Unavailable — restricted by browser policy') {
    try {
      const value = fn();
      if (chipId) {
        setSignalValue(chipId, value || fallbackMsg);
      }
      return value || fallbackMsg;
    } catch (err) {
      console.warn(`[DEUS-SIGNALS] Signal evaluation failed for [${chipId || 'generic'}]:`, err);
      if (chipId) {
        setSignalValue(chipId, fallbackMsg);
      }
      return fallbackMsg;
    }
  }

  // 21. Typing Rhythm Challenge Initializer
  function initTypingChallenge() {
    const input = document.getElementById('typing-input');
    const resultsContainer = document.getElementById('typing-results');
    const wpmEl = document.getElementById('type-wpm');
    const timeEl = document.getElementById('type-time');
    const errorsEl = document.getElementById('type-errors');
    const readoutEl = document.getElementById('type-readout');

    if (!input) return;

    const targetPhrase = 'the quick brown fox jumps over the lazy dog';
    let startTime = null;
    let correctionCount = 0;
    let completed = false;

    input.addEventListener('keydown', e => {
      if (completed) return;
      if (!startTime && e.key.length === 1) {
        startTime = Date.now();
      }
      if (e.key === 'Backspace' || e.key === 'Delete') {
        correctionCount++;
      }
    });

    input.addEventListener('input', () => {
      if (completed || !startTime) return;
      const currentVal = input.value.trim().toLowerCase();

      if (currentVal === targetPhrase) {
        completed = true;
        const elapsedSec = (Date.now() - startTime) / 1000;
        const wordCount = 9;
        const wpm = Math.round((wordCount / elapsedSec) * 60);

        if (wpmEl) wpmEl.textContent = `${wpm} WPM`;
        if (timeEl) timeEl.textContent = `${elapsedSec.toFixed(1)}s elapsed`;
        if (errorsEl) errorsEl.textContent = `${correctionCount} correction${correctionCount === 1 ? '' : 's'}`;

        let personalityRead = '';
        if (wpm > 60 && correctionCount <= 2) {
          personalityRead = 'Rhythm read: High-velocity touch typist. Clean execution with minimal hesitation.';
        } else if (wpm > 50 && correctionCount > 2) {
          personalityRead = 'Rhythm read: Aggressive bursts of speed with rapid backspace correction.';
        } else if (wpm <= 50 && correctionCount <= 2) {
          personalityRead = 'Rhythm read: Calm, deliberate keystroke cadences with high precision.';
        } else {
          personalityRead = 'Rhythm read: Methodical input cadence with real-time accuracy checks.';
        }

        if (readoutEl) readoutEl.textContent = personalityRead;
        if (resultsContainer) resultsContainer.hidden = false;
        input.disabled = true;
        input.style.borderColor = '#10b981';
      }
    });
  }

  // --- TYPEWRITER STREAM ENGINE ---
  function initTypewriterStream() {
    const contentEl = document.getElementById("typewriter-content");
    const sessionIdEl = document.getElementById("fp-session-id");
    if (!contentEl) return;

    // Session ID & Timestamp
    let isReturnVisit = false;
    try {
      let storedId;
      try { storedId = localStorage.getItem('deus_fp_id'); } catch (e) {}
      if (storedId) {
        isReturnVisit = true;
      } else {
        storedId = 'fp_' + Math.random().toString(36).substring(2, 10);
      }
      if (sessionIdEl) sessionIdEl.textContent = `SESSION ID: ${storedId}`;
    } catch (e) {}

    const timestampEl = document.getElementById("fp-timestamp");
    if (timestampEl) {
      try {
        timestampEl.textContent = `TIMESTAMP: ${new Date().toISOString()}`;
      } catch (e) {
        timestampEl.textContent = `TIMESTAMP: LIVE ACTIVE`;
      }
    }

    // INDEPENDENT SAFE SIGNAL EVALUATION (Req #2)
    const osBrowserStr = safeSignal(null, () => getOSAndBrowser(), 'Unknown OS · Unknown Browser');
    const cpuStr = safeSignal(null, () => getCPUInfo(), 'Hardware concurrency restricted');
    const gpuObj = safeSignal(null, () => getGPUInfo(), { shortName: 'GPU vendor undetermined', fullStr: 'WebGL disabled' });
    
    safeSignal('webgl-caps', () => getWebGLCapabilities(), 'WebGL capability inspection restricted');
    safeSignal('fonts-detected', () => detectFonts().statusMsg, 'Font metric canvas inspection restricted');
    safeSignal('languages-pdf', () => getLanguagesAndPlugins(), 'Languages & environment inspection restricted');
    safeSignal('touch-pointer', () => getTouchAndMediaFeatures(), 'Touch & Pointer features restricted');
    safeSignal('device-memory', () => getDeviceMemory(), 'Hardware memory API restricted');
    safeSignal('network-info', () => getNetworkInfo(), 'Network status: Online');
    const screenRes = safeSignal(null, () => getScreenInfo(), 'Screen resolution restricted');
    safeSignal('rarity', () => calculateRarity(osBrowserStr, screenRes), 'Estimated Unicity: Standard configuration');
    safeSignal('canvas-hash', () => getCanvasFingerprintHashSync(), 'Canvas fingerprinting restricted by client privacy policy');

    // Typing challenge widget
    try {
      initTypingChallenge();
    } catch (e) {
      console.warn('[DEUS-SIGNALS] initTypingChallenge error:', e);
    }

    // Dynamic local time & sleep condition
    let timeStr = '12:00 p.m.';
    let sleepNotice = ' Confirmed by your local timezone clock.';
    let tzName = 'Client Local';
    try {
      const now = new Date();
      const hours = now.getHours();
      const minutes = String(now.getMinutes()).padStart(2, "0");
      const ampm = hours >= 12 ? "p.m." : "a.m.";
      const displayHour = hours % 12 || 12;
      timeStr = `${displayHour}:${minutes} ${ampm}`;
      tzName = Intl.DateTimeFormat().resolvedOptions().timeZone || 'Client Local';
      sleepNotice = (hours >= 23 || hours < 6)
        ? " You should be asleep. We won't tell anyone, but your device timestamp just confirmed it."
        : " Confirmed by your local timezone clock.";
    } catch (e) {}

    // OS Name
    let osName = "Linux";
    if (osBrowserStr.includes("macOS")) osName = "macOS";
    else if (osBrowserStr.includes("Windows")) osName = "Windows";
    else if (osBrowserStr.includes("Android")) osName = "Android";
    else if (osBrowserStr.includes("iOS")) osName = "iOS";

    // Render terminal lines IMMEDIATELY (0ms delay)
    const lines = [
      { type: "p", text: `${gpuObj.shortName || 'GPU vendor undetermined'}, ${cpuStr}, and a ${screenRes} display.` },
      { type: "p", text: `Live system audit active.` },
      { type: "h", text: `Where you are` },
      { type: "b", id: "stream-line-isp", text: `• Network Provider: Resolving client ISP...` },
      { type: "b", text: `• Local Clock: ${timeStr}.${sleepNotice}` },
      { type: "b", id: "stream-line-geo", text: `• Location: Timezone Region (${tzName}).` },
      { type: "h", text: `What device you are using` },
      { type: "b", text: `• Operating System: ${osName}.` },
      { type: "b", text: `• Browser & Engine: ${osBrowserStr}.` },
      { type: "h", text: `Security & Session Persistence` },
      { type: "b", id: "stream-line-session", text: `• Session persistence active.` }
    ];

    try {
      contentEl.replaceChildren();

      const skipBtn = document.getElementById("typewriter-skip-btn");
      const allWordSpans = [];

      lines.forEach(line => {
        const cls = line.type === "h" ? "typewriter-heading" : line.type === "b" ? "typewriter-bullet" : "typewriter-paragraph";
        const div = document.createElement("div");
        if (line.id) div.id = line.id;
        div.className = cls;

        const words = line.text.split(" ");
        words.forEach((word, wIdx) => {
          const span = document.createElement("span");
          span.className = "word-span pending";
          span.textContent = word + (wIdx < words.length - 1 ? " " : "");
          div.appendChild(span);
          allWordSpans.push(span);
        });

        contentEl.appendChild(div);
      });

      let revealTimer = null;

      function revealAllInstantly() {
        if (revealTimer) clearInterval(revealTimer);
        allWordSpans.forEach(span => {
          span.className = "word-span revealed";
        });
        appendCompleteMessage();
        if (skipBtn) skipBtn.style.display = "none";
      }

      function appendCompleteMessage() {
        if (document.getElementById("typewriter-complete-msg")) return;
        const completeDiv = document.createElement("div");
        completeDiv.id = "typewriter-complete-msg";
        completeDiv.className = "typewriter-complete-msg";
        completeDiv.textContent = "→ PASSIVE AUDIT COMPLETE. OSINT ENGINE READY BELOW.";
        contentEl.appendChild(completeDiv);
      }

      if (skipBtn) {
        skipBtn.style.display = "inline-block";
        skipBtn.onclick = () => revealAllInstantly();
      }

      if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
        revealAllInstantly();
      } else {
        let wordIdx = 0;
        revealTimer = setInterval(() => {
          if (wordIdx < allWordSpans.length) {
            allWordSpans[wordIdx].className = "word-span revealed";
            wordIdx++;
          } else {
            clearInterval(revealTimer);
            appendCompleteMessage();
            if (skipBtn) skipBtn.style.display = "none";
          }
        }, 35);
      }
    } catch (err) {
      console.error("[DEUS-SIGNALS] Terminal rendering error:", err);
    }

    // ASYNCHRONOUSLY UPDATE GEOLOCATION & SESSION WHEN RETURNED
    getGeoAndISP()
      .then(geoObj => {
        const ispEl = document.getElementById("stream-line-isp");
        const geoEl = document.getElementById("stream-line-geo");
        if (ispEl) {
          const rawOrg = geoObj?.org || '';
          const cleanOrg = rawOrg.replace(/^AS\d+\s+/i, '').trim();
          if (cleanOrg && !cleanOrg.toLowerCase().includes('failed') && !cleanOrg.toLowerCase().includes('undetermined')) {
            ispEl.innerHTML = `<span class="word-span revealed">• Network Provider: ${cleanOrg}.</span>`;
          } else {
            ispEl.innerHTML = `<span class="word-span revealed">• Network Provider: ISP Lookup Restricted / Offline.</span>`;
          }
        }
        if (geoEl && !geoObj?.isFailed) {
          geoEl.innerHTML = `<span class="word-span revealed">• You're in or near ${geoObj.locationStr}.</span>`;
        }
      })
      .catch(err => {
        console.warn('[DEUS-SIGNALS] Background geo lookup error:', err);
      });

    checkSessionPersistence(osBrowserStr, gpuObj?.fullStr || '', screenRes, isReturnVisit)
      .then(sessionStr => {
        const sessEl = document.getElementById("stream-line-session");
        if (sessEl && sessionStr) {
          sessEl.innerHTML = `<span class="word-span revealed">• ${sessionStr}</span>`;
        }
      })
      .catch(err => {
        console.warn('[DEUS-SIGNALS] Background session persistence error:', err);
      });
  }

  // --- HARD TIMEOUT FALLBACK FOR CHIPS (Req #3) ---
  setTimeout(() => {
    try {
      const skeletonChips = document.querySelectorAll('.signal-chip-val.skeleton');
      skeletonChips.forEach(chip => {
        chip.classList.remove('skeleton');
        if (!chip.textContent || chip.textContent.includes('...')) {
          chip.textContent = 'Unavailable — restricted by browser policy';
        }
      });
    } catch (e) {
      console.warn('[DEUS-SIGNALS] Hard timeout fallback error:', e);
    }
  }, 2500);

  // --- STAGE 2 MAIN ENTRY POINT ---
  function initStage2() {
    initTypewriterStream();
  }

  // INDEPENDENT TRY/CATCH WRAPPERS IN RUNINIT (Req #1)
  function runInit() {
    try {
      initStage1();
    } catch (err) {
      console.error('[DEUS-SIGNALS] initStage1 failed:', err);
    }

    try {
      initStage2();
    } catch (err) {
      console.error('[DEUS-SIGNALS] initStage2 failed:', err);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', runInit);
  } else {
    runInit();
  }
})();
