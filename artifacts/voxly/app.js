/**
 * Voxly – Viral Shorts Generator
 * State Machine: idle → loading → results | error
 */

'use strict';

// ─── Constants ──────────────────────────────────────────────────────────────
// Local AI Clipper backend (start with start_backend.bat)
const BACKEND_URL = '/api/process';

const LOADING_MESSAGES = [
  'Connecting to AI engine...',
  'Fetching video metadata...',
  'Transcribing audio...',
  'Analyzing viral hooks...',
  'Scoring engagement moments...',
  'Identifying key highlights...',
  'Clipping best segments...',
  'Formatting to 9:16 vertical...',
  'Rendering your shorts...',
  'Almost there...',
];

const STEPS = [
  { id: 'step-1', label: 'Fetching video metadata', progress: 25 },
  { id: 'step-2', label: 'Analyzing viral hooks', progress: 50 },
  { id: 'step-3', label: 'Clipping & formatting', progress: 75 },
  { id: 'step-4', label: 'Rendering shorts', progress: 95 },
];

// ─── DOM Refs ────────────────────────────────────────────────────────────────
const screens = {
  input: document.getElementById('screen-input'),
  loading: document.getElementById('screen-loading'),
  results: document.getElementById('screen-results'),
  error: document.getElementById('screen-error'),
};

const urlInput = document.getElementById('youtube-url-input');
const generateBtn = document.getElementById('generate-btn');
const loadingMsg = document.getElementById('loading-message');
const progressBar = document.getElementById('progress-bar');
const resultsGallery = document.getElementById('results-gallery');
const resultsCount = document.getElementById('results-count');
const newVideoBtn = document.getElementById('new-video-btn');
const retryBtn = document.getElementById('retry-btn');
const errorMessage = document.getElementById('error-message');

// ─── App State ───────────────────────────────────────────────────────────────
let loadingTimer = null;
let messageInterval = null;
let stepIndex = 0;
let msgIndex = 0;
let savedUrl = '';
let clipsCount = null;  // null = Default (backend decides)

// ─── Screen Manager ──────────────────────────────────────────────────────────
function showScreen(name) {
  Object.values(screens).forEach(s => s.classList.remove('active'));
  const target = screens[name];
  if (target) {
    target.classList.add('active');
  }
}

// ─── Loading Animations ───────────────────────────────────────────────────────
function startLoadingAnimation() {
  // Reset
  progressBar.style.width = '0%';
  stepIndex = 0;
  msgIndex = 0;
  STEPS.forEach(s => {
    const el = document.getElementById(s.id);
    el.classList.remove('active', 'done');
  });

  // Rotate messages
  loadingMsg.textContent = LOADING_MESSAGES[0];
  messageInterval = setInterval(() => {
    msgIndex = (msgIndex + 1) % LOADING_MESSAGES.length;
    loadingMsg.style.opacity = '0';
    setTimeout(() => {
      loadingMsg.textContent = LOADING_MESSAGES[msgIndex];
      loadingMsg.style.opacity = '1';
    }, 250);
  }, 2200);

  // Advance steps
  advanceStep();
}

function advanceStep() {
  if (stepIndex >= STEPS.length) return;
  const step = STEPS[stepIndex];
  const stepEl = document.getElementById(step.id);

  // Mark previous as done
  if (stepIndex > 0) {
    const prevEl = document.getElementById(STEPS[stepIndex - 1].id);
    prevEl.classList.remove('active');
    prevEl.classList.add('done');
  }

  stepEl.classList.add('active');
  progressBar.style.width = step.progress + '%';

  stepIndex++;
  if (stepIndex < STEPS.length) {
    loadingTimer = setTimeout(advanceStep, 3500);
  }
}

function stopLoadingAnimation() {
  clearInterval(messageInterval);
  clearTimeout(loadingTimer);
  messageInterval = null;
  loadingTimer = null;
}

function completeAllSteps() {
  STEPS.forEach(s => {
    const el = document.getElementById(s.id);
    el.classList.remove('active');
    el.classList.add('done');
  });
  progressBar.style.width = '100%';
}

