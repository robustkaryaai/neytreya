const fs = require('fs');

const htmlPath = 'electron/renderer/onboarding.html';
let html = fs.readFileSync(htmlPath, 'utf8');

// The missing step 5
const step5 = `
    <!-- ── Step 5: Vision ───────────────────────────────────── -->
    <div class="step" id="step-5">
      <div class="step-emoji">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="var(--em)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
          <circle cx="12" cy="12" r="3"></circle>
        </svg>
      </div>
      <h2>Deep screen<br>understanding?</h2>
      <p class="sub">Uses a local AI model via Ollama.<br>Everything stays on your device — nothing leaves.</p>

      <div class="vis-toggle-row">
        <span class="vis-label" id="vis-label">Disabled</span>
        <label class="big-tog">
          <input type="checkbox" id="ob-vision" />
          <span class="big-track"><span class="big-thumb"></span></span>
        </label>
      </div>

      <div class="model-section" id="model-section" style="display:none">
        <div class="model-detecting" id="model-detecting">
          <div class="detect-spinner"></div>
          <span>Detecting your system…</span>
        </div>
        <div class="spec-badge hidden" id="spec-badge">
          <span id="spec-platform"></span>
          <span class="spec-sep">·</span>
          <span id="spec-ram"></span> RAM
        </div>
        <div class="model-title">Choose Vision Model</div>
        <div class="model-grid" id="model-grid"></div>
        <div class="pull-progress hidden" id="pull-progress">
          <div class="pull-label">
            <span id="pull-model-name">Installing model…</span>
            <span id="pull-pct">0%</span>
          </div>
          <div class="pull-track">
            <div class="pull-fill" id="pull-fill"></div>
          </div>
          <div class="pull-status" id="pull-status">Downloading…</div>
        </div>
        <div class="ollama-hint">
          Requires <a id="ollama-link" style="color:var(--em);cursor:pointer">Ollama</a> running locally.
          Only fires on LOW system load.
        </div>
      </div>

      <div class="nav-row" id="vision-nav-row">
        <button class="btn-back" id="back-5">← Back</button>
        <button class="btn-em sm" id="next-5">Next →</button>
      </div>
    </div>

    <!-- ── Step 6: Done! ────────────────────────────────────── -->
    <div class="step" id="step-6">
`;

html = html.replace('    <!-- ── Step 5: Done! ────────────────────────────────────── -->\n    <div class="step" id="step-5">', step5);
html = html.replace('<div class="p-dot"></div>\n    <div class="p-dot"></div>\n    <div class="p-dot"></div>\n  </div>', '<div class="p-dot"></div>\n    <div class="p-dot"></div>\n    <div class="p-dot"></div>\n    <div class="p-dot"></div>\n  </div>');

fs.writeFileSync(htmlPath, html);

const jsPath = 'electron/renderer/onboarding.js';
let js = fs.readFileSync(jsPath, 'utf8');

