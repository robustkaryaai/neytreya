'use strict';

/* ──────────────────────────────────────────────────────────────
   Neytreya Onboarding Logic — v3
   6-step flow: Auth → Name → Work Style → Quiet Hours → Vision → Done
   ────────────────────────────────────────────────────────────── */

const TOTAL_STEPS = 6;

const state = {
  current: 1,
  data: {
    email:         '',
    offline:       false,
    name:          '',
    workStyles:    [],
    quietFrom:     '00:00',
    quietTo:       '00:00',
    visionEnabled: false,
    visionModel:   '',
    systemSpecs:   null,
  },
  modelPulled:    false,
  pullInProgress: false,
};

// ── Transition engine ─────────────────────────────────────────

const FORWARD_DURATION = 480;
const BACK_DURATION    = 420;

function goTo(next, direction = 'forward') {
  const prev   = state.current;
  const prevEl = document.getElementById(`step-${prev}`);
  const nextEl = document.getElementById(`step-${next}`);
  if (!prevEl || !nextEl || prev === next) return;

  const dur    = direction === 'forward' ? FORWARD_DURATION : BACK_DURATION;
  const spring = `cubic-bezier(0.34, 1.56, 0.64, 1)`;
  const ease   = `cubic-bezier(0.16, 1, 0.3, 1)`;
  const startX = direction === 'forward' ? '100%' : '-80%';
  const endX   = direction === 'forward' ? '-80%' : '100%';

  nextEl.style.cssText = `
    transform: translateX(${startX}) scale(0.95);
    opacity: 0; pointer-events: none; transition: none;
  `;
  void nextEl.offsetWidth;

  prevEl.classList.remove('active');
  const transition = `transform ${dur}ms ${spring}, opacity ${Math.round(dur * 0.65)}ms ${ease}`;

  prevEl.style.transition = transition;
  prevEl.style.transform  = `translateX(${endX}) scale(0.96)`;
  prevEl.style.opacity    = '0';

  nextEl.style.transition = transition;
  nextEl.style.transform  = 'translateX(0) scale(1)';
  nextEl.style.opacity    = '1';
  nextEl.style.pointerEvents = '';

  setTimeout(() => {
    prevEl.style.cssText = '';
    nextEl.style.cssText = '';
    nextEl.classList.add('active');
  }, dur + 20);

  updateProgress(next);
  state.current = next;

  if (next === 5) onEnterVisionStep();
  if (next === 6) {
    const nameEl = document.getElementById('done-name');
    if (state.data.name) nameEl.textContent = state.data.name;
  }
}

function next() { if (state.current < TOTAL_STEPS) goTo(state.current + 1, 'forward'); }
function back() { if (state.current > 1)           goTo(state.current - 1, 'back'); }

function updateProgress(n) {
  document.querySelectorAll('.p-dot').forEach((d, i) => {
    d.classList.toggle('active', i === n - 1);
  });
}

// ── Step 1: Auth ──────────────────────────────────────────────

const authEmail = document.getElementById('auth-email');
const authPass  = document.getElementById('auth-pass');

authEmail.addEventListener('keydown', e => { if (e.key === 'Enter') authPass.focus(); });
authPass.addEventListener('keydown',  e => { if (e.key === 'Enter') doSignIn(); });
document.getElementById('btn-signin').addEventListener('click', doSignIn);

function doSignIn() {
  const email = authEmail.value.trim();
  if (!email || !email.includes('@')) { shake(authEmail); return; }
  state.data.email   = email;
  state.data.offline = false;
  next();
}

// ── Step 1: Google OAuth ──────────────────────────────────────

const btnGoogle = document.getElementById('btn-google');
btnGoogle.addEventListener('click', async () => {
  btnGoogle.disabled = true;
  btnGoogle.style.opacity = '0.7';
  const orig = btnGoogle.innerHTML;
  btnGoogle.innerHTML = '<span style="display:inline-flex;gap:8px;align-items:center"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10" opacity="0.25"/><path d="M12 2a10 10 0 0 1 10 10" stroke-linecap="round"><animateTransform attributeName="transform" type="rotate" from="0 12 12" to="360 12 12" dur="0.8s" repeatCount="indefinite"/></path></svg>Opening Google…</span>';

  const cleanup = window.neytreya.onOAuthSuccess((payload) => {
    cleanup && cleanup();
    if (payload.name) {
      const nameInput = document.getElementById('user-name');
      if (nameInput) nameInput.value = payload.name;
      state.data.name = payload.name;
    }
    state.data.email       = payload.email   || '__google__';
    state.data.user_slug   = payload.slug    || '';
    state.data.user_plan   = payload.plan    || 'free';
    state.data.auth_method = 'google';
    state.data.offline     = false;
    btnGoogle.disabled     = false;
    btnGoogle.style.opacity = '1';
    btnGoogle.innerHTML    = orig;
    next();
  });

  try {
    await window.neytreya.startGoogleOAuth();
  } catch (err) {
    console.error('Google OAuth failed:', err);
    btnGoogle.disabled      = false;
    btnGoogle.style.opacity = '1';
    btnGoogle.innerHTML     = orig;
    if (cleanup) cleanup();
  }
});

document.getElementById('btn-offline').addEventListener('click', () => {
  state.data.offline = true;
  next();
});

// ── Step 2: Name ──────────────────────────────────────────────

const nameInput = document.getElementById('user-name');
document.getElementById('next-2').addEventListener('click', doName);
document.getElementById('back-2').addEventListener('click', back);
nameInput.addEventListener('keydown', e => { if (e.key === 'Enter') doName(); });