// ─── Backend Call (streaming NDJSON) ───────────────────────────────────────────
async function callBackend(youtubeUrl, { onTotal, onClip }) {
  const modeEl = document.querySelector('input[name="crop-mode"]:checked');
  const mode = modeEl ? modeEl.value : 'fill';
  const durationEl = document.querySelector('input[name="clip-duration"]:checked');
  const duration = durationEl ? parseInt(durationEl.value, 10) : 45;
  const captionsEl = document.querySelector('input[name="auto-captions"]:checked');
  const captions = captionsEl ? (captionsEl.value === 'true') : true;

  const geminiKeyEl = document.getElementById('gemini-key-input');
  const geminiKey = geminiKeyEl ? geminiKeyEl.value.trim() : '';

  const captionStyle = (typeof window.getSelectedCaptionStyle === 'function') ? window.getSelectedCaptionStyle() : 'mrbeast';

  // Segment 1 – source type + language
  const sourceType = document.querySelector('input[name="source-type"]:checked')?.value || 'youtube';
  const language = (typeof window.getSelectedLanguage === 'function') ? window.getSelectedLanguage() : 'english';

  // Segment 3 – audio enhance
  const audioEnhance = document.getElementById('audio-enhance-toggle')?.checked || false;

  // B-Roll AI
  const brollEnabled = document.getElementById('broll-toggle')?.checked || false;

  // Visual enhancements
  const colorGrade  = document.querySelector('#grade-pills .grade-pill.active')?.dataset.grade || 'none';
  const autoZoom    = document.getElementById('auto-zoom-toggle')?.checked   || false;
  const emojiBurst  = document.getElementById('emoji-burst-toggle')?.checked || false;
  const faceFocus   = document.getElementById('face-focus-toggle')?.checked  || false;
  const speedRamp   = document.getElementById('speed-ramp-toggle')?.checked  || false;
  const logoConfig  = window._logoFilename ? {
    filename: window._logoFilename,
    corner:   document.querySelector('#corner-pills .corner-pill.active')?.dataset.corner || 'br',
    size:     document.querySelector('#size-pills .size-pill.active')?.dataset.size || 'medium',
    opacity:  (parseInt(document.getElementById('logo-opacity')?.value || '80') / 100).toFixed(2),
  } : null;

  // Segment 5 – custom style
  const customStyle = (typeof window.getCustomStyle === 'function') ? window.getCustomStyle() : null;

  const payload = {
    youtubeUrl: sourceType === 'youtube' ? youtubeUrl : '',
    sourceType,
    mode, duration, captions, captionStyle, language, audioEnhance, brollEnabled,
    colorGrade, autoZoom, emojiBurst, faceFocus, speedRamp,
  };
  if (logoConfig) payload.logoConfig = logoConfig;
  if (sourceType === 'upload') payload.uploadFile = window._uploadedFilename || '';
  if (customStyle) payload.customStyle = customStyle;
  if (clipsCount !== null) payload.clips = clipsCount;
  if (geminiKey) payload.geminiKey = geminiKey;

  let response;
  try {
    response = await fetch(BACKEND_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  } catch {
    throw new Error(
      'Cannot reach the local backend. Make sure start_backend.bat is running on port 5000.'
    );
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop(); // keep any incomplete trailing chunk

    for (const line of lines) {
      if (!line.trim()) continue;
      let msg;
      try { msg = JSON.parse(line); } catch { continue; }

      if (msg.error) throw new Error(msg.error);
      if (msg.total !== undefined) await onTotal(msg.total);
      if (msg.clip !== undefined) await onClip(msg.clip, msg.index, msg.hooks, msg.hasSrt, msg.hasRawAudio, msg.hasAlpha, msg.viralScore ?? null, msg.brollCount ?? 0, msg.hasThumbnail ?? false);
      if (msg.thumbReady) {
        const card = document.querySelector(`[data-clip-index="${msg.index}"]`);
        if (card) {
          const video = card.querySelector('video');
          const thumbUrl = video?.src?.replace('.mp4', '_thumb.jpg');
          if (video && thumbUrl) video.setAttribute('poster', thumbUrl);
          const btn = card.querySelector('.thumb-dl-btn');
          if (btn) btn.style.display = '';
        }
      }
      // msg.warning is silently ignored (non-fatal)
    }
  }
}

// ─── Gallery Rendering ────────────────────────────────────────────────────────
function renderGallery(videoUrls) {
  resultsGallery.innerHTML = '';
  resultsCount.textContent = videoUrls.length;

  videoUrls.forEach((url, i) => {
    const card = createVideoCard(url, i + 1);
    resultsGallery.appendChild(card);
  });
}

function createVideoCard(url, index, hooks = [], hasSrt = false, hasRawAudio = false, hasAlpha = false, viralScore = null, brollCount = 0, hasThumbnail = false) {
  const card = document.createElement('article');
  card.className = 'video-card';
  card.style.animationDelay = `${(index - 1) * 0.08}s`;
  card.setAttribute('role', 'listitem');
  card.setAttribute('data-clip-index', index - 1);

  const thumbUrl = url.replace('.mp4', '_thumb.jpg');

  const videoWrapper = document.createElement('div');
  videoWrapper.className = 'video-wrapper';

  const video = document.createElement('video');
  video.src = url;
  video.controls = true;
  video.setAttribute('preload', 'metadata');
  video.setAttribute('playsinline', '');
  video.setAttribute('aria-label', `Generated Short #${index}`);
  if (hasThumbnail) video.setAttribute('poster', thumbUrl);

  videoWrapper.appendChild(video);

  // ── Viral Score Badge ────────────────────────────────────────────────────
  if (viralScore !== null) {
    const scoreColor = viralScore >= 8 ? '#22c55e' : viralScore >= 6 ? '#f59e0b' : '#ef4444';
    const icon = viralScore >= 8 ? '🔥' : viralScore >= 6 ? '⚡' : '📈';
    const badge = document.createElement('div');
    badge.className = 'viral-score-badge';
    badge.style.cssText = `--score-color:${scoreColor};border-color:${scoreColor};color:${scoreColor};`;
    badge.innerHTML = `${icon} <strong>${viralScore}</strong><span style="opacity:.75">/10</span>`;
    badge.title = `Viral potential score: ${viralScore}/10`;
    videoWrapper.appendChild(badge);
  }

  // ── B-Roll Count Badge ───────────────────────────────────────────────────
  if (brollCount > 0) {
    const brBadge = document.createElement('div');
    brBadge.className = 'broll-count-badge';
    brBadge.innerHTML = `🎬 ${brollCount} B-Roll${brollCount > 1 ? 's' : ''}`;
    brBadge.title = `${brollCount} AI-generated B-roll${brollCount > 1 ? 's' : ''} spliced in`;
    videoWrapper.appendChild(brBadge);
  }

  const footer = document.createElement('div');
  footer.className = 'video-card-footer';

  const label = document.createElement('p');
  label.className = 'video-card-label';
  label.textContent = `Short #${index}`;

  const downloadBtn = document.createElement('button');
  downloadBtn.className = 'btn-download';
  downloadBtn.setAttribute('aria-label', `Download Short #${index}`);
  downloadBtn.innerHTML = `
    <svg class="dl-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/>
      <polyline points="7 10 12 15 17 10"/>
      <line x1="12" y1="15" x2="12" y2="3"/>
    </svg>
    <span class="dl-label">Download</span>`;

  downloadBtn.addEventListener('click', async () => {
    if (downloadBtn.disabled) return;
    downloadBtn.disabled = true;
    downloadBtn.querySelector('.dl-label').textContent = 'Downloading…';
    try {
      const res = await fetch(url);
      const blob = await res.blob();
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = blobUrl;
      a.download = `viral-short-${index}.mp4`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(blobUrl), 10000);
    } catch (err) {
      console.error('Download failed:', err);
      alert('Download failed. Please try right-clicking the video and saving it.');
    }
    downloadBtn.disabled = false;
    downloadBtn.querySelector('.dl-label').textContent = 'Download';
  });

  footer.appendChild(label);
  footer.appendChild(downloadBtn);

  // Thumbnail download button — hidden until thumbReady event arrives
  const thumbBtn = document.createElement('button');
  thumbBtn.className = 'btn-download thumb-dl-btn';
  thumbBtn.title = 'Download AI-generated thumbnail JPG for YouTube/TikTok upload';
  thumbBtn.setAttribute('aria-label', `Download thumbnail for Short #${index}`);
  thumbBtn.style.display = hasThumbnail ? '' : 'none';
  thumbBtn.innerHTML = `
    <svg class="dl-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
      <rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/>
      <polyline points="21 15 16 10 5 21"/>
    </svg>
    <span class="dl-label">Thumbnail</span>`;
  thumbBtn.addEventListener('click', async () => {
    if (thumbBtn.disabled) return;
    thumbBtn.disabled = true;
    thumbBtn.querySelector('.dl-label').textContent = 'Saving…';
    try {
      const res = await fetch(thumbUrl);
      const blob = await res.blob();
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = blobUrl;
      a.download = `thumbnail-short-${index}.jpg`;
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(blobUrl), 10000);
    } catch (err) {
      alert('Thumbnail download failed: ' + err.message);
    }
    thumbBtn.disabled = false;
    thumbBtn.querySelector('.dl-label').textContent = 'Thumbnail';
  });
  footer.appendChild(thumbBtn);

  // ── Smart 4K Thumbnail Generator ─────────────────────────────────────────
  const smart4kBtn = document.createElement('button');
  smart4kBtn.className = 'btn-download btn-thumb4k';
  smart4kBtn.title = 'Analyse this clip and generate a 4K AI thumbnail (1920×1080)';
  smart4kBtn.setAttribute('aria-label', `Generate 4K thumbnail for Short #${index}`);
  smart4kBtn.innerHTML = `
    <svg class="dl-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
      <rect x="3" y="3" width="18" height="18" rx="2"/>
      <circle cx="8.5" cy="8.5" r="1.5"/>
      <path d="M21 15l-5-5L5 21"/>
      <path d="M14 3h7v7"/>
    </svg>
    <span class="dl-label">4K Thumbnail</span>`;

  // Panel that shows the generated thumbnail preview + download
  const thumb4kPanel = document.createElement('div');
  thumb4kPanel.className = 'thumb4k-panel';
  thumb4kPanel.style.display = 'none';

  const clipFilename = url.split('/').pop();

  smart4kBtn.addEventListener('click', async () => {
    if (smart4kBtn.disabled) return;

    // If panel already has a result, toggle it
    if (thumb4kPanel.dataset.ready === 'true') {
      thumb4kPanel.style.display = thumb4kPanel.style.display === 'none' ? '' : 'none';
      return;
    }

    smart4kBtn.disabled = true;
    const label = smart4kBtn.querySelector('.dl-label');

    const steps = ['Analysing video…', 'Detecting scenes…', 'Generating AI image…', 'Upscaling to 4K…'];
    let si = 0;
    label.textContent = steps[si];
    const ticker = setInterval(() => {
      si = (si + 1) % steps.length;
      label.textContent = steps[si];
    }, 3500);

    try {
      const res = await fetch(`/api/smart-thumbnail/${clipFilename}`);
      const data = await res.json();
      clearInterval(ticker);

      if (data.error) throw new Error(data.error);

      // Build preview panel
      thumb4kPanel.innerHTML = '';

      const previewImg = document.createElement('img');
      previewImg.src = data.url + '?t=' + Date.now();
      previewImg.className = 'thumb4k-preview';
      previewImg.alt = 'AI-generated 4K thumbnail';

      const actions = document.createElement('div');
      actions.className = 'thumb4k-actions';

      const dlBtn = document.createElement('button');
      dlBtn.className = 'btn-download';
      dlBtn.innerHTML = `
        <svg class="dl-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/>
          <polyline points="7 10 12 15 17 10"/>
          <line x1="12" y1="15" x2="12" y2="3"/>
        </svg>
        <span class="dl-label">Download 1920×1080</span>`;
      dlBtn.addEventListener('click', async () => {
        dlBtn.disabled = true;
        dlBtn.querySelector('.dl-label').textContent = 'Saving…';
        try {
          const r2 = await fetch(data.url);
          const blob = await r2.blob();
          const a = document.createElement('a');
          a.href = URL.createObjectURL(blob);
          a.download = `thumbnail-4k-short-${index}.jpg`;
          document.body.appendChild(a); a.click(); document.body.removeChild(a);
          setTimeout(() => URL.revokeObjectURL(a.href), 10000);
        } catch(e) { alert('Download failed: ' + e.message); }
        dlBtn.disabled = false;
        dlBtn.querySelector('.dl-label').textContent = 'Download 1920×1080';
      });

      const regenBtn = document.createElement('button');
      regenBtn.className = 'btn-download';
      regenBtn.innerHTML = `
        <svg class="dl-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="23 4 23 10 17 10"/>
          <path d="M20.49 15a9 9 0 11-2.12-9.36L23 10"/>
        </svg>
        <span class="dl-label">Regenerate</span>`;
      regenBtn.addEventListener('click', () => {
        // Clear cache flag so next click re-generates
        thumb4kPanel.dataset.ready = 'false';
        thumb4kPanel.style.display = 'none';
        smart4kBtn.disabled = false;
        smart4kBtn.querySelector('.dl-label').textContent = '4K Thumbnail';
      });

      const sizeTag = document.createElement('span');
      sizeTag.className = 'thumb4k-sizetag';
      sizeTag.textContent = '1920 × 1080 · AI Generated';

      actions.appendChild(sizeTag);
      actions.appendChild(dlBtn);
      actions.appendChild(regenBtn);

      thumb4kPanel.appendChild(previewImg);
      thumb4kPanel.appendChild(actions);
      thumb4kPanel.dataset.ready = 'true';
      thumb4kPanel.style.display = '';

      label.textContent = '4K Thumbnail ✓';
      smart4kBtn.disabled = false;

    } catch (err) {
      clearInterval(ticker);
      label.textContent = '4K Thumbnail';
      smart4kBtn.disabled = false;
      alert('Thumbnail generation failed: ' + err.message);
    }
  });

  footer.appendChild(smart4kBtn);

  // ── Clip Trimmer ──────────────────────────────────────────────────────────
  const trimBtn = document.createElement('button');
  trimBtn.className = 'btn-download';
  trimBtn.title = 'Trim this clip before downloading';
  trimBtn.innerHTML = `
    <svg class="dl-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/>
      <line x1="20" y1="4" x2="8.12" y2="15.88"/><line x1="14.47" y1="14.48" x2="20" y2="20"/>
      <line x1="8.12" y1="8.12" x2="12" y2="12"/>
    </svg>
    <span class="dl-label">Trim</span>`;

  const trimPanel = document.createElement('div');
  trimPanel.className = 'trim-panel';
  trimPanel.style.display = 'none';
  trimPanel.innerHTML = `
    <div class="trim-track">
      <div class="trim-fill" id="trim-fill-${index}"></div>
      <input type="range" class="trim-range trim-start-range" id="trim-s-${index}" min="0" max="100" step="0.1" value="0">
      <input type="range" class="trim-range trim-end-range"   id="trim-e-${index}" min="0" max="100" step="0.1" value="100">
    </div>
    <div class="trim-labels">
      <span id="trim-sl-${index}">0:00.0</span>
      <span id="trim-el-${index}">—:——</span>
    </div>
    <button class="btn-trim-apply" id="trim-apply-${index}">✂️ Trim &amp; Download</button>`;

  const fillEl   = () => trimPanel.querySelector(`#trim-fill-${index}`);
  const startEl  = () => trimPanel.querySelector(`#trim-s-${index}`);
  const endEl    = () => trimPanel.querySelector(`#trim-e-${index}`);
  const startLbl = () => trimPanel.querySelector(`#trim-sl-${index}`);
  const endLbl   = () => trimPanel.querySelector(`#trim-el-${index}`);
  const applyBtn = () => trimPanel.querySelector(`#trim-apply-${index}`);

  function fmtT(sec) {
    const m = Math.floor(sec / 60);
    const s = (sec % 60).toFixed(1).padStart(4, '0');
    return `${m}:${s}`;
  }
  function syncTrim() {
    const dur = video.duration || 100;
    let sv = parseFloat(startEl().value), ev = parseFloat(endEl().value);
    if (sv >= ev - 0.2) { if (document.activeElement === startEl()) sv = ev - 0.2; else ev = sv + 0.2; }
    startEl().value = sv; endEl().value = ev;
    startLbl().textContent = fmtT((sv / 100) * dur);
    endLbl().textContent   = fmtT((ev / 100) * dur);
    fillEl().style.left  = sv + '%';
    fillEl().style.width = (ev - sv) + '%';
  }

  video.addEventListener('loadedmetadata', () => {
    endLbl().textContent = fmtT(video.duration);
    syncTrim();
  });
  trimPanel.addEventListener('input', syncTrim);

  trimBtn.addEventListener('click', () => {
    const open = trimPanel.style.display !== 'none';
    trimPanel.style.display = open ? 'none' : 'block';
    trimBtn.querySelector('.dl-label').textContent = open ? 'Trim' : 'Close';
    if (!open) syncTrim();
  });

  applyBtn()?.addEventListener?.('click', () => {});  // placeholder until DOM ready
  trimPanel.addEventListener('click', async (ev) => {
    const btn = ev.target.closest('.btn-trim-apply');
    if (!btn || btn.disabled) return;
    const dur = video.duration || 100;
    const tS  = ((parseFloat(startEl().value) / 100) * dur).toFixed(3);
    const tE  = ((parseFloat(endEl().value)   / 100) * dur).toFixed(3);
    const fn  = url.split('/').pop();
    btn.disabled = true; btn.textContent = '⏳ Trimming…';
    try {
      const res = await fetch(`/api/trim-clip/${fn}?start=${tS}&end=${tE}`);
      if (!res.ok) { const d = await res.json(); throw new Error(d.error || 'Trim failed'); }
      const blob = await res.blob();
      const bUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = bUrl; a.download = `trimmed-short-${index}.mp4`;
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(bUrl), 15000);
    } catch (err) { alert('Trim failed: ' + err.message); }
    btn.disabled = false; btn.textContent = '✂️ Trim & Download';
  });

  footer.appendChild(trimBtn);
  card.appendChild(trimPanel);

  // Segment 2 – SRT Export button
  if (hasSrt) {
    const srtBtn = createSrtButton(url);
    footer.appendChild(srtBtn);
  }

  // Feature: Translate SRT (multi-language)
  if (hasSrt) {
    const LANGS = [
      { code: 'en', flag: '🇺🇸', label: 'English'    },
      { code: 'es', flag: '🇪🇸', label: 'Spanish'    },
      { code: 'fr', flag: '🇫🇷', label: 'French'     },
      { code: 'pt', flag: '🇵🇹', label: 'Portuguese' },
      { code: 'de', flag: '🇩🇪', label: 'German'     },
      { code: 'ar', flag: '🇸🇦', label: 'Arabic'     },
      { code: 'hi', flag: '🇮🇳', label: 'Hindi'      },
      { code: 'ja', flag: '🇯🇵', label: 'Japanese'   },
    ];

    const transToggleBtn = document.createElement('button');
    transToggleBtn.className = 'btn-download';
    transToggleBtn.title = 'Translate subtitles to another language';
    transToggleBtn.innerHTML = `
      <svg class="dl-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M5 8l6 6M4 14l6-6 2-2M2 5h12M7 2h1M22 22l-5-10-5 10M14 18h6"/>
      </svg>
      <span class="dl-label">Translate</span>`;

    const transPanel = document.createElement('div');
    transPanel.className = 'translate-panel';
    transPanel.style.display = 'none';
    transPanel.innerHTML = `<p class="trans-hint">Download subtitles translated to:</p>
      <div class="trans-lang-grid">${
        LANGS.map(l => `<button class="trans-lang-btn" data-code="${l.code}" data-label="${l.label}">${l.flag} ${l.label}</button>`).join('')
      }</div>`;

    transPanel.addEventListener('click', async (ev) => {
      const btn = ev.target.closest('.trans-lang-btn');
      if (!btn || btn.disabled) return;
      const code  = btn.dataset.code;
      const label = btn.dataset.label;
      btn.disabled = true;
      btn.textContent = '⏳ …';
      const filename = url.split('/').pop();
      try {
        const res = await fetch(`/api/translate-srt/${filename}?lang=${code}`);
        if (!res.ok) { const d = await res.json(); throw new Error(d.error || 'Translation failed'); }
        const blob = await res.blob();
        const blobUrl = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = blobUrl;
        a.download = filename.replace('.mp4', `_${code}.srt`);
        document.body.appendChild(a); a.click(); document.body.removeChild(a);
        setTimeout(() => URL.revokeObjectURL(blobUrl), 10000);
      } catch (err) { alert(`Translation to ${label} failed: ` + err.message); }
      btn.disabled = false;
      btn.textContent = `${LANGS.find(l => l.code === code)?.flag} ${label}`;
    });

    transToggleBtn.addEventListener('click', () => {
      const open = transPanel.style.display !== 'none';
      transPanel.style.display = open ? 'none' : 'block';
      transToggleBtn.querySelector('.dl-label').textContent = open ? 'Translate' : 'Close';
    });

    footer.appendChild(transToggleBtn);
    card.appendChild(transPanel);
  }

  // Feature: Alpha Channel Export (NLE overlay)
  if (hasAlpha) {
    const alphaBtn = document.createElement('button');
    alphaBtn.className = 'btn-download btn-alpha';
    alphaBtn.title = 'Export caption-only transparent WebM for NLE overlay (Premiere, DaVinci, etc.)';
    alphaBtn.innerHTML = `
      <svg class="dl-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/>
      </svg>
      <span class="dl-label">Alpha</span>`;
    alphaBtn.addEventListener('click', async () => {
      if (alphaBtn.disabled) return;
      alphaBtn.disabled = true;
      alphaBtn.querySelector('.dl-label').textContent = 'Rendering…';
      try {
        const filename = url.split('/').pop();
        const res = await fetch(`/api/alpha-export/${filename}`);
        if (!res.ok) { const d = await res.json(); throw new Error(d.error || 'Alpha export failed'); }
        const blob = await res.blob();
        const blobUrl = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = blobUrl;
        a.download = filename.replace('.mp4', '_alpha_captions.webm');
        document.body.appendChild(a); a.click(); document.body.removeChild(a);
        setTimeout(() => URL.revokeObjectURL(blobUrl), 30000);
      } catch (err) { alert('Alpha export failed: ' + err.message); }
      alphaBtn.disabled = false;
      alphaBtn.querySelector('.dl-label').textContent = 'Alpha';
    });
    footer.appendChild(alphaBtn);
  }

  // Segment 4 – Edit Captions button
  const captionStyle = (typeof window.getSelectedCaptionStyle === 'function') ? window.getSelectedCaptionStyle() : 'mrbeast';
  const editBtn = createEditCaptionsButton(url, captionStyle);
  footer.appendChild(editBtn);

  card.appendChild(videoWrapper);

  // Feature: Before/After Audio Comparison (shown when audio enhancement was used)
  if (hasRawAudio) {
    const audioCompare = document.createElement('div');
    audioCompare.className = 'audio-compare-section';
    audioCompare.innerHTML = `
      <div class="audio-compare-header">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v4M8 23h8"/></svg>
        Audio Enhancement Preview
      </div>
      <div class="audio-compare-toggle">
        <button class="audio-tab active" data-mode="enhanced">✦ Enhanced</button>
        <button class="audio-tab" data-mode="raw">Raw</button>
      </div>
      <audio class="audio-compare-player" controls preload="none"></audio>`;
    const filename = url.split('/').pop();
    const tabs = audioCompare.querySelectorAll('.audio-tab');
    const player = audioCompare.querySelector('.audio-compare-player');

    // Set initial to enhanced (extract audio from video URL)
    player.src = url + '#t=0';

    tabs.forEach(tab => {
      tab.addEventListener('click', () => {
        tabs.forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        const wasPlaying = !player.paused;
        const currentTime = player.currentTime;
        if (tab.dataset.mode === 'raw') {
          player.src = `/api/audio-raw/${filename}`;
        } else {
          player.src = url;
        }
        player.load();
        player.currentTime = currentTime;
        if (wasPlaying) player.play().catch(() => {});
      });
    });

    card.appendChild(audioCompare);
  }

  // If we have AI hooks returned, append them below the video
  if (hooks && hooks.length > 0) {
    const hooksContainer = document.createElement('div');
    hooksContainer.className = 'viral-hooks-container';

    const hooksTitle = document.createElement('div');
    hooksTitle.className = 'hooks-title';
    hooksTitle.innerHTML = `
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
        <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2v10z"></path>
      </svg>
      AI Viral Hooks
      <span class="hooks-hint">click to copy · 🔥 to burn onto clip</span>
    `;
    hooksContainer.appendChild(hooksTitle);

    const hooksList = document.createElement('ul');
    hooksList.className = 'hooks-list';
    hooks.forEach(hookText => {
      const li = document.createElement('li');
      li.className = 'hook-item';

      const hookSpan = document.createElement('span');
      hookSpan.className = 'hook-text';
      hookSpan.textContent = hookText;
      hookSpan.title = 'Click to copy';
      hookSpan.addEventListener('click', () => {
        navigator.clipboard.writeText(hookText);
        const orig = hookSpan.textContent;
        hookSpan.textContent = 'Copied!';
        hookSpan.style.color = 'var(--purple-400, #a78bfa)';
        setTimeout(() => { hookSpan.textContent = orig; hookSpan.style.color = ''; }, 1500);
      });

      const burnBtn = document.createElement('button');
      burnBtn.className = 'btn-burn-hook';
      burnBtn.title = 'Burn this hook text onto the top of the clip';
      burnBtn.textContent = '🔥';
      burnBtn.addEventListener('click', async () => {
        if (burnBtn.disabled) return;
        burnBtn.disabled = true;
        burnBtn.textContent = '⏳';
        const filename = url.split('/').pop();
        try {
          const res = await fetch(`/api/burn-hook/${filename}?text=${encodeURIComponent(hookText)}`);
          if (!res.ok) { const d = await res.json(); throw new Error(d.error || 'Burn failed'); }
          const blob = await res.blob();
          const bUrl = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = bUrl; a.download = `hooked-short-${index + 1}.mp4`;
          document.body.appendChild(a); a.click(); document.body.removeChild(a);
          setTimeout(() => URL.revokeObjectURL(bUrl), 15000);
          burnBtn.textContent = '✅';
          setTimeout(() => { burnBtn.textContent = '🔥'; burnBtn.disabled = false; }, 2000);
          return;
        } catch (err) { alert('Burn failed: ' + err.message); }
        burnBtn.disabled = false;
        burnBtn.textContent = '🔥';
      });

      li.appendChild(hookSpan);
      li.appendChild(burnBtn);
      hooksList.appendChild(li);
    });

    hooksContainer.appendChild(hooksList);
    card.appendChild(hooksContainer);
  }

  // ── Chapters button ────────────────────────────────────────────────────────
  const chaptersBtn = document.createElement('button');
  chaptersBtn.className = 'btn-download';
  chaptersBtn.title = 'Auto-detect scene cuts and label chapters';
  chaptersBtn.innerHTML = `
    <svg class="dl-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
      <line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/>
      <line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/>
      <line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>
    </svg>
    <span class="dl-label">Chapters</span>`;

  const chaptersPanel = document.createElement('div');
  chaptersPanel.className = 'chapters-panel';
  chaptersPanel.style.display = 'none';

  chaptersBtn.addEventListener('click', async () => {
    const open = chaptersPanel.style.display !== 'none';
    if (open) {
      chaptersPanel.style.display = 'none';
      chaptersBtn.querySelector('.dl-label').textContent = 'Chapters';
      return;
    }
    chaptersBtn.querySelector('.dl-label').textContent = 'Detecting…';
    chaptersBtn.disabled = true;
    const filename = url.split('/').pop();
    try {
      const res = await fetch(`/api/chapters/${filename}`);
      if (!res.ok) { const d = await res.json(); throw new Error(d.error || 'Chapter detection failed'); }
      const data = await res.json();
      const chapters = data.chapters || [];
      chaptersPanel.innerHTML = '';
      if (chapters.length === 0) {
        chaptersPanel.innerHTML = '<p class="chapters-empty">No distinct scene cuts detected.</p>';
      } else {
        const list = document.createElement('ul');
        list.className = 'chapters-list';
        chapters.forEach(ch => {
          const item = document.createElement('li');
          item.className = 'chapter-item';
          const mins = Math.floor(ch.time / 60);
          const secs = (ch.time % 60).toFixed(1).padStart(4, '0');
          item.innerHTML = `<span class="chapter-ts">${mins}:${secs}</span><span class="chapter-label">${ch.label}</span>`;
          item.addEventListener('click', () => { video.currentTime = ch.time; video.play().catch(() => {}); });
          list.appendChild(item);
        });
        chaptersPanel.appendChild(list);
      }
      chaptersPanel.style.display = 'block';
      chaptersBtn.querySelector('.dl-label').textContent = 'Close';
    } catch (err) {
      alert('Chapters failed: ' + err.message);
      chaptersBtn.querySelector('.dl-label').textContent = 'Chapters';
    }
    chaptersBtn.disabled = false;
  });

  footer.appendChild(chaptersBtn);
  card.appendChild(chaptersPanel);
  card.appendChild(thumb4kPanel);

  card.appendChild(footer);

  return card;
}