js = js.replace('const TOTAL_STEPS = 5;', 'const TOTAL_STEPS = 6;');
js = js.replace('if (next === 5) {', 'if (next === 5) onEnterVisionStep();\n  if (next === 6) {');
js = js.replace("document.getElementById('btn-launch').addEventListener('click'", `
// ── Step 5: Vision — Dynamic Model Selection ──────────────────

const obVision  = document.getElementById('ob-vision');
const modelSec  = document.getElementById('model-section');
const visLabel  = document.getElementById('vis-label');
const modelGrid = document.getElementById('model-grid');
const detecting = document.getElementById('model-detecting');
const specBadge = document.getElementById('spec-badge');

let specsLoaded  = false;
let specsLoading = false;

obVision.addEventListener('change', () => {
  const enabled = obVision.checked;
  state.data.visionEnabled = enabled;
  visLabel.textContent = enabled ? 'Enabled' : 'Disabled';
  modelSec.style.display = enabled ? '' : 'none';
  if (enabled && !specsLoaded && !specsLoading) loadSystemSpecs();
});

async function onEnterVisionStep() {
  if (obVision.checked && !specsLoaded && !specsLoading) {
    await loadSystemSpecs();
  }
}

async function loadSystemSpecs() {
  specsLoading = true;
  detecting.style.display = 'flex';
  specBadge.classList.add('hidden');
  modelGrid.innerHTML = '';

  try {
    const specs = await window.neytreya.detectSystemSpecs();
    state.data.systemSpecs = specs;
    specsLoaded = true;

    const platformLabel = specs.is_apple_silicon
      ? '🍎 Apple Silicon'
      : specs.platform === 'darwin' ? '🍏 Mac (Intel)'
      : specs.platform === 'win32'  ? '🪟 Windows'
      : '🖥 Linux';

    document.getElementById('spec-platform').textContent = platformLabel;
    document.getElementById('spec-ram').textContent      = \`\${specs.ram_gb} GB\`;
    specBadge.classList.remove('hidden');
    renderModelCards(specs);

  } catch (err) {
    console.error('System spec detection failed:', err);
    detecting.innerHTML = '<span style="color:var(--em-dim)">Could not detect system. Pick a model manually.</span>';
    renderFallbackCards();
  } finally {
    specsLoading = false;
    detecting.style.display = 'none';
  }
}

function renderModelCards(specs) {
  modelGrid.innerHTML = '';
  const tiers       = specs.tiers || [];
  const recommended = specs.recommended_model;

  tiers.forEach(tier => {
    const isRec  = tier.model === recommended;
    const hasRam = specs.avail_gb >= tier.min_ram_gb;
    const card   = document.createElement('div');
    card.className = 'model-card' + (isRec ? ' sel' : '') + (!hasRam ? ' dimmed' : '');
    card.dataset.model = tier.model;

    card.innerHTML = \`
      \${isRec ? '<div class="mc-rec-badge">✦ Recommended</div>' : ''}
      <div class="mc-name">\${tier.label}</div>
      <div class="mc-tag">\${tier.ram_note} RAM required</div>
      \${!hasRam ? '<div class="mc-warn">Low RAM — may be slow</div>' : ''}
    \`;

    card.addEventListener('click', () => {
      document.querySelectorAll('.model-card').forEach(c => c.classList.remove('sel'));
      card.classList.add('sel');
      state.data.visionModel = tier.model;
    });

    modelGrid.appendChild(card);
    if (isRec) state.data.visionModel = tier.model;
  });
}

function renderFallbackCards() {
  const fallback = [
    { model: 'qwen3-vl:30b',      label: 'Qwen3-VL 30B',      ram_note: '22GB+',   isRec: false },
    { model: 'qwen3-vl:8b',   label: 'Qwen3-VL 8B (recommended)',   ram_note: '8GB+', isRec: true },
    { model: 'qwen3-vl:4b',   label: 'Qwen3-VL 4B',   ram_note: '4GB+', isRec: false },
    { model: 'qwen3-vl:2b',   label: 'Qwen3-VL 2B',   ram_note: '1GB+', isRec: false },
  ];
  modelGrid.innerHTML = '';
  fallback.forEach(tier => {
    const card = document.createElement('div');
    card.className = 'model-card' + (tier.isRec ? ' sel' : '');
    card.dataset.model = tier.model;
    card.innerHTML = \`
      \${tier.isRec ? '<div class="mc-rec-badge">✦ Recommended</div>' : ''}
      <div class="mc-name">\${tier.label}</div>
      <div class="mc-tag">\${tier.ram_note} RAM required</div>
    \`;
    card.addEventListener('click', () => {
      document.querySelectorAll('.model-card').forEach(c => c.classList.remove('sel'));
      card.classList.add('sel');
      state.data.visionModel = tier.model;
    });
    modelGrid.appendChild(card);
    if (tier.isRec) state.data.visionModel = tier.model;
  });
}

// ── Step 5: Next — trigger model pull if vision enabled ───────

document.getElementById('next-5').addEventListener('click', async () => {
  // If vision disabled → skip straight to done
  if (!state.data.visionEnabled) {
    next();
    return;
  }

  // If no model selected (shouldn't happen with fallback, but just in case)
  if (!state.data.visionModel) {
    next();
    return;
  }

  // Already pulled → advance
  if (state.modelPulled) { next(); return; }

  // Pull in progress → do nothing (button shows "Installing…")
  if (state.pullInProgress) return;

  // Start the pull
  await startModelPull(state.data.visionModel);
});

document.getElementById('back-5').addEventListener('click', back);

async function startModelPull(modelName) {
  state.pullInProgress = true;

  const pullProgress  = document.getElementById('pull-progress');
  const pullFill      = document.getElementById('pull-fill');
  const pullPct       = document.getElementById('pull-pct');
  const pullStatus    = document.getElementById('pull-status');
  const pullModelName = document.getElementById('pull-model-name');
  const btn           = document.getElementById('next-5');
  const backBtn       = document.getElementById('back-5');

  pullProgress.classList.remove('hidden');
  pullModelName.textContent  = \`Installing \${modelName}…\`;
  pullFill.style.width       = '0%';
  pullPct.textContent        = '0%';
  pullStatus.textContent     = 'Connecting to Ollama…';
  btn.disabled               = true;
  btn.textContent            = 'Installing…';
  backBtn.disabled           = true;

  const removeListener = window.neytreya.onOllamaProgress((data) => {
    if (data.model !== modelName) return;
    const pct = data.percent || 0;
    pullFill.style.width   = pct + '%';
    pullPct.textContent    = pct + '%';
    pullStatus.textContent = data.status === 'done' ? '✓ Model ready!' : \`Downloading… \${pct}%\`;
    if (data.status === 'done') pullStatus.style.color = 'var(--em)';
  });

  try {
    await window.neytreya.installVisionModel(modelName);
    state.modelPulled = true;

    pullStatus.textContent = '✓ Setup complete!';
    pullStatus.style.color = 'var(--em)';
    pullFill.style.width   = '100%';
    pullPct.textContent    = '100%';

    btn.textContent  = 'Next →';
    btn.disabled     = false;
    backBtn.disabled = false;
    state.pullInProgress = false;
    removeListener && removeListener();

    // Auto-advance after short delay
    setTimeout(() => next(), 800);

  } catch (err) {
    console.error('Model install failed:', err);
    pullStatus.textContent = '⚠ Ollama not running — you can install it later.';
    pullStatus.style.color = '#f87171';
    btn.textContent  = 'Skip & continue →';
    btn.disabled     = false;
    backBtn.disabled = false;
    state.pullInProgress = false;
    removeListener && removeListener();

    btn.onclick = () => { btn.onclick = null; btn.textContent = 'Next →'; next(); };
  }
}

// ── Step 6: Launch ────────────────────────────────────────────

document.getElementById('btn-launch').addEventListener('click'`);

fs.writeFileSync(jsPath, js);