function doName() {
  state.data.name = nameInput.value.trim() || 'friend';
  next();
}

// ── Step 3: Work Style ────────────────────────────────────────

document.querySelectorAll('.style-card').forEach(card => {
  card.addEventListener('click', () => {
    card.classList.toggle('sel');
    const v = card.dataset.value;
    if (card.classList.contains('sel')) {
      if (!state.data.workStyles.includes(v)) state.data.workStyles.push(v);
    } else {
      state.data.workStyles = state.data.workStyles.filter(x => x !== v);
    }
  });
});

document.getElementById('next-3').addEventListener('click', next);
document.getElementById('back-3').addEventListener('click', back);

// ── Step 4: Quiet Hours ───────────────────────────────────────

const quietFrom = document.getElementById('quiet-from');
const quietTo   = document.getElementById('quiet-to');
const quietHint = document.getElementById('quiet-hint');

function updateQuietHint() {
  const from = quietFrom.value;
  const to   = quietTo.value;
  if (!quietHint) return;
  if (from === '00:00' && to === '00:00') {
    quietHint.textContent = '🟢 Always active — no quiet hours set';
  } else {
    quietHint.textContent = `🌙 Silent from ${from} to ${to}`;
  }
}

quietFrom.addEventListener('change', updateQuietHint);
quietTo.addEventListener('change', updateQuietHint);

document.getElementById('next-4').addEventListener('click', () => {
  state.data.quietFrom = quietFrom.value;
  state.data.quietTo   = quietTo.value;
  next();
});
document.getElementById('back-4').addEventListener('click', back);



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
    document.getElementById('spec-ram').textContent      = `${specs.ram_gb} GB`;
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
    const hasRam = specs.ram_gb >= tier.min_ram_gb;  // use TOTAL ram, not free
    const card   = document.createElement('div');
    card.className = 'model-card' + (isRec ? ' sel' : '') + (!hasRam ? ' dimmed' : '');
    card.dataset.model = tier.model;

    card.innerHTML = `
      ${isRec ? '<div class="mc-rec-badge">✦ Recommended</div>' : ''}
      <div class="mc-name">${tier.label}</div>
      <div class="mc-tag">${tier.ram_note} RAM required</div>
      ${!hasRam ? '<div class="mc-warn">Not enough RAM — may crash</div>' : ''}
    `;

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
    { model: 'qwen3-vl:30b', label: 'Qwen3-VL 30B', ram_note: '22GB+', isRec: false },
    { model: 'qwen3-vl:8b',  label: 'Qwen3-VL 8B',  ram_note: '8GB+',  isRec: true  },
    { model: 'qwen3-vl:4b',  label: 'Qwen3-VL 4B',  ram_note: '4GB+',  isRec: false },
    { model: 'qwen3-vl:2b',  label: 'Qwen3-VL 2B',  ram_note: '1GB+',  isRec: false },
  ];
  modelGrid.innerHTML = '';
  fallback.forEach(tier => {
    const card = document.createElement('div');
    card.className = 'model-card' + (tier.isRec ? ' sel' : '');
    card.dataset.model = tier.model;
    card.innerHTML = `
      ${tier.isRec ? '<div class="mc-rec-badge">✦ Recommended</div>' : ''}
      <div class="mc-name">${tier.label}</div>
      <div class="mc-tag">${tier.ram_note} RAM required</div>
    `;
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
  pullModelName.textContent  = `Installing ${modelName}…`;
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
    pullStatus.textContent = data.status === 'done' ? '✓ Model ready!' : `Downloading… ${pct}%`;
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

// Wire up the Ollama deep link (opens browser to ollama.com)
const ollamaLink = document.getElementById('ollama-link');
if (ollamaLink) {
  ollamaLink.addEventListener('click', () => {
    window.neytreya.openExternal('https://ollama.com/download');
  });
}

document.getElementById('btn-launch').addEventListener('click', async () => {
  const btn = document.getElementById('btn-launch');
  btn.textContent   = 'Starting Neytreya…';
  btn.style.opacity = '0.7';
  btn.disabled      = true;

  const settings = {
    user_name:           state.data.name,
    work_styles:         state.data.workStyles,
    quiet_hours_start:   state.data.quietTo,
    quiet_hours_end:     state.data.quietFrom,
    vision_enabled:      state.data.visionEnabled,
    vision_model:        state.data.visionModel,
    offline_mode:        state.data.offline,
    onboarding_complete: true,
  };

  try {
    await window.neytreya.completeOnboarding(settings);
  } catch (err) {
    console.error('Onboarding complete failed:', err);
    btn.textContent   = 'Launch Neytreya →';
    btn.style.opacity = '1';
    btn.disabled      = false;
  }
});

// ── Shake helper ──────────────────────────────────────────────

function shake(el) {
  el.style.animation   = 'none';
  el.style.borderColor = 'rgba(239,68,68,0.7)';
  el.style.boxShadow   = '0 0 0 3px rgba(239,68,68,0.12)';
  void el.offsetWidth;
  el.animate([
    { transform: 'translateX(0)' }, { transform: 'translateX(-6px)' },
    { transform: 'translateX(6px)' }, { transform: 'translateX(-4px)' },
    { transform: 'translateX(4px)' }, { transform: 'translateX(0)' },
  ], { duration: 360, easing: 'ease-out' });
  setTimeout(() => { el.style.borderColor = ''; el.style.boxShadow = ''; }, 800);
}