// ─── Placeholder card (shown while clip is encoding) ──────────────────────────
function createPlaceholderCard(index) {
  const card = document.createElement('article');
  card.className = 'video-card video-card-placeholder';
  card.dataset.cardIndex = index;
  card.setAttribute('role', 'listitem');
  card.style.animationDelay = `${index * 0.07}s`;

  const wrapper = document.createElement('div');
  wrapper.className = 'video-wrapper';
  wrapper.innerHTML = `
    <div class="placeholder-inner">
      <div class="placeholder-spinner"></div>
      <span class="placeholder-label">PROCESSING...</span>
    </div>`;

  const footer = document.createElement('div');
  footer.className = 'video-card-footer';
  footer.innerHTML = `
    <p class="video-card-label" style="opacity:0.35">Short #${index + 1}</p>
    <div class="btn-download-ghost"></div>`;

  card.appendChild(wrapper);
  card.appendChild(footer);
  return card;
}

// ─── Validation ───────────────────────────────────────────────────────────────
function isValidYouTubeUrl(url) {
  try {
    const u = new URL(url.trim());
    return (
      (u.hostname === 'www.youtube.com' || u.hostname === 'youtube.com') && u.searchParams.has('v') ||
      u.hostname === 'youtu.be' && u.pathname.length > 1 ||
      u.hostname === 'www.youtube.com' && u.pathname.startsWith('/shorts/')
    );
  } catch {
    return false;
  }
}

