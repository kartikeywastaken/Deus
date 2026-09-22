/**
 * Deus OSINT Toolkit — Fingerprint Reveal Engine
 * Gathers passive client browser signals in real time without cookies or permissions.
 */

(function () {
  'use strict';

  if (typeof window === 'undefined' || typeof document === 'undefined') return;

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
      window.lenis.stop();
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
        window.lenis.start();
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
      gsap.fromTo(
        element,
        { opacity: 0, y: 30 },
        { opacity: 1, y: 0, duration: 0.8, ease: 'power3.out' }
      );
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
      const brands = navigator.userAgentData.brands.map(b => `${b.brand} v${b.version}`).join(', ');
      uaDataStr = ` [Sec-CH-UA: ${brands}]`;
    }

    return `${os} · ${browser}${uaDataStr}`;
  }

  // 2. CPU Concurrency & Architecture
  function getCPUInfo() {
    const cores = navigator.hardwareConcurrency;
    let arch = 'Unknown arch';
    if (/arm|aarch64/i.test(navigator.userAgent || '')) arch = 'ARM architecture';
    else if (/x86_64|x64|wow64/i.test(navigator.userAgent || '')) arch = 'x86_64 architecture';

    return cores ? `${cores} logical CPU cores (${arch})` : `Hardware concurrency restricted (${arch})`;
  }

  // 3. GPU Vendor & Renderer Parsing (HONEST GPU DETECTION)
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
      return 'WebGL capability inspection restricted';
    }
  }

  // 5. Canvas Fingerprint Hash
  async function getCanvasFingerprintHash() {
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

      let hash = 'canvas_';
      if (window.crypto?.subtle) {
        const encoder = new TextEncoder();
        const data = encoder.encode(dataUrl);
        const buffer = await crypto.subtle.digest('SHA-256', data);
        const arr = Array.from(new Uint8Array(buffer));
        hash = arr.map(b => b.toString(16).padStart(2, '0')).join('').slice(0, 16);
      } else {
        let sum = 0;
        for (let i = 0; i < dataUrl.length; i++) {
          sum = (sum << 5) - sum + dataUrl.charCodeAt(i);
          sum |= 0;
        }
        hash = 'fnv_' + Math.abs(sum).toString(16);
      }
      return `Canvas Hash: [${hash}]`;
    } catch (e) {
      return 'Canvas fingerprinting restricted by client privacy policy';
    }
  }



  // 7. Screen Resolution & Color Gamut
  function getScreenInfo() {
    const w = window.screen.width;
    const h = window.screen.height;
    const dpr = window.devicePixelRatio || 1;
    const depth = window.screen.colorDepth || 24;

    let gamut = 'sRGB';
    if (window.matchMedia('(color-gamut: rec2020)').matches) gamut = 'Rec.2020';
    else if (window.matchMedia('(color-gamut: p3)').matches) gamut = 'Display P3';

    return `${w}×${h} px @ ${dpr}x DPR · ${depth}-bit color (${gamut} gamut)`;
  }

  // 8. Timezone & Live Clock
  function initTimezoneAndClock(targetEl) {
    if (!targetEl) return;
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';

    function updateClock() {
      const now = new Date();
      const timeStr = now.toLocaleTimeString('en-US', { hour12: false });
      const offsetMinutes = -now.getTimezoneOffset();
      const sign = offsetMinutes >= 0 ? '+' : '-';
      const hrs = String(Math.floor(Math.abs(offsetMinutes) / 60)).padStart(2, '0');
      const mins = String(Math.abs(offsetMinutes) % 60).padStart(2, '0');
      const utcOffset = `UTC${sign}${hrs}:${mins}`;

      targetEl.textContent = `${tz} (${utcOffset}) · Local time: ${timeStr}`;
    }

    updateClock();
    setInterval(updateClock, 1000);
  }

  async function fetchWithTimeout(url, options = {}, timeoutMs = 2500) {
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

  // 9. HONEST Geo & ISP Lookup (NO FAKE GUNTUR / CLOUDFLARE FALLBACK)
  async function getGeoAndISP() {
    const cached = sessionStorage.getItem('deus_geo_cache');
    if (cached) {
      try {
        return JSON.parse(cached);
      } catch (e) {
        /* ignore */
      }
    }

    // Primary: ipwho.is (HTTPS, CORS-enabled, Free)
    try {
      const res = await fetchWithTimeout('https://ipwho.is/', {}, 1800);
      if (res.ok) {
        const data = await res.json();
        if (data.success) {
          const city = data.city || '';
          const region = data.region || data.region_code || '';
          const country = data.country || '';
          const org = data.connection?.org || data.connection?.isp || data.isp || '';
          const locationStr = `${city}${region ? ', ' + region : ''}${country ? ', ' + country : ''} · ${org || 'ISP Undetermined'}`;
          const resultObj = { isFailed: false, locationStr, city, region, country, org, ip: data.ip || '127.0.0.1' };
          sessionStorage.setItem('deus_geo_cache', JSON.stringify(resultObj));
          return resultObj;
        }
      }
    } catch (e) {
      /* try fallback */
    }

    // Fallback: ipapi.co
    try {
      const res2 = await fetchWithTimeout('https://ipapi.co/json/', {}, 1800);
      if (res2.ok) {
        const data2 = await res2.json();
        const city = data2.city || '';
        const region = data2.region_code || data2.region || '';
        const country = data2.country_name || '';
        const org = data2.org || data2.asn || '';

        if (city || country || org) {
          const locationStr = `${city}${region ? ', ' + region : ''}${country ? ', ' + country : ''} · ${org || 'ISP Undetermined'}`;
          const resultObj = { isFailed: false, locationStr, city, region, country, org, ip: data2.ip || '127.0.0.1' };
          sessionStorage.setItem('deus_geo_cache', JSON.stringify(resultObj));
          return resultObj;
        }
      }
    } catch (e) {
      /* ignore */
    }

    // HONEST FAILURE RETURN
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

  // 10. Camera & Microphone Presence
  async function getMediaDevices() {
    if (!navigator.mediaDevices?.enumerateDevices) {
      return 'MediaDevices API enumerateDevices restricted';
    }
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      const videoCount = devices.filter(d => d.kind === 'videoinput').length;
      const audioCount = devices.filter(d => d.kind === 'audioinput').length;
      return `${videoCount} camera input${videoCount === 1 ? '' : 's'} · ${audioCount} microphone input${audioCount === 1 ? '' : 's'} detected`;
    } catch (e) {
      return 'Media device enumeration restricted by browser permission policy';
    }
  }

  // 11. HONEST Font Detection (NO FAKE PROGRAMMER FONTS ASSERTION)
  function detectFonts() {
    const devFonts = [
      'Hack',
      'Fira Code',
      'JetBrains Mono',
      'Cascadia Code',
      'DejaVu Sans Mono',
      'Liberation Mono',
      'Noto Color Emoji',
      'Code New Roman',
      'Monaco',
      'Menlo',
      'Consolas'
    ];
    const extendedFonts = [
      'Arial',
      'Helvetica',
      'Times New Roman',
      'Georgia',
      'Courier New',
      'Verdana',
      'Trebuchet MS',
      'Impact',
      'Comic Sans MS',
      'Segoe UI',
      'Roboto',
      'Ubuntu',
      'Cantarell',
      'SF Pro',
      'Palatino',
      'Garamond',
      'Papyrus'
    ];
    const testString = 'mmmmmmmmmmlliWWWWWWWWW1234567890';

    try {
      if (!fontCanvasCtx) {
        const canvas = document.createElement('canvas');
        fontCanvasCtx = canvas.getContext('2d');
      }
      if (!fontCanvasCtx) {
        return {
          isRestricted: true,
          detectedDev: [],
          detectedExt: [],
          statusMsg: 'Font metric canvas inspection restricted / context disabled'
        };
      }

      const baseFonts = ['monospace', 'sans-serif', 'serif'];
      const baseWidths = {};
      baseFonts.forEach(base => {
        fontCanvasCtx.font = `72px ${base}`;
        baseWidths[base] = fontCanvasCtx.measureText(testString).width;
      });

      const checkFont = font => {
        for (const base of baseFonts) {
          fontCanvasCtx.font = `72px '${font}', ${base}`;
          if (fontCanvasCtx.measureText(testString).width !== baseWidths[base]) {
            return true;
          }
        }
        return false;
      };

      const detectedDev = devFonts.filter(checkFont);
      const detectedExt = extendedFonts.filter(checkFont);

      let statusMsg = '';
      if (detectedDev.length > 0) {
        statusMsg = `Detected ${detectedDev.length} developer font${detectedDev.length > 1 ? 's' : ''} (${detectedDev.join(', ')})`;
      } else if (detectedExt.length > 0) {
        statusMsg = `Identified system font stack: ${detectedExt.slice(0, 5).join(', ')}`;
      } else {
        statusMsg = 'Standard system font stack identified (no specialized custom fonts detected)';
      }

      return { isRestricted: false, detectedDev, detectedExt, statusMsg };
    } catch (e) {
      return {
        isRestricted: true,
        detectedDev: [],
        detectedExt: [],
        statusMsg: 'Font metric canvas inspection restricted by browser privacy policy'
      };
    }
  }



  // 13. Session Persistence (No-Cookie Check)
  async function checkSessionPersistence(osStr, gpuStr, screenStr) {
    const rawSignal = `${osStr}|${gpuStr}|${screenStr}|${Intl.DateTimeFormat().resolvedOptions().timeZone}`;
    let hash = 'fp_' + String(rawSignal.length);

    try {
      if (window.crypto?.subtle) {
        const encoder = new TextEncoder();
        const data = encoder.encode(rawSignal);
        const hashBuffer = await crypto.subtle.digest('SHA-256', data);
        const hashArray = Array.from(new Uint8Array(hashBuffer));
        hash = hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
      }
    } catch (e) {
      /* fallback */
    }

    const shortId = hash.slice(0, 12);
    const storageKey = 'deus_fp_id';
    const previousVisit = localStorage.getItem(storageKey);

    if (previousVisit) {
      return `Return visit detected: Welcome back. Session fingerprint ID [${shortId}] matches previous session (stored locally without cookies).`;
    } else {
      localStorage.setItem(storageKey, shortId);
      return `First-time visit recorded: Session fingerprint ID [${shortId}] generated and stored locally without cookies.`;
    }
  }

  // 14. Rarity & Entropy Readout
  function calculateRarity(osStr, screenStr) {
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
  }

  // Helper to safely set element value and remove skeleton class
  function setSignalValue(elementId, text, isHtml = false) {
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

    try {
      let storedId = localStorage.getItem('deus_fp_id');
      if (!storedId) {
        storedId = 'fp_' + Math.random().toString(36).substring(2, 10);
        localStorage.setItem('deus_fp_id', storedId);
      }
      if (sessionIdEl) sessionIdEl.textContent = `SESSION ID: ${storedId}`;

      const timestampEl = document.getElementById("fp-timestamp");
      if (timestampEl) {
        timestampEl.textContent = `TIMESTAMP: ${new Date().toISOString()}`;
      }

      // Gather synchronous signals instantly
      const osBrowserStr = getOSAndBrowser();
      const cpuStr = getCPUInfo();
      const gpuObj = getGPUInfo();
      const webglCapsStr = getWebGLCapabilities();
      const fontsObj = detectFonts();
      const languagesPluginsStr = getLanguagesAndPlugins();
      const touchMediaStr = getTouchAndMediaFeatures();
      const screenRes = getScreenInfo();
      const unicityStr = calculateRarity(osBrowserStr, screenRes);

      // Instantly populate all synchronous signal chips (removes skeleton class)
      setSignalValue('rarity', unicityStr);
      setSignalValue('webgl-caps', webglCapsStr);
      setSignalValue('touch-pointer', touchMediaStr);
      setSignalValue('languages-pdf', languagesPluginsStr);
      setSignalValue('fonts-detected', fontsObj.statusMsg);
      setSignalValue('canvas-hash', 'Canvas Hash: [computing...]');

      // Initialize typing challenge widget
      initTypingChallenge();

      // Dynamic local time & sleep condition
      const now = new Date();
      const hours = now.getHours();
      const minutes = String(now.getMinutes()).padStart(2, "0");
      const ampm = hours >= 12 ? "p.m." : "a.m.";
      const displayHour = hours % 12 || 12;
      const timeStr = `${displayHour}:${minutes} ${ampm}`;

      let sleepNotice = (hours >= 23 || hours < 6)
        ? " You should be asleep. We won't tell anyone, but your device timestamp just confirmed it."
        : " Confirmed by your local timezone clock.";

      // OS Name
      let osName = "Linux";
      if (osBrowserStr.includes("macOS")) osName = "macOS";
      else if (osBrowserStr.includes("Windows")) osName = "Windows";
      else if (osBrowserStr.includes("Android")) osName = "Android";
      else if (osBrowserStr.includes("iOS")) osName = "iOS";

      // Render terminal lines IMMEDIATELY (0ms delay)
      const lines = [
        { type: "p", text: `${gpuObj.shortName}, ${cpuStr}, and a ${screenRes} display.` },
        { type: "p", text: `Live system audit active.` },
        { type: "h", text: `Where you are` },
        { type: "b", id: "stream-line-isp", text: `• Network Provider: Resolving...` },
        { type: "b", text: `• Local Clock: ${timeStr}.${sleepNotice}` },
        { type: "b", id: "stream-line-geo", text: `• Location: Resolving network IP...` },
        { type: "h", text: `What device you are using` },
        { type: "b", text: `• Operating System: ${osName}.` },
        { type: "b", text: `• Browser & Engine: ${osBrowserStr}.` },
        { type: "h", text: `Security & Session Persistence` },
        { type: "b", id: "stream-line-session", text: `• Session persistence active.` }
      ];

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
        }, 40);
      }

      // ASYNCHRONOUSLY UPDATE RESOLVING LINES AS SOON AS ASYNC PROMISES RETURN
      getCanvasFingerprintHash()
        .then(hashStr => setSignalValue('canvas-hash', hashStr))
        .catch(() => setSignalValue('canvas-hash', 'Canvas Hash: [unavailable]'));

      getGeoAndISP()
        .then(geoObj => {
          const ispEl = document.getElementById("stream-line-isp");
          const geoEl = document.getElementById("stream-line-geo");
          if (ispEl) {
            ispEl.innerHTML = `<span class="word-span revealed">• Network Provider: ${geoObj.org || 'ISP Undetermined'}.</span>`;
          }
          if (geoEl) {
            const locText = geoObj.isFailed
              ? `• Location lookup: IP geolocation endpoint restricted / offline.`
              : `• You're in or near ${geoObj.locationStr}.`;
            geoEl.innerHTML = `<span class="word-span revealed">${locText}</span>`;
          }
        })
        .catch(() => {
          const locEl = document.getElementById("stream-line-geo");
          if (locEl) locEl.innerHTML = `<span class="word-span revealed">• Location lookup: IP geolocation endpoint restricted / offline.</span>`;
        });

      checkSessionPersistence(osBrowserStr, gpuObj.fullStr, screenRes)
        .then(sessionStr => {
          const sessEl = document.getElementById("stream-line-session");
          if (sessEl) sessEl.innerHTML = `<span class="word-span revealed">• ${sessionStr}</span>`;
        })
        .catch(() => {});

    } catch (err) {
      console.error("Typewriter stream error:", err);
    }
  }

  // --- STAGE 2 MAIN ENTRY POINT ---
  function initStage2() {
    initTypewriterStream();
  }

  document.addEventListener('DOMContentLoaded', () => {
    initStage1();
    initStage2();
  });
})();
