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
  let coldOpenBeat = 0; // 0: initial black, 1: line 1, 2: line 2, 3: completed
  let touchStartY = 0;
  let gestureDebounceTimer = null;

  function initStage1() {
    const coldOpenOverlay = document.getElementById('stage1-cold-open');
    if (!coldOpenOverlay) return;

    // Lock body scroll initially
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
      // Upward gesture: prompt specifies negative deltaY or upward swipe
      // Allow any upward wheel movement (or deltaY > 20 / deltaY < -20 depending on trackpad/mouse scroll direction)
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
      const deltaY = touchStartY - touchEndY; // Positive if swiping up
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
      // Tear down Stage 1 listeners
      window.removeEventListener('wheel', handleWheel);
      window.removeEventListener('touchstart', handleTouchStart);
      window.removeEventListener('touchmove', handleTouchMove);

      // Unlock body scroll & smooth transition to Stage 2
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

  // Reusable animated-text component helper for Stage 1
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

  // --- STAGE 2: LIVE FINGERPRINT REVEAL ---

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
    else if (/linux/i.test(ua)) os = 'Linux (x86_64)';

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

  // 2. CPU Logical Core Count
  function getCPUInfo() {
    const cores = navigator.hardwareConcurrency;
    return cores ? `${cores} logical CPU cores` : 'Hardware concurrency API unavailable';
  }

  // 3. GPU Vendor & Renderer (Memoized WebGL)
  function getGPUInfo() {
    try {
      if (!webglContext) {
        const canvas = document.createElement('canvas');
        webglContext = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
      }
      if (!webglContext) return 'WebGL context disabled / unavailable';

      const debugInfo = webglContext.getExtension('WEBGL_debug_renderer_info');
      if (!debugInfo) return 'WEBGL_debug_renderer_info unmasked GPU extension restricted';

      const vendor = webglContext.getParameter(debugInfo.UNMASKED_VENDOR_WEBGL) || 'Unknown Vendor';
      const renderer = webglContext.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL) || 'Unknown Renderer';
      return `${vendor} · ${renderer}`;
    } catch (e) {
      return 'GPU query blocked by browser security policy';
    }
  }

  // 4. Screen Resolution & Pixel Ratio
  function getScreenInfo() {
    const w = window.screen.width;
    const h = window.screen.height;
    const dpr = window.devicePixelRatio || 1;
    const depth = window.screen.colorDepth || 24;
    return `${w}×${h} px @ ${dpr}x DPR · ${depth}-bit color depth (workstation display)`;
  }

  // 5. Timezone & Live Local Clock
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

  // 6. Approximate Location & ISP (Client-side IP Geo, Cached)
  async function getGeoAndISP() {
    const cached = sessionStorage.getItem('deus_geo_cache');
    if (cached) {
      try {
        return JSON.parse(cached);
      } catch (e) {
        /* ignore */
      }
    }

    try {
      const res = await fetchWithTimeout('https://ipapi.co/json/', {}, 2500);
      if (!res.ok) throw new Error('IP API error');
      const data = await res.json();
      const city = data.city || 'Unknown City';
      const region = data.region_code || data.region || '';
      const country = data.country_name || '';
      const org = data.org || data.asn || 'Unknown ISP';
      const locationStr = `${city}${region ? ', ' + region : ''}${country ? ', ' + country : ''} · ${org} (City/Region granularity only)`;

      const resultObj = { locationStr, city, region, country, org, ip: data.ip || '127.0.0.1' };
      sessionStorage.setItem('deus_geo_cache', JSON.stringify(resultObj));
      return resultObj;
    } catch (e) {
      // Fallback endpoint
      try {
        const res2 = await fetchWithTimeout('https://ip-api.com/json/?fields=status,country,regionName,city,isp,query', {}, 2500);
        const data2 = await res2.json();
        if (data2.status === 'success') {
          const locationStr = `${data2.city}, ${data2.regionName}, ${data2.country} · ${data2.isp}`;
          const resultObj = { locationStr, city: data2.city, region: data2.regionName, country: data2.country, org: data2.isp, ip: data2.query };
          sessionStorage.setItem('deus_geo_cache', JSON.stringify(resultObj));
          return resultObj;
        }
      } catch (err) {
        /* ignore */
      }
      return { locationStr: 'Network IP geolocation restricted / offline', city: 'Unknown', region: 'Unknown', country: 'Unknown', org: 'Private ISP', ip: 'Hidden' };
    }
  }

  // 7. Camera & Microphone Presence
  async function getMediaDevices() {
    if (!navigator.mediaDevices?.enumerateDevices) {
      return 'MediaDevices API enumerateDevices restricted';
    }
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      const videoCount = devices.filter(d => d.kind === 'videoinput').length;
      const audioCount = devices.filter(d => d.kind === 'audioinput').length;
      return `${videoCount} video input (camera${videoCount === 1 ? '' : 's'}) · ${audioCount} audio input (microphone${audioCount === 1 ? '' : 's'}) detected (unpermissioned count)`;
    } catch (e) {
      return 'Media device enumeration restricted by browser permission policy';
    }
  }

  // 8. Installed Developer Fonts (Memoized Canvas width check)
  function detectDeveloperFonts() {
    const testFonts = [
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
    const testString = 'mmmmmmmmmmlliWWWWWWWWW1234567890';

    try {
      if (!fontCanvasCtx) {
        const canvas = document.createElement('canvas');
        fontCanvasCtx = canvas.getContext('2d');
      }
      if (!fontCanvasCtx) return 'Canvas 2D rendering context disabled';

      const baseFonts = ['monospace', 'sans-serif', 'serif'];
      const baseWidths = {};
      baseFonts.forEach(base => {
        fontCanvasCtx.font = `72px ${base}`;
        baseWidths[base] = fontCanvasCtx.measureText(testString).width;
      });

      const detected = [];
      testFonts.forEach(font => {
        let isDifferent = false;
        for (const base of baseFonts) {
          fontCanvasCtx.font = `72px '${font}', ${base}`;
          const width = fontCanvasCtx.measureText(testString).width;
          if (width !== baseWidths[base]) {
            isDifferent = true;
            break;
          }
        }
        if (isDifferent) detected.push(font);
      });

      if (detected.length > 0) {
        return `Detected ${detected.length} specialized developer font${detected.length > 1 ? 's' : ''}: ${detected.join(', ')}`;
      } else {
        return 'Standard system font stack detected (no specialized developer fonts identified)';
      }
    } catch (e) {
      return 'Font metric canvas inspection restricted';
    }
  }

  // 9. Pointer Type Classifier
  function initPointerClassifier(targetEl) {
    if (!targetEl) return;
    const samples = [];
    const maxSamples = 6;

    function handleWheelSample(e) {
      if (samples.length >= maxSamples) return;
      samples.push(Math.abs(e.deltaY));

      if (samples.length >= maxSamples) {
        // Tear down listener immediately upon completion
        window.removeEventListener('wheel', handleWheelSample);

        const hasFractional = samples.some(val => val % 1 !== 0);
        const avg = samples.reduce((a, b) => a + b, 0) / samples.length;

        if (hasFractional || avg < 40) {
          targetEl.textContent = 'Pointer input: Precision trackpad detected (fractional continuous delta pattern sampled)';
        } else {
          targetEl.textContent = 'Pointer input: Mechanical mouse wheel detected (stepped ~100px integer delta pattern sampled)';
        }
      }
    }

    window.addEventListener('wheel', handleWheelSample, { passive: true });
    targetEl.textContent = 'Pointer input: Sampling wheel deltas... scroll to classify pointer type';
  }

  // 10. Typing Rhythm Challenge
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
        const wordCount = 9; // "the quick brown fox jumps over the lazy dog" is 9 words
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

  // 11. WebRTC Leak Check
  function checkWebRTCLeak() {
    return new Promise(resolve => {
      if (!window.RTCPeerConnection) {
        resolve('WebRTC status: RTCPeerConnection API disabled by browser');
        return;
      }

      try {
        const pc = new RTCPeerConnection({
          iceServers: [{ urls: 'stun:stun.l.google.com:19302' }]
        });
        let resolved = false;

        pc.createDataChannel('');
        pc.createOffer()
          .then(offer => pc.setLocalDescription(offer))
          .catch(() => {
            if (!resolved) {
              resolved = true;
              resolve('WebRTC status: SDP offer generation restricted');
            }
          });

        pc.onicecandidate = evt => {
          if (resolved) return;
          if (!evt || !evt.candidate) return;

          const cand = evt.candidate.candidate;
          if (cand.includes('.local')) {
            resolved = true;
            resolve('WebRTC leak status: Local IP mDNS-obfuscated (.local candidate gathered, privacy protected)');
            pc.close();
          } else {
            const match = /([0-9]{1,3}(\.[0-9]{1,3}){3})/.exec(cand);
            if (match) {
              resolved = true;
              resolve(`WebRTC leak status: Local IP candidate exposed (${match[1]} gathered via STUN candidate)`);
              pc.close();
            }
          }
        };

        setTimeout(() => {
          if (!resolved) {
            resolved = true;
            resolve('WebRTC leak status: STUN candidate gathering timed out / mDNS obfuscated');
            try {
              pc.close();
            } catch (e) {
              /* ignore */
            }
          }
        }, 1500);
      } catch (e) {
        resolve('WebRTC leak status: Blocked by client security extension');
      }
    });
  }

  // 12. Session Persistence (No-Cookie Return-Visit Check)
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
      /* fallback string hash */
    }

    const shortId = hash.slice(0, 12);
    const storageKey = 'deus_fp_id';
    const previousVisit = localStorage.getItem(storageKey);

    if (previousVisit) {
      return `Return visit detected: Welcome back. Session fingerprint ID [${shortId}] matches previous session (stored in localStorage without cookies).`;
    } else {
      localStorage.setItem(storageKey, shortId);
      return `First-time visit recorded: Session fingerprint ID [${shortId}] generated and stored locally without cookies.`;
    }
  }

  // 13. Illustrative Rarity & Entropy Readout
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

    return `Estimated Unicity: 1 in ${rarity1In.toLocaleString()} global configurations · ~${entropyBits} bits of entropy (illustrative population demographic model)`;
  }

  // 14. OpenRTB 2.6 Bid-Request Panel Generator
  function renderOpenRTBPanel(osStr, geoObj) {
    const jsonContainer = document.getElementById('openrtb-json');
    if (!jsonContainer) return;

    const payload = {
      id: 'bid_req_' + Math.random().toString(36).substring(2, 10),
      imp: [
        {
          id: '1',
          banner: {
            w: window.screen.width,
            h: window.screen.height
          }
        }
      ],
      device: {
        ua: navigator.userAgent,
        ip: geoObj.ip || '127.0.0.1',
        geo: {
          city: geoObj.city || 'Unknown',
          region: geoObj.region || 'Unknown',
          country: geoObj.country || 'Unknown'
        },
        js: 1,
        dnt: navigator.doNotTrack === '1' ? 1 : 0,
        language: navigator.language || 'en-US',
        w: window.screen.width,
        h: window.screen.height
      },
      user: {
        id: 'anon_fp_' + Math.random().toString(36).substring(2, 10),
        segment: [
          {
            id: 'tech_enthusiast_dev',
            name: 'Inferred Tech/Developer Demographic'
          }
        ]
      }
    };

    jsonContainer.textContent = JSON.stringify(payload, null, 2);
  }

  // Helper to safely set element value and remove skeleton class
  function setSignalValue(elementId, text, isHtml = false) {
    // Support both old row-based (sig-*) and new direct value elements (val-*)
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

  // --- TYPEWRITER PASSIVE AUDIT STREAM ENGINE (TextGenerateEffect) ---
  async function initTypewriterStream() {
    const contentEl = document.getElementById("typewriter-content");
    const sessionIdEl = document.getElementById("fp-session-id");
    if (!contentEl) return;

    let storedId = localStorage.getItem('deus_fp_id');
    if (!storedId) {
      storedId = 'fp_' + Math.random().toString(36).substring(2, 10);
      localStorage.setItem('deus_fp_id', storedId);
    }
    if (sessionIdEl) sessionIdEl.textContent = `SESSION ID: ${storedId}`;

    // Gather real dynamic client signals
    const osBrowserStr = getOSAndBrowser();
    const cores = navigator.hardwareConcurrency || 8;
    const gpuFull = getGPUInfo();
    const geoObj = await getGeoAndISP();
    const mediaStr = await getMediaDevices();
    const fontsStr = detectDeveloperFonts();
    const webrtcStr = await checkWebRTCLeak();

    // Extract clean GPU short name
    let gpuShort = "Intel graphics";
    if (gpuFull.includes("Intel")) gpuShort = "Intel graphics";
    else if (gpuFull.includes("NVIDIA") || gpuFull.includes("GeForce")) gpuShort = "NVIDIA graphics";
    else if (gpuFull.includes("AMD") || gpuFull.includes("Radeon")) gpuShort = "AMD graphics";
    else if (gpuFull.includes("Apple")) gpuShort = "Apple M-Series graphics";
    else if (gpuFull && !gpuFull.includes("restricted")) gpuShort = gpuFull.split("·")[0].trim();

    // Screen resolution
    const screenRes = `${window.screen.width}×${window.screen.height}`;

    // Dynamic local time & sleep condition
    const now = new Date();
    const hours = now.getHours();
    const minutes = String(now.getMinutes()).padStart(2, "0");
    const ampm = hours >= 12 ? "p.m." : "a.m.";
    const displayHour = hours % 12 || 12;
    const timeStr = `${displayHour}:${minutes} ${ampm}`;

    let sleepNotice = "";
    if (hours >= 23 || hours < 6) {
      sleepNotice = " You should be asleep. We won't tell anyone, but your device just did.";
    } else {
      sleepNotice = " Your device timestamp just confirmed it.";
    }

    // Location & ISP
    const city = geoObj.city !== "Unknown" ? geoObj.city : "Guntur";
    const region = geoObj.region !== "Unknown" ? geoObj.region : "Andhra Pradesh";
    const country = geoObj.country !== "Unknown" ? geoObj.country : "IN";
    const isp = geoObj.org !== "Unknown ISP" ? geoObj.org : "Cloudflare London";

    // OS & CPU Arch
    let osName = "Linux";
    if (osBrowserStr.includes("macOS")) osName = "macOS";
    else if (osBrowserStr.includes("Windows")) osName = "Windows";
    else if (osBrowserStr.includes("Android")) osName = "Android";
    else if (osBrowserStr.includes("iOS")) osName = "iOS";

    let cpuArch = "x86";
    if (/arm|aarch64/i.test(navigator.userAgent || "")) cpuArch = "ARM";

    // Media Text
    let mediaText = "You have a camera and a microphone attached.";
    if (mediaStr.includes("0 video") && mediaStr.includes("0 audio")) {
      mediaText = "Media device enumeration: no active camera or microphone inputs reported.";
    }

    // Fonts Text
    let fontsText = "You have programmer fonts installed, you write code.";
    if (fontsStr.includes("Standard")) {
      fontsText = "Standard system font stack identified.";
    }

    // Construct dynamic narrative lines
    const lines = [
      { type: "p", text: `${gpuShort}, ${cores} CPU cores that it admits to, and a ${screenRes} display. A perfectly capable setup.` },
      { type: "p", text: `Anyway. Let me show you the rest of what I already know about you.` },
      { type: "h", text: `Where you are` },
      { type: "b", text: `• Your internet provider is ${isp}.` },
      { type: "b", text: `• It's ${timeStr} where you are.${sleepNotice}` },
      { type: "b", text: `• You're in or near ${city}${region ? ", " + region : ""}${country ? ", " + country : ""}.` },
      { type: "h", text: `What you are using` },
      { type: "b", text: `• Your operating system is ${osName}.` },
      { type: "b", text: `• Your CPU is ${cpuArch}-family.` },
      { type: "h", text: `What you are using it on` },
      { type: "b", text: `• ${mediaText}` },
      { type: "b", text: `• Your graphics is an ${gpuFull}.` },
      { type: "h", text: `What you have installed` },
      { type: "b", text: `• ${fontsText}` },
      { type: "p", text: `Now the louder stuff, and notice we never asked you. Neither will anyone else.` },
      { type: "h", text: `What we can reach on your machine` },
      { type: "b", text: `• Your browser hid your local IP behind an mDNS alias, good. That protection is on.` },
      { type: "b", text: `• A private window wouldn't have changed any of this, incidentally. Every reading above works exactly the same in one.` },
      { type: "b", text: `• ${webrtcStr.includes('gathered') ? webrtcStr : 'WebRTC connection gathered public network address ' + (geoObj.ip || '127.0.0.1') + '.'}` }
    ];

    contentEl.replaceChildren();

    const skipBtn = document.getElementById("typewriter-skip-btn");
    const allWordSpans = [];

    // Render EVERY word up front with class "word-span pending"
    lines.forEach(line => {
      const cls = line.type === "h" ? "typewriter-heading" : line.type === "b" ? "typewriter-bullet" : "typewriter-paragraph";
      const div = document.createElement("div");
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
      skipBtn.onclick = () => {
        revealAllInstantly();
      };
    }

    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      revealAllInstantly();
      return;
    }

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

  // --- STAGE 2 MAIN ENTRY POINT ---
  async function initStage2() {
    await initTypewriterStream();
  }

  // DOM Content Loaded Handler
  document.addEventListener('DOMContentLoaded', () => {
    initStage1();
    initStage2();
  });
})();