// ─── Results badge ─────────────────────────────────────────────────────────────
function showResultsBadge(visible) {
  const badge = document.getElementById('results-loading-badge');
  if (badge) badge.style.display = visible ? 'flex' : 'none';
}

// ─── Main Generate Flow ───────────────────────────────────────────────────────────
async function handleGenerate() {
  const sourceType = document.querySelector('input[name="source-type"]:checked')?.value || 'youtube';
  const rawUrl = (sourceType === 'youtube') ? urlInput.value.trim() : '';

  if (sourceType === 'youtube') {
    if (!rawUrl) { shakeInput(); return; }
    if (!isValidYouTubeUrl(rawUrl)) {
      shakeInput();
      showInputError('Please enter a valid YouTube URL.');
      return;
    }
  } else {
    // Upload mode
    if (!window._uploadedFilename) {
      const dropZone = document.getElementById('upload-drop-zone');
      if (dropZone) { dropZone.style.borderColor = 'rgba(239,68,68,0.7)'; setTimeout(() => dropZone.style.borderColor = '', 2000); }
      return;
    }
  }

  clearInputError();
  clearVideoPreview();
  savedUrl = rawUrl;
  urlInput.disabled = true;
  generateBtn.disabled = true;

  showScreen('loading');
  startLoadingAnimation();

  let totalClips = 0;
  let receivedClips = 0;

  try {
    await callBackend(rawUrl, {
      async onTotal(n) {
        totalClips = n;
        stopLoadingAnimation();
        completeAllSteps();
        await delay(300);
        resultsGallery.innerHTML = '';
        resultsCount.textContent = '0';
        showScreen('results');
        showResultsBadge(true);
        for (let i = 0; i < n; i++) {
          resultsGallery.appendChild(createPlaceholderCard(i));
        }
      },
      async onClip(url, index, hooks, hasSrt, hasRawAudio, hasAlpha, viralScore, brollCount, hasThumbnail) {
        receivedClips++;
        const placeholder = resultsGallery.querySelector(`[data-card-index="${index}"]`);
        const realCard = createVideoCard(url, index + 1, hooks, hasSrt, hasRawAudio, hasAlpha, viralScore ?? null, brollCount ?? 0, hasThumbnail ?? false);
        realCard.style.animationDuration = '0.3s';
        if (placeholder) {
          resultsGallery.replaceChild(realCard, placeholder);
        } else {
          resultsGallery.appendChild(realCard);
        }
        resultsCount.textContent = receivedClips;
        if (receivedClips >= totalClips) showResultsBadge(false);
      },
    });

    if (totalClips === 0) {
      throw new Error('No shorts were generated. Please try a different video.');
    }
    showResultsBadge(false);

    // ── Record into Analytics + History ──────────────────────────────────
    incrementStats(totalClips);

    let thumbUrl = null;
    try {
      const u = new URL(rawUrl);
      let vid = u.searchParams.get('v');
      if (!vid && u.pathname.startsWith('/shorts/')) vid = u.pathname.split('/')[2];
      if (!vid && u.hostname === 'youtu.be') vid = u.pathname.slice(1);
      if (vid) thumbUrl = `https://img.youtube.com/vi/${vid}/mqdefault.jpg`;
    } catch { }

    addHistoryEntry(rawUrl, totalClips, thumbUrl);

  } catch (err) {
    stopLoadingAnimation();
    console.error('[ClipperApp] Error:', err);
    errorMessage.textContent = err.message || 'An unexpected error occurred.';
    showScreen('error');
  }
}

// ─── Input helpers ────────────────────────────────────────────────────────────
function shakeInput() {
  const wrapper = urlInput.closest('.input-wrapper');
  wrapper.style.animation = 'none';
  wrapper.offsetHeight;
  wrapper.style.animation = 'shake 0.4s ease';
  wrapper.addEventListener('animationend', () => {
    wrapper.style.animation = '';
  }, { once: true });
}

function showInputError(msg) {
  let errEl = document.getElementById('input-error');
  if (!errEl) {
    errEl = document.createElement('p');
    errEl.id = 'input-error';
    errEl.style.cssText = 'font-size:0.8rem;color:#F87171;margin-top:-0.25rem;padding-left:0.25rem;';
    urlInput.closest('.input-card').insertBefore(errEl, document.querySelector('.btn-generate'));
  }
  errEl.textContent = msg;
}

function clearInputError() {
  const errEl = document.getElementById('input-error');
  if (errEl) errEl.remove();
}

// ─── Utility ──────────────────────────────────────────────────────────────────
function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// ─── Reset to Input Screen ────────────────────────────────────────────────────
function resetToInput() {
  urlInput.disabled = false;
  generateBtn.disabled = false;
  urlInput.value = '';
  clearInputError();
  clearVideoPreview();
  showScreen('input');
  urlInput.focus();
}

// ─── Shake Keyframe ───────────────────────────────────────────────────────────
(function injectShakeKeyframe() {
  const style = document.createElement('style');
  style.textContent = `
    @keyframes shake {
      0%,100% { transform: translateX(0); }
      20%      { transform: translateX(-6px); }
      40%      { transform: translateX(6px); }
      60%      { transform: translateX(-4px); }
      80%      { transform: translateX(4px); }
    }
  `;
  document.head.appendChild(style);
})();


// Video ID extractor
function extractVideoId(url) {
  try {
    const u = new URL(url.trim());
    if (u.hostname === 'youtu.be') return u.pathname.slice(1).split('?')[0];
    if (u.hostname === 'www.youtube.com' || u.hostname === 'youtube.com') {
      if (u.pathname.startsWith('/shorts/')) return u.pathname.split('/')[2];
      return u.searchParams.get('v');
    }
  } catch {}
  return null;
}

// Video Preview Card
let previewDebounceTimer = null;

function clearVideoPreview() {
  const card = document.getElementById('video-preview-card');
  if (card) card.remove();
}

async function fetchVideoPreview(url) {
  clearVideoPreview();
  if (!isValidYouTubeUrl(url)) return;
  const vid = extractVideoId(url);
  if (!vid) return;

  const inputCard = urlInput.closest('.input-card');
  const optionsGrid = inputCard.querySelector('.options-grid');
  const skeleton = document.createElement('div');
  skeleton.id = 'video-preview-card';
  skeleton.className = 'video-preview-card video-preview-loading';
  skeleton.innerHTML = '<div class="vp-thumb-wrap"><div class="vp-thumb-skeleton"></div></div>'
    + '<div class="vp-info"><div class="vp-skeleton-line" style="width:70%"></div>'
    + '<div class="vp-skeleton-line" style="width:45%;margin-top:6px"></div></div>';
  inputCard.insertBefore(skeleton, optionsGrid);

  try {
    const res = await fetch('/api/video-preview?v=' + encodeURIComponent(vid));
    const data = await res.json();
    if (data.error) { clearVideoPreview(); return; }

    const card = document.getElementById('video-preview-card');
    if (!card) return;

    const fmtDur = d => d ? Math.floor(d/60) + ':' + String(d%60).padStart(2,'0') : '';
    const fmtViews = v => {
      if (!v) return '';
      if (v >= 1e6) return (v/1e6).toFixed(1) + 'M views';
      if (v >= 1e3) return (v/1e3).toFixed(0) + 'K views';
      return v + ' views';
    };
    const speedBadge = data.hasTranscript
      ? '<span class="vp-badge vp-badge-instant">Instant Detection</span>'
      : '<span class="vp-badge vp-badge-whisper">Whisper Analysis</span>';

    let html = '<div class="vp-thumb-wrap"><img class="vp-thumb" src="' + data.thumbnail + '" alt="thumb" loading="lazy" />';
    if (data.duration) html += '<span class="vp-duration">' + fmtDur(data.duration) + '</span>';
    html += '</div><div class="vp-info"><div class="vp-title">' + (data.title || 'YouTube Video') + '</div><div class="vp-meta">';
    if (data.channel) html += '<span class="vp-channel">' + data.channel + '</span>';
    if (data.views) html += '<span class="vp-views">' + fmtViews(data.views) + '</span>';
    html += '</div>' + speedBadge + '</div>';

    card.className = 'video-preview-card';
    card.innerHTML = html;
  } catch (e) {
    clearVideoPreview();
  }
}

// ─── Event Listeners ──────────────────────────────────────────────────────────
generateBtn.addEventListener('click', handleGenerate);

urlInput.addEventListener('keydown', e => {
  if (e.key === 'Enter') handleGenerate();
});

urlInput.addEventListener('input', () => {
  clearTimeout(previewDebounceTimer);
  previewDebounceTimer = setTimeout(() => fetchVideoPreview(urlInput.value.trim()), 700);
});

urlInput.addEventListener('paste', () => {
  setTimeout(() => fetchVideoPreview(urlInput.value.trim()), 100);
});

newVideoBtn.addEventListener('click', resetToInput);
retryBtn.addEventListener('click', resetToInput);

window.addEventListener('DOMContentLoaded', () => {
  urlInput.focus();
});

// ─── Clip Count Stepper ───────────────────────────────────────────────────────
const clipsDisplay = document.getElementById('clips-display');
const clipsDecBtn = document.getElementById('clips-dec');
const clipsIncBtn = document.getElementById('clips-inc');

function updateClipsDisplay() {
  clipsDisplay.classList.remove('count-pop');
  void clipsDisplay.offsetWidth;
  clipsDisplay.classList.add('count-pop');
  if (clipsCount === null) {
    clipsDisplay.textContent = 'Default';
    clipsDisplay.classList.add('clips-default');
  } else {
    clipsDisplay.textContent = clipsCount;
    clipsDisplay.classList.remove('clips-default');
  }
}

clipsDecBtn.addEventListener('click', () => {
  if (clipsCount === null) { clipsCount = 4; }
  else if (clipsCount <= 1) { clipsCount = null; }
  else { clipsCount--; }
  updateClipsDisplay();
});

clipsIncBtn.addEventListener('click', () => {
  if (clipsCount === null) { clipsCount = 6; }
  else { clipsCount = Math.min(10, clipsCount + 1); }
  updateClipsDisplay();
});

// --- Sidebar Tab Navigation ---------------------------------------------------
(function initSidebar() {
  const navItems = document.querySelectorAll('.nav-item');
  const tabPanels = document.querySelectorAll('.tab-panel');

  navItems.forEach(btn => {
    btn.addEventListener('click', () => {
      const target = btn.dataset.tab;

      navItems.forEach(n => n.classList.remove('active'));
      tabPanels.forEach(p => p.classList.remove('active'));

      btn.classList.add('active');
      const panel = document.getElementById('tab-' + target);
      if (panel) panel.classList.add('active');

      if (target === 'dashboard') updateDashboard();
      if (target === 'history') renderHistory();
    });
  });
})();

// --- Analytics State (persisted in sessionStorage) ---------------------------
function getStats() {
  return {
    videos: parseInt(sessionStorage.getItem('stat_videos') || '0', 10),
    clips: parseInt(sessionStorage.getItem('stat_clips') || '0', 10),
  };
}

function incrementStats(clipsAdded) {
  const s = getStats();
  sessionStorage.setItem('stat_videos', s.videos + 1);
  sessionStorage.setItem('stat_clips', s.clips + clipsAdded);
}

function updateDashboard() {
  const s = getStats();
  const hoursPerClip = 0.5; // ~30min saved per clip
  const hours = (s.clips * hoursPerClip).toFixed(1);

  animateCounter('stat-videos', s.videos);
  animateCounter('stat-clips', s.clips);
  const hoursEl = document.getElementById('stat-hours');
  if (hoursEl) hoursEl.textContent = hours + 'h';
}

function animateCounter(id, target) {
  const el = document.getElementById(id);
  if (!el) return;
  const duration = 800;
  const start = performance.now();
  const from = 0;
  function step(now) {
    const progress = Math.min((now - start) / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 3);
    el.textContent = Math.round(from + (target - from) * eased);
    if (progress < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}

// --- History ------------------------------------------------------------------
function getHistory() {
  try { return JSON.parse(sessionStorage.getItem('clip_history') || '[]'); }
  catch { return []; }
}

function addHistoryEntry(url, clipCount, thumbnailUrl) {
  const history = getHistory();
  history.unshift({
    url,
    clipCount,
    thumbnailUrl: thumbnailUrl || null,
    date: new Date().toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' }),
    id: Date.now(),
  });
  sessionStorage.setItem('clip_history', JSON.stringify(history.slice(0, 50)));
}

function renderHistory() {
  const container = document.getElementById('history-container');
  const emptyEl = document.getElementById('history-empty');
  const history = getHistory();

  // Remove old items
  container.querySelectorAll('.history-item').forEach(el => el.remove());

  if (history.length === 0) {
    emptyEl.style.display = 'block';
    return;
  }
  emptyEl.style.display = 'none';

  history.forEach(entry => {
    const item = document.createElement('div');
    item.className = 'history-item';
    item.dataset.historyId = entry.id;

    const thumbHtml = entry.thumbnailUrl
      ? `<img src="${entry.thumbnailUrl}" alt="Thumbnail" loading="lazy" />`
      : '??';

    item.innerHTML = `
      <div class="history-thumb">${thumbHtml}</div>
      <div class="history-info">
        <div class="history-url" title="${entry.url}">${entry.url}</div>
        <div class="history-meta">
          <span class="history-date">${entry.date}</span>
          <span class="history-clip-count">${entry.clipCount} clips</span>
        </div>
      </div>
      <button class="btn-view-clips" data-url="${encodeURIComponent(entry.url)}">View Clips</button>
    `;

    item.querySelector('.btn-view-clips').addEventListener('click', () => {
      // Switch to Studio tab and pre-fill URL
      document.querySelector('[data-tab="studio"]').click();
      urlInput.value = entry.url;
      urlInput.focus();
    });

    container.appendChild(item);
  });
}

// --- Clear History ------------------------------------------------------------
document.getElementById('clear-history-btn').addEventListener('click', () => {
  sessionStorage.removeItem('clip_history');
  renderHistory();
});

// --- Caption Style Card Selection --------------------------------------------
(function initStyleCards() {
  const cards = document.querySelectorAll('.style-card');
  let selectedStyle = 'mrbeast';

  cards.forEach(card => {
    card.addEventListener('click', () => {
      // deselect all
      cards.forEach(c => {
        c.classList.remove('active');
        c.setAttribute('aria-pressed', 'false');
      });
      // select clicked
      card.classList.add('active');
      card.setAttribute('aria-pressed', 'true');
      selectedStyle = card.dataset.style;
      console.log('[StyleCards] Selected:', selectedStyle);
    });
  });

  // Expose globally so callBackend can include it in payload
  window.getSelectedCaptionStyle = () => selectedStyle;

  // Customize button now opens the Caption Customizer modal (Segment 5 – handled via onclick in HTML)

  // Show/hide the styling section based on CC toggle
  const ccRadios = document.querySelectorAll('input[name="auto-captions"]');
  const stylingSection = document.getElementById('caption-styling-section');

  function syncStylingVisibility() {
    const ccOn = document.querySelector('input[name="auto-captions"]:checked')?.value === 'true';
    if (stylingSection) {
      stylingSection.style.opacity  = ccOn ? '1' : '0.35';
      stylingSection.style.pointerEvents = ccOn ? 'auto' : 'none';
    }
  }

  ccRadios.forEach(r => r.addEventListener('change', syncStylingVisibility));
  syncStylingVisibility(); // run on load
})();


// --- Visual Enhancements – Pill Selectors & Logo Upload --------------------
(function initVisualEnhancements() {

  // ── Grade pills ────────────────────────────────────────────────────────
  const gradePills = document.querySelectorAll('#grade-pills .grade-pill');
  gradePills.forEach(pill => {
    pill.addEventListener('click', () => {
      gradePills.forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
    });
  });

  // ── Corner pills ───────────────────────────────────────────────────────
  const cornerPills = document.querySelectorAll('#corner-pills .corner-pill');
  cornerPills.forEach(pill => {
    pill.addEventListener('click', () => {
      cornerPills.forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
    });
  });

  // ── Size pills ─────────────────────────────────────────────────────────
  const sizePills = document.querySelectorAll('#size-pills .size-pill');
  sizePills.forEach(pill => {
    pill.addEventListener('click', () => {
      sizePills.forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
    });
  });

  // ── Logo upload ────────────────────────────────────────────────────────
  const logoArea  = document.getElementById('logo-upload-area');
  const logoInput = document.getElementById('logo-file-input');

  if (logoArea && logoInput) {
    logoArea.addEventListener('click', () => logoInput.click());
    logoArea.addEventListener('dragover', e => { e.preventDefault(); logoArea.style.borderColor = 'rgba(56,189,248,0.8)'; });
    logoArea.addEventListener('dragleave', () => { logoArea.style.borderColor = ''; });
    logoArea.addEventListener('drop', e => {
      e.preventDefault();
      logoArea.style.borderColor = '';
      const file = e.dataTransfer?.files?.[0];
      if (file) uploadLogo(file);
    });

    logoInput.addEventListener('change', () => {
      const file = logoInput.files?.[0];
      if (file) uploadLogo(file);
      logoInput.value = '';
    });
  }

  async function uploadLogo(file) {
    const allowed = ['image/png', 'image/jpeg', 'image/jpg', 'image/webp'];
    if (!allowed.includes(file.type)) {
      alert('Please upload a PNG, JPG or WebP image.');
      return;
    }
    const fd = new FormData();
    fd.append('file', file);
    try {
      logoArea.style.opacity = '0.5';
      const res  = await fetch('/api/upload-logo', { method: 'POST', body: fd });
      const data = await res.json();
      if (data.error) { alert('Upload failed: ' + data.error); return; }
      window._logoFilename = data.filename;
      // Show preview
      const preview = document.getElementById('logo-preview-img');
      const label   = document.getElementById('logo-filename-label');
      if (preview) { preview.src = URL.createObjectURL(file); }
      if (label)   { label.textContent = file.name; }
      // Swap upload area for controls
      const controls = document.getElementById('logo-controls');
      if (logoArea)   { logoArea.style.display = 'none'; }
      if (controls)   { controls.style.display = 'block'; }
    } catch (err) {
      alert('Upload error: ' + err.message);
    } finally {
      logoArea.style.opacity = '';
    }
  }

  // Expose clearLogo globally (used by Remove button in HTML)
  window.clearLogo = function() {
    window._logoFilename = null;
    const preview  = document.getElementById('logo-preview-img');
    const label    = document.getElementById('logo-filename-label');
    const controls = document.getElementById('logo-controls');
    if (preview)  { preview.src = ''; }
    if (label)    { label.textContent = ''; }
    if (logoArea) { logoArea.style.display = 'flex'; }
    if (controls) { controls.style.display = 'none'; }
  };

})();


// ═══════════════════════════════════════════════════════════════════════════
// SEGMENT 1 – Source Toggle + Language Selector + File Upload
// ═══════════════════════════════════════════════════════════════════════════
(function initSourceAndLanguage() {
  // Source type toggle
  const srcRadios = document.querySelectorAll('input[name="source-type"]');
  const ytPanel   = document.getElementById('source-youtube-panel');
  const upPanel   = document.getElementById('source-upload-panel');
  const langGroup = document.getElementById('language-selector-group');

  function syncSourcePanels() {
    const val = document.querySelector('input[name="source-type"]:checked')?.value || 'youtube';
    if (ytPanel)  ytPanel.style.display  = val === 'youtube' ? '' : 'none';
    if (upPanel)  upPanel.style.display  = val === 'upload'  ? '' : 'none';
    // Hide language selector for uploads if non-English is irrelevant (keep it anyway for UX)
  }
  srcRadios.forEach(r => r.addEventListener('change', syncSourcePanels));
  syncSourcePanels();

  // Language grid
  let selectedLanguage = 'english';
  const langBtns = document.querySelectorAll('.lang-btn');
  langBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      langBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      selectedLanguage = btn.dataset.lang;
    });
  });
  window.getSelectedLanguage = () => selectedLanguage;

  // File upload drop zone
  const dropZone    = document.getElementById('upload-drop-zone');
  const fileInput   = document.getElementById('video-file-input');
  const browseLink  = document.getElementById('upload-browse-link');
  const progressArea= document.getElementById('upload-progress-area');
  const barFill     = document.getElementById('upload-bar-fill');
  const pctLabel    = document.getElementById('upload-pct-label');
  const statusText  = document.getElementById('upload-status-text');
  const fileNameEl  = document.getElementById('upload-filename');
  const cancelBtn   = document.getElementById('upload-cancel-btn');

  window._uploadedFilename = null;

  function resetUpload() {
    window._uploadedFilename = null;
    if (progressArea) progressArea.style.display = 'none';
    if (dropZone) dropZone.style.display = '';
    if (fileInput) fileInput.value = '';
  }

  if (cancelBtn) cancelBtn.addEventListener('click', resetUpload);

  if (browseLink) browseLink.addEventListener('click', () => fileInput && fileInput.click());
  if (dropZone) {
    dropZone.addEventListener('click', () => fileInput && fileInput.click());
    dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('dragover'); });
    dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
    dropZone.addEventListener('drop', e => {
      e.preventDefault(); dropZone.classList.remove('dragover');
      const file = e.dataTransfer.files[0];
      if (file) uploadFile(file);
    });
  }
  if (fileInput) fileInput.addEventListener('change', () => { if (fileInput.files[0]) uploadFile(fileInput.files[0]); });

  async function uploadFile(file) {
    if (!dropZone || !progressArea) return;
    dropZone.style.display = 'none';
    progressArea.style.display = '';
    if (fileNameEl) fileNameEl.textContent = file.name;
    if (statusText) statusText.textContent = 'Uploading...';
    if (barFill) barFill.style.width = '0%';
    if (pctLabel) pctLabel.textContent = '0%';

    const fd = new FormData();
    fd.append('file', file);

    return new Promise((resolve) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', '/api/upload-video');
      xhr.upload.onprogress = e => {
        if (e.lengthComputable) {
          const pct = Math.round(e.loaded / e.total * 100);
          if (barFill) barFill.style.width = pct + '%';
          if (pctLabel) pctLabel.textContent = pct + '%';
        }
      };
      xhr.onload = () => {
        try {
          const data = JSON.parse(xhr.responseText);
          if (data.ok) {
            window._uploadedFilename = data.filename;
            if (statusText) statusText.textContent = `Ready — ${fmtDuration(data.duration)} · ${data.width}×${data.height}`;
            if (pctLabel) pctLabel.textContent = '100%';
            if (barFill) barFill.style.width = '100%';
          } else {
            if (statusText) { statusText.textContent = 'Upload failed: ' + (data.error || 'unknown'); statusText.style.color = '#ffb4ab'; }
            setTimeout(resetUpload, 3000);
          }
        } catch { if (statusText) statusText.textContent = 'Server error'; }
        resolve();
      };
      xhr.onerror = () => { if (statusText) statusText.textContent = 'Network error'; resolve(); };
      xhr.send(fd);
    });
  }

  function fmtDuration(s) {
    if (!s) return '';
    return Math.floor(s/60) + ':' + String(Math.floor(s%60)).padStart(2,'0');
  }
})();

// ═══════════════════════════════════════════════════════════════════════════
// SEGMENT 2 – SRT Export on video cards
// ═══════════════════════════════════════════════════════════════════════════
function createSrtButton(clipUrl) {
  const filename = clipUrl.split('/').pop();
  const btn = document.createElement('a');
  btn.className = 'btn-srt';
  btn.href = `/api/clip-srt/${filename}`;
  btn.download = filename.replace('.mp4', '.srt');
  btn.title = 'Download SRT subtitle file';
  btn.innerHTML = `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> SRT`;
  return btn;
}

// ═══════════════════════════════════════════════════════════════════════════
// SEGMENT 4 – Caption Editor
// ═══════════════════════════════════════════════════════════════════════════
let _captionEditorState = { filename: null, words: [], captionStyle: 'mrbeast', targetCard: null };

function createEditCaptionsButton(clipUrl, captionStyle) {
  const btn = document.createElement('button');
  btn.className = 'btn-edit-captions';
  btn.title = 'Edit captions word by word';
  btn.innerHTML = `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg> Edit Captions`;
  btn.addEventListener('click', async () => {
    const filename = clipUrl.split('/').pop();
    btn.disabled = true;
    btn.textContent = 'Loading...';
    try {
      const res = await fetch(`/api/clip-transcript/${filename}`);
      const data = await res.json();
      if (data.error) { alert('Captions not available for this clip.'); return; }
      _captionEditorState = { filename, words: JSON.parse(JSON.stringify(data.words)), captionStyle };
      _captionEditorState.targetCard = btn.closest('.video-card');
      openCaptionEditor(data.words);
    } catch (e) {
      alert('Could not load transcript: ' + e.message);
    } finally {
      btn.disabled = false;
      btn.innerHTML = `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg> Edit Captions`;
    }
  });
  return btn;
}

function openCaptionEditor(words) {
  const modal = document.getElementById('caption-editor-modal');
  const container = document.getElementById('caption-editor-words');
  if (!modal || !container) return;
  container.innerHTML = '';

  words.forEach((w, i) => {
    const chip = document.createElement('span');
    chip.className = 'caption-word-chip';
    chip.textContent = w.word;
    chip.dataset.idx = i;

    chip.addEventListener('click', () => {
      if (chip.classList.contains('editing')) return;
      chip.classList.add('editing');
      const inp = document.createElement('input');
      inp.type = 'text';
      inp.value = w.word;
      inp.style.width = Math.max(60, w.word.length * 10) + 'px';
      chip.textContent = '';
      chip.appendChild(inp);
      inp.focus();
      inp.select();

      function commit() {
        const newVal = inp.value.trim() || w.word;
        _captionEditorState.words[i].word = newVal;
        chip.classList.remove('editing');
        chip.textContent = newVal;
      }
      inp.addEventListener('blur', commit);
      inp.addEventListener('keydown', e => { if (e.key === 'Enter') inp.blur(); if (e.key === 'Escape') { inp.value = w.word; inp.blur(); } });
    });
    container.appendChild(chip);
  });

  modal.style.display = 'flex';
}

document.addEventListener('DOMContentLoaded', () => {
  const rebakeBtn = document.getElementById('caption-editor-rebake');
  if (rebakeBtn) {
    rebakeBtn.addEventListener('click', async () => {
      rebakeBtn.disabled = true;
      rebakeBtn.textContent = 'Re-baking...';
      try {
        const res = await fetch('/api/rebake-captions', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            filename: _captionEditorState.filename,
            words: _captionEditorState.words,
            captionStyle: _captionEditorState.captionStyle,
            customStyle: (typeof window.getCustomStyle === 'function') ? window.getCustomStyle() : null,
          }),
        });
        const data = await res.json();
        if (data.ok && data.clip) {
          // Replace the video card with the new rebaked clip
          const card = _captionEditorState.targetCard;
          if (card) {
            const video = card.querySelector('video');
            if (video) {
              video.src = data.clip + '?t=' + Date.now();
              video.load();
            }
            // Update SRT link
            const srtLink = card.querySelector('.btn-srt');
            if (srtLink) srtLink.href = '/api/clip-srt/' + data.clip.split('/').pop();
          }
          document.getElementById('caption-editor-modal').style.display = 'none';
        } else {
          alert('Re-bake failed: ' + (data.error || 'unknown error'));
        }
      } catch (e) {
        alert('Error: ' + e.message);
      } finally {
        rebakeBtn.disabled = false;
        rebakeBtn.innerHTML = `<span class="material-symbols-outlined" style="font-size:18px;font-variation-settings:'FILL' 1">movie_edit</span> Re-bake Captions <span class="btn-shimmer"></span>`;
      }
    });
  }
});

// ═══════════════════════════════════════════════════════════════════════════
// SEGMENT 5 – Caption Customizer
// ═══════════════════════════════════════════════════════════════════════════
(function initCaptionCustomizer() {
  let _customStyle = null; // null = use style preset default

  const sizeSlider    = document.getElementById('cust-size');
  const sizeVal       = document.getElementById('cust-size-val');
  const outlineSlider = document.getElementById('cust-outline-width');
  const outlineVal    = document.getElementById('cust-outline-val');
  const applyBtn      = document.getElementById('cust-apply-btn');
  const resetBtn      = document.getElementById('cust-reset-btn');

  if (sizeSlider && sizeVal) {
    sizeVal.textContent = sizeSlider.value + 'px';
    sizeSlider.addEventListener('input', () => sizeVal.textContent = sizeSlider.value + 'px');
  }
  if (outlineSlider && outlineVal) {
    outlineVal.textContent = outlineSlider.value + 'px';
    outlineSlider.addEventListener('input', () => outlineVal.textContent = outlineSlider.value + 'px');
  }

  if (applyBtn) {
    applyBtn.addEventListener('click', () => {
      _customStyle = {
        font:           document.getElementById('cust-font')?.value || null,
        size:           parseInt(sizeSlider?.value || '110'),
        primaryColor:   document.getElementById('cust-primary-color')?.value,
        highlightColor: document.getElementById('cust-highlight-color')?.value,
        outlineColor:   document.getElementById('cust-outline-color')?.value,
        outlineWidth:   parseInt(outlineSlider?.value || '3'),
        uppercase:      document.getElementById('cust-uppercase')?.checked ?? true,
        wordsPerLine:   parseInt(document.querySelector('input[name="cust-wpl"]:checked')?.value || '3'),
        position:       document.querySelector('input[name="cust-pos"]:checked')?.value || 'bottom',
      };
      // Remove empty/null fields
      if (!_customStyle.font) delete _customStyle.font;

      const btn = document.getElementById('btn-customize');
      if (btn) { btn.style.background = 'rgba(139,92,246,0.25)'; btn.style.borderColor = 'rgba(139,92,246,0.6)'; btn.style.color = '#d0bcff'; }
      document.getElementById('caption-customizer-modal').style.display = 'none';
    });
  }

  if (resetBtn) {
    resetBtn.addEventListener('click', () => {
      _customStyle = null;
      const btn = document.getElementById('btn-customize');
      if (btn) { btn.style.background = ''; btn.style.borderColor = ''; btn.style.color = ''; }
      document.getElementById('caption-customizer-modal').style.display = 'none';
    });
  }

  window.getCustomStyle = () => _customStyle;

  // ── Custom Font Upload ────────────────────────────────────────────────────
  const fontZone  = document.getElementById('font-upload-zone');
  const fontInput = document.getElementById('font-file-input');
  const fontLabel = document.getElementById('font-upload-label');
  const fontStatus = document.getElementById('font-status-text');
  let _uploadedFontName = null;

  if (fontZone && fontInput) {
    fontZone.addEventListener('click', () => fontInput.click());
    fontZone.addEventListener('dragover', e => { e.preventDefault(); fontZone.style.borderColor = 'rgba(139,92,246,0.7)'; });
    fontZone.addEventListener('dragleave', () => { fontZone.style.borderColor = 'rgba(139,92,246,0.35)'; });
    fontZone.addEventListener('drop', e => {
      e.preventDefault();
      fontZone.style.borderColor = 'rgba(139,92,246,0.35)';
      const file = e.dataTransfer.files[0];
      if (file) { const dt = new DataTransfer(); dt.items.add(file); fontInput.files = dt.files; fontInput.dispatchEvent(new Event('change')); }
    });

    fontInput.addEventListener('change', async () => {
      const file = fontInput.files[0];
      if (!file) return;
      fontLabel.textContent = 'Uploading…';
      fontStatus.style.display = 'none';
      try {
        const fd = new FormData();
        fd.append('file', file);
        const res = await fetch('/api/upload-font', { method: 'POST', body: fd });
        const data = await res.json();
        if (data.ok) {
          _uploadedFontName = data.fontName;
          fontLabel.textContent = file.name;
          fontLabel.style.color = '#34d399';
          fontStatus.textContent = `✓ "${data.fontName}" installed`;
          fontStatus.style.display = 'inline';
          // Add to the font selector
          const sel = document.getElementById('cust-font');
          if (sel) {
            const opt = document.createElement('option');
            opt.value = data.fontName;
            opt.textContent = data.fontName + ' (uploaded)';
            opt.selected = true;
            sel.appendChild(opt);
          }
        } else {
          fontLabel.textContent = 'Upload failed';
          fontLabel.style.color = '#ffb4ab';
          fontStatus.textContent = data.error || 'Unknown error';
          fontStatus.style.display = 'inline';
          fontStatus.style.color = '#ffb4ab';
        }
      } catch (err) {
        fontLabel.textContent = 'Upload failed';
        fontStatus.textContent = err.message;
        fontStatus.style.display = 'inline';
        fontStatus.style.color = '#ffb4ab';
      }
    });
  }

  window.getUploadedFont = () => _uploadedFontName;
})();
