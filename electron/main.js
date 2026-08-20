'use strict';

const { app, BrowserWindow, ipcMain, Menu, screen,
        dialog, shell, systemPreferences, protocol,
        Tray, nativeImage, globalShortcut } = require('electron');
const path = require('path');
const { spawn, execSync, exec } = require('child_process');
const fs   = require('fs');
const os   = require('os');
const { autoUpdater } = require('electron-updater');

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------
const BACKEND_PORT   = 7432;
const DATA_DIR       = path.join(os.homedir(), '.neytreya');
const SETTINGS_FILE  = path.join(DATA_DIR, 'settings.json');
const APP_STATE_FILE = path.join(DATA_DIR, 'app_state.json'); // Electron-only flags — never touched by Python backend
const ARKIS_URL      = 'https://rexycore.vercel.app';
const PROTOCOL       = 'neytreya';
const PANEL_W        = 370;
const PANEL_H        = 680;
const ONBOARD_W      = 520;
const ONBOARD_H      = 680;
const RECALL_W       = 860;
const RECALL_H       = 620;
const BUBBLE_W       = 320;
const BUBBLE_H       = 90;

let tray             = null;
let panelWindow      = null;
let bubbleWindow     = null;
let onboardingWindow = null;
let recallWindow     = null;
let quickRecallWindow = null;
let setupWindow      = null;
let backendProcess   = null;
let isWatching       = true;  // tracks if engine is active

// ---------------------------------------------------------------------------
// Eye SVG icon generator — used for tray icons
// ---------------------------------------------------------------------------

function createEyeSVG(open = true) {
  if (open) {
    // Black on transparent — works as macOS template image
    return `<svg width="18" height="18" viewBox="0 0 18 18" xmlns="http://www.w3.org/2000/svg">
      <path d="M9 4C5.5 4 2 9 2 9C2 9 5.5 14 9 14C12.5 14 16 9 16 9C16 9 12.5 4 9 4Z"
        fill="none" stroke="#000" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>
      <circle cx="9" cy="9" r="2.8" fill="none" stroke="#000" stroke-width="1.3"/>
      <circle cx="9" cy="9" r="1.1" fill="#000"/>
    </svg>`;
  } else {
    return `<svg width="18" height="18" viewBox="0 0 18 18" xmlns="http://www.w3.org/2000/svg">
      <path d="M2 9C5.5 14 12.5 14 16 9Z" fill="none" stroke="#000" stroke-width="1.5"
        stroke-linejoin="round" stroke-linecap="round"/>
      <line x1="2" y1="9" x2="16" y2="9" stroke="#000" stroke-width="1" opacity="0.4"/>
    </svg>`;
  }
}

function createTrayIcon(open = true) {
  const p = path.join(__dirname, open ? 'eye-openTemplate@2x.png' : 'eye-closedTemplate@2x.png');
  let img;
  if (fs.existsSync(p)) {
    img = nativeImage.createFromPath(p);
  } else {
    // Fallback SVG (black on transparent for template use)
    const svg = Buffer.from(createEyeSVG(open));
    img = nativeImage.createFromBuffer(svg, { scaleFactor: 1.0 });
  }
  // Mark as template so macOS adapts it for dark/light menubar automatically
  img.setTemplateImage(true);
  return img;
}

// ---------------------------------------------------------------------------
// Tray setup
// ---------------------------------------------------------------------------

function createTray() {
  tray = new Tray(createTrayIcon(true));
  tray.setToolTip('Neytreya — Perceptual Intelligence');
  tray.on('click', () => showPanel());
  tray.on('right-click', () => {
    const ctxMenu = Menu.buildFromTemplate([
      { label: 'Neytreya', enabled: false },
      { type: 'separator' },
      { label: 'Open Panel', click: () => showPanel() },
      { label: 'Open Recall', click: () => openRecallWindow() },
      { type: 'separator' },
      { label: isWatching ? 'Pause Watching' : 'Resume Watching',
        click: () => setWatchingState(!isWatching) },
      { type: 'separator' },
      { label: 'Quit Neytreya', click: () => { stopBackend(); app.quit(); } },
    ]);
    tray.popUpContextMenu(ctxMenu);
  });
}

function updateTrayIcon(open) {
  isWatching = open;
  if (tray) tray.setImage(createTrayIcon(open));
}

function setWatchingState(active) {
  isWatching = active;
  updateTrayIcon(active);
  // Tell backend to actually stop/start capturing
  try {
    const body = JSON.stringify({ watching_enabled: active });
    const req  = http.request(`http://localhost:${BACKEND_PORT}/settings`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) }
    });
    req.on('error', () => {});
    req.write(body); req.end();
  } catch (_) {}
  // Notify panel
  if (panelWindow && !panelWindow.isDestroyed()) {
    panelWindow.webContents.send('watching-state', active);
  }
}

// ---------------------------------------------------------------------------
// Panel Window
// ---------------------------------------------------------------------------

function createPanel() {
  panelWindow = new BrowserWindow({
    width: PANEL_W, height: PANEL_H,
    show: false,
    frame: false,
    transparent: true,
    resizable: false,
    movable: false,
    skipTaskbar: true,
    alwaysOnTop: true,
    vibrancy: 'under-window',
    visualEffectState: 'active',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true, nodeIntegration: false, sandbox: false,
    },
  });

  panelWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));
  panelWindow.setAlwaysOnTop(true, 'screen-saver');
  panelWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });

  // Hide when focus lost
  panelWindow.on('blur', () => {
    if (panelWindow && !panelWindow.isDestroyed()) panelWindow.hide();
  });
  panelWindow.on('closed', () => { panelWindow = null; });
}

function getPanelPosition() {
  const trayBounds   = tray.getBounds();
  const windowBounds = panelWindow.getBounds();
  const display      = screen.getDisplayMatching(trayBounds);
  const workArea     = display.workArea;

  let x, y;

  if (!trayBounds || trayBounds.width === 0 || trayBounds.y > workArea.height) {
    // Fallback if tray bounds are invalid: top right of screen
    x = workArea.x + workArea.width - windowBounds.width - 24;
    y = workArea.y + 12;
  } else {
    // Normal tray positioning
    x = Math.round(trayBounds.x + trayBounds.width / 2 - windowBounds.width / 2);
    y = trayBounds.y + trayBounds.height + 6;
  }

  // Ensure window stays within screen bounds
  x = Math.max(workArea.x + 6, Math.min(x, workArea.x + workArea.width - windowBounds.width - 6));
  y = Math.max(workArea.y + 6, Math.min(y, workArea.y + workArea.height - windowBounds.height - 6));

  return { x, y };
}

function showPanel() {
  if (!panelWindow || panelWindow.isDestroyed()) createPanel();
  const pos = getPanelPosition();
  panelWindow.setPosition(pos.x, pos.y, false);
  panelWindow.show();
  panelWindow.focus();
}

function hidePanel() {
  if (panelWindow && !panelWindow.isDestroyed()) panelWindow.hide();
}

function togglePanel() {
  if (!panelWindow || panelWindow.isDestroyed()) { showPanel(); return; }
  if (panelWindow.isVisible()) hidePanel();
  else showPanel();
}

// ---------------------------------------------------------------------------
// Observation Bubble
// ---------------------------------------------------------------------------

function createBubble() {
  bubbleWindow = new BrowserWindow({
    width: BUBBLE_W, height: BUBBLE_H,
    show: false,
    frame: false,
    transparent: true,
    resizable: false,
    movable: false,
    skipTaskbar: true,
    alwaysOnTop: true,
    focusable: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true, nodeIntegration: false, sandbox: false,
    },
  });
  bubbleWindow.loadFile(path.join(__dirname, 'renderer', 'bubble.html'));
  bubbleWindow.setAlwaysOnTop(true, 'screen-saver');
  bubbleWindow.setVisibleOnAllWorkspaces(true);
  bubbleWindow.setIgnoreMouseEvents(false);
  bubbleWindow.on('closed', () => { bubbleWindow = null; });
}

let bubbleDismissTimer = null;

function showObservationBubble(observation) {
  if (!bubbleWindow || bubbleWindow.isDestroyed()) createBubble();

  const trayBounds = tray.getBounds();
  const display    = screen.getDisplayMatching(trayBounds);
  const workArea   = display.workArea;

  let x, y;
  if (!trayBounds || trayBounds.width === 0 || trayBounds.y > workArea.height) {
    x = workArea.x + workArea.width - BUBBLE_W - 24;
    y = workArea.y + 12;
  } else {
    x = Math.min(
      trayBounds.x + trayBounds.width / 2 - BUBBLE_W / 2,
      workArea.x + workArea.width - BUBBLE_W - 10
    );
    y = trayBounds.y + trayBounds.height + 8;
  }

  bubbleWindow.setPosition(Math.round(x), Math.round(y), false);

  // Wait for load then send data
  const send = () => {
    if (bubbleWindow && !bubbleWindow.isDestroyed()) {
      bubbleWindow.webContents.send('show-observation', observation);
      bubbleWindow.showInactive();
    }
  };

  if (bubbleWindow.webContents.isLoading()) {
    bubbleWindow.webContents.once('did-finish-load', send);
  } else {
    send();
  }

  // Auto dismiss after 7 seconds
  clearTimeout(bubbleDismissTimer);
  bubbleDismissTimer = setTimeout(() => {
    if (bubbleWindow && !bubbleWindow.isDestroyed()) {
      bubbleWindow.webContents.send('dismiss-observation');
      setTimeout(() => bubbleWindow?.hide(), 400);
    }
  }, 7000);
}

// ---------------------------------------------------------------------------
// Recall Window
// ---------------------------------------------------------------------------

function openRecallWindow() {
  if (recallWindow && !recallWindow.isDestroyed()) { recallWindow.focus(); return; }
  // Show in dock while Recall is open
  app.dock?.show();
  recallWindow = new BrowserWindow({
    width: RECALL_W, height: RECALL_H, center: true,
    frame: false, transparent: false, backgroundColor: '#060e09',
    resizable: true, minWidth: 640, minHeight: 480,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true, nodeIntegration: false, sandbox: false,
    },
  });
  recallWindow.loadFile(path.join(__dirname, 'renderer', 'recall.html'));
  recallWindow.once('ready-to-show', () => { recallWindow.show(); recallWindow.focus(); });
  recallWindow.on('closed', () => {
    recallWindow = null;
    // Hide dock again when recall closes (if no other visible windows)
    if (!galleryWindow) app.dock?.hide();
  });
}

let galleryWindow = null;
function openGalleryWindow() {
  if (galleryWindow && !galleryWindow.isDestroyed()) { galleryWindow.focus(); return; }
  app.dock?.show();
  galleryWindow = new BrowserWindow({
    width: 900, height: 700, center: true,
    frame: false, transparent: false, backgroundColor: '#060e09',
    resizable: true, minWidth: 640, minHeight: 480,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true, nodeIntegration: false, sandbox: false,
    },
  });
  galleryWindow.loadFile(path.join(__dirname, 'renderer', 'gallery.html'));
  galleryWindow.once('ready-to-show', () => { galleryWindow.show(); galleryWindow.focus(); });
  galleryWindow.on('closed', () => {
    galleryWindow = null;
    if (!recallWindow) app.dock?.hide();
  });
}

// ---------------------------------------------------------------------------
// Quick Recall Overlay
// ---------------------------------------------------------------------------

function openQuickRecallWindow() {
  if (quickRecallWindow && !quickRecallWindow.isDestroyed()) { quickRecallWindow.focus(); return; }
  quickRecallWindow = new BrowserWindow({
    width: 700, height: 100, center: true,
    frame: false, transparent: true, backgroundColor: '#00000000',
    resizable: false, show: false, alwaysOnTop: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true, nodeIntegration: false, sandbox: false,
    },
  });
  
  // Center near bottom
  const { width, height } = screen.getPrimaryDisplay().workAreaSize;
  quickRecallWindow.setPosition(Math.round((width - 700) / 2), height - 200);

  quickRecallWindow.loadFile(path.join(__dirname, 'renderer', 'quick_recall.html'));
  quickRecallWindow.once('ready-to-show', () => { quickRecallWindow.show(); quickRecallWindow.focus(); });
  quickRecallWindow.on('blur', () => { if (quickRecallWindow) quickRecallWindow.close(); });
  quickRecallWindow.on('closed', () => { quickRecallWindow = null; });
}

// ---------------------------------------------------------------------------
// Onboarding Window
// ---------------------------------------------------------------------------

function openOnboarding() {
  onboardingWindow = new BrowserWindow({
    width: ONBOARD_W, height: ONBOARD_H, center: true,
    frame: false, transparent: false, backgroundColor: '#060e09',
    resizable: false, skipTaskbar: false, alwaysOnTop: false, show: false,
    titleBarStyle: 'hiddenInset',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true, nodeIntegration: false, sandbox: false,
      devTools: true,
    },
  });
  Menu.setApplicationMenu(null);
  onboardingWindow.loadFile(path.join(__dirname, 'renderer', 'onboarding.html'));
  onboardingWindow.once('ready-to-show', () => {
    onboardingWindow.show();
    onboardingWindow.focus();
  });
  onboardingWindow.on('closed', () => { onboardingWindow = null; });
}

// ---------------------------------------------------------------------------
// Setup Window
// ---------------------------------------------------------------------------

function openSetupWindow() {
  setupWindow = new BrowserWindow({
    width: 600, height: 480, center: true,
    frame: false, transparent: false, backgroundColor: '#060e09',
    resizable: false, show: false,
    titleBarStyle: 'hiddenInset',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true, nodeIntegration: false, sandbox: false,
    },
  });
  Menu.setApplicationMenu(null);
  setupWindow.loadFile(path.join(__dirname, 'renderer', 'setup.html'));
  setupWindow.once('ready-to-show', () => {
    setupWindow.show();
    setupWindow.focus();
  });
  setupWindow.on('closed', () => { setupWindow = null; });
}

// ---------------------------------------------------------------------------
// Backend
// ---------------------------------------------------------------------------

function startBackend() {
  if (process.env.NEYTREYA_EXTERNAL_BACKEND) {
    console.log('[backend] Using external backend');
    setTimeout(() => panelWindow?.webContents.send('backend-ready'), 1500);
    return;
  }

  let backendBin = null;
  if (app.isPackaged) {
    const binName = process.platform === 'win32' ? 'neytreya-backend.exe' : 'neytreya-backend';
    backendBin = path.join(process.resourcesPath, 'backend', binName);
  }

  if (backendBin && fs.existsSync(backendBin)) {
    backendProcess = spawn(backendBin, [], {
      cwd: path.dirname(backendBin), stdio: ['ignore', 'pipe', 'pipe'],
    });
  } else {
    const backendDir = path.join(__dirname, '..', 'backend');
    const venvPy     = path.join(backendDir, 'venv', 'bin', 'python3');
    const python     = fs.existsSync(venvPy) ? venvPy
                     : (process.platform === 'win32' ? 'python' : 'python3');
    try {
      backendProcess = spawn(python, ['main.py'], {
        cwd: backendDir, stdio: ['ignore', 'pipe', 'pipe'],
      });
    } catch (err) {
      console.error('[backend] Failed to spawn python3:', err.message);
      // Backend unavailable — notify UI so it can degrade gracefully
      setTimeout(() => panelWindow?.webContents.send('backend-error', { message: err.message }), 1000);
      return;
    }
  }

  backendProcess.stdout.on('data', d => {
    const t = d.toString();
    process.stdout.write(`[backend] ${t}`);
    if (t.includes('Neytreya backend ready')) panelWindow?.webContents.send('backend-ready');
  });
  backendProcess.stderr.on('data', d => process.stderr.write(`[backend-err] ${d}`));
  backendProcess.on('close', code => {
    console.log(`[backend] exited with code ${code}`);
    updateTrayIcon(false);
  });
}

function stopBackend() {
  if (backendProcess) { backendProcess.kill('SIGTERM'); backendProcess = null; }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function ensureDataDir() {
  if (!fs.existsSync(DATA_DIR)) fs.mkdirSync(DATA_DIR, { recursive: true });
}

function readSettings() {
  try {
    if (fs.existsSync(SETTINGS_FILE)) return JSON.parse(fs.readFileSync(SETTINGS_FILE, 'utf8'));
  } catch (_) {}
  return {};
}

function writeSettings(data) {
  ensureDataDir();
  // Merge with existing so auth fields (is_logged_in, user_name, etc.) are never lost
  let existing = {};
  try {
    if (fs.existsSync(SETTINGS_FILE)) existing = JSON.parse(fs.readFileSync(SETTINGS_FILE, 'utf8'));
  } catch (_) {}
  const merged = { ...existing, ...data };
  fs.writeFileSync(SETTINGS_FILE, JSON.stringify(merged, null, 2), 'utf8');
}

// App state — Electron-only flags (setup_complete, onboarding_complete)
// Kept in a SEPARATE file so the Python backend never overwrites them
function readAppState() {
  try {
    if (fs.existsSync(APP_STATE_FILE)) return JSON.parse(fs.readFileSync(APP_STATE_FILE, 'utf8'));
  } catch (_) {}
  return {};
}

function writeAppState(data) {
  ensureDataDir();
  const current = readAppState();
  fs.writeFileSync(APP_STATE_FILE, JSON.stringify({ ...current, ...data }, null, 2), 'utf8');
}

function isSetupComplete()  { return !!readAppState().setup_complete; }
function isFirstTime()      { return !readAppState().onboarding_complete; }

// ---------------------------------------------------------------------------
// System specs
// ---------------------------------------------------------------------------

function getSystemSpecs() {
  const totalMem  = os.totalmem();
  const freeMem   = os.freemem();
  const ram_gb    = Math.round(totalMem / (1024 ** 3) * 10) / 10;
  const avail_gb  = Math.round(freeMem  / (1024 ** 3) * 10) / 10;
  const platform  = process.platform;

  let is_apple_silicon = false;
  if (platform === 'darwin') {
    try {
      const cpu = execSync('sysctl -n machdep.cpu.brand_string', { timeout: 2000 }).toString().trim();
      is_apple_silicon = cpu.toLowerCase().includes('apple');
    } catch (_) {
      try { is_apple_silicon = execSync('uname -m', { timeout: 2000 }).toString().trim() === 'arm64'; } catch (_2) {}
    }
  }

  // Detect dedicated GPU VRAM (Windows only — macOS uses Unified Memory so RAM = VRAM)
  let vram_gb = null;
  if (platform === 'win32') {
    try {
      const wmicOut = execSync('wmic path win32_VideoController get AdapterRAM /value', { timeout: 3000 }).toString();
      const match = wmicOut.match(/AdapterRAM=(\d+)/);
      if (match) vram_gb = Math.round(parseInt(match[1]) / (1024 ** 3) * 10) / 10;
    } catch (_) {}
  }

  const vlTiers = [
    { model: 'qwen3-vl:30b', min_ram_gb: 22.0, label: 'Qwen3-VL 30B',  tier: 1, ram_note: '22GB+' },
    { model: 'qwen3-vl:8b',  min_ram_gb: 8.0,  label: 'Qwen3-VL 8B',   tier: 2, ram_note: '8GB+'  },
    { model: 'qwen3-vl:4b',  min_ram_gb: 4.0,  label: 'Qwen3-VL 4B',   tier: 3, ram_note: '4GB+'  },
    { model: 'qwen3-vl:2b',  min_ram_gb: 0.0,  label: 'Qwen3-VL 2B',   tier: 4, ram_note: '1GB+'  },
  ];

  // On Windows with a dedicated GPU: cap recommendation based on VRAM, not just RAM.
  // Ollama runs the model on GPU — so VRAM is the real bottleneck.
  // macOS Unified Memory machines (Apple Silicon) use total RAM correctly.
  let effective_gb = ram_gb;
  if (platform === 'win32' && vram_gb !== null && !is_apple_silicon) {
    // If VRAM < 8GB, GPU can't run 30b or 8b well — cap to safe tier
    if (vram_gb < 4)       effective_gb = Math.min(ram_gb, 3.9);  // force 2b
    else if (vram_gb < 8)  effective_gb = Math.min(ram_gb, 7.9);  // force 4b max
    else if (vram_gb < 22) effective_gb = Math.min(ram_gb, 21.9); // force 8b max
  }

  const recommended = vlTiers.find(t => effective_gb >= t.min_ram_gb) || vlTiers[vlTiers.length - 1];

  return { ram_gb, avail_gb, vram_gb, platform, is_apple_silicon, tiers: vlTiers, recommended_model: recommended.model };
}

// ---------------------------------------------------------------------------
// Ollama model pull
// ---------------------------------------------------------------------------

function installVisionModel(event, modelName) {
  return new Promise((resolve, reject) => {
    const webContents = event.sender;
    
    async function attemptPull(isRetry = false) {
      try {
        const response = await fetch('http://127.0.0.1:11434/api/pull', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: modelName })
        });
        
        if (!response.ok) {
           throw new Error(`API error: ${response.statusText}`);
        }
        
        const body = response.body;
        // In Node 18+ fetch, body is a ReadableStream or similar. We can read chunks.
        for await (const chunk of body) {
          const text = chunk.toString();
          const lines = text.split('\\n').filter(Boolean);
          for (const line of lines) {
            try {
              const data = JSON.parse(line);
              if (data.status === 'success') {
                webContents.send('ollama-pull-progress', { model: modelName, percent: 100, status: 'done' });
              } else if (data.total && data.completed) {
                const pct = Math.floor((data.completed / data.total) * 100);
                webContents.send('ollama-pull-progress', { model: modelName, percent: pct, status: 'pulling' });
              }
            } catch(e) {}
          }
        }
        resolve({ ok: true, model: modelName });
      } catch (err) {
        // Connection refused or fetch failed
        const errStr = err.message.toLowerCase() + (err.cause ? ' ' + err.cause.message.toLowerCase() : '');
        if (!isRetry && (errStr.includes('econnrefused') || errStr.includes('fetch failed'))) {
          webContents.send('ollama-pull-progress', { model: modelName, percent: 0, status: 'Starting Ollama app...' });
          const startCmd = spawn('open', ['-a', 'Ollama']);
          startCmd.on('close', () => {
            setTimeout(() => attemptPull(true), 5000);
          });
          startCmd.on('error', () => {
            reject(new Error(`Ollama app not found. Please install Ollama.`));
          });
        } else {
          reject(new Error(`Ollama pull failed: ${err.message}`));
        }
      }
    }
    
    attemptPull(false);
  });
}

// ---------------------------------------------------------------------------
// OAuth deep-link
// ---------------------------------------------------------------------------

function handleOAuthCallback(urlString) {
  try {
    const u      = new URL(urlString);
    const email  = u.searchParams.get('email')    || '';
    const name   = u.searchParams.get('username') || '';
    const slug   = u.searchParams.get('slug')     || '';
    const plan   = u.searchParams.get('plan')     || 'free';
    const existing = readSettings();
    writeSettings({ ...existing, user_email: email, user_name: name || existing.user_name,
                    user_slug: slug, user_plan: plan, auth_method: 'google', is_logged_in: true });
    const payload = { email, name, slug, plan };
    if (onboardingWindow && !onboardingWindow.isDestroyed()) onboardingWindow.webContents.send('oauth-success', payload);
    else if (panelWindow && !panelWindow.isDestroyed()) panelWindow.webContents.send('oauth-success', payload);
  } catch (err) { console.error('[auth] Failed to parse OAuth deep-link:', err); }
}

if (process.defaultApp) {
  if (process.argv.length >= 2)
    app.setAsDefaultProtocolClient(PROTOCOL, process.execPath, [path.resolve(process.argv[1])]);
} else {
  app.setAsDefaultProtocolClient(PROTOCOL);
}

const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) {
  app.quit();
} else {
  app.on('second-instance', (event, commandLine, workingDirectory) => {
    // Someone tried to run a second instance, we should focus our window.
    if (panelWindow) {
      if (panelWindow.isMinimized()) panelWindow.restore();
      panelWindow.focus();
    } else if (setupWindow) {
      if (setupWindow.isMinimized()) setupWindow.restore();
      setupWindow.focus();
    } else if (onboardingWindow) {
      if (onboardingWindow.isMinimized()) onboardingWindow.restore();
      onboardingWindow.focus();
    }
    
    // Deep linking for Windows/Linux
    const url = commandLine.find(arg => arg.startsWith(`${PROTOCOL}://`));
    if (url && url.startsWith(`${PROTOCOL}://oauth-success`)) {
      handleOAuthCallback(url);
    }
  });

  app.on('open-url', (event, urlString) => {
    event.preventDefault();
    if (urlString.startsWith(`${PROTOCOL}://oauth-success`)) handleOAuthCallback(urlString);
  });

// ---------------------------------------------------------------------------
// macOS Permissions
// ---------------------------------------------------------------------------

async function checkAndRequestPermissions() {
  if (process.platform !== 'darwin') return;
  // Don't re-prompt if user already chose Limited Mode this session
  const appState = readAppState();
  if (appState.limited_mode_accepted) return;

  const missing = [];
  const screenStatus = systemPreferences.getMediaAccessStatus('screen');
  if (screenStatus !== 'granted')
    missing.push({ id: 'screen', name: 'Screen Recording',
      reason: "To see what's on screen for OCR and context detection.",
      url: 'x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture' });
  if (!systemPreferences.isTrustedAccessibilityClient(false))
    missing.push({ id: 'accessibility', name: 'Accessibility',
      reason: 'To read which window is active and its title.',
      url: 'x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility' });
  if (missing.length === 0) {
    // Clear any stale limited_mode flag now that perms are granted
    writeAppState({ limited_mode_accepted: false });
    return;
  }
  const permLines = missing.map(p => `  •  ${p.name}\n     ${p.reason}`).join('\n\n');
  const { response } = await dialog.showMessageBox({
    type: 'warning', title: 'Neytreya — Permissions Needed',
    message: 'Neytreya needs these macOS permissions to work properly:',
    detail: `${permLines}\n\nClick "Open Privacy Settings" to grant them, then relaunch Neytreya.`,
    buttons: ['Open Privacy Settings', 'Continue in Limited Mode'],
    defaultId: 0, cancelId: 1,
  });
  if (response === 0) {
    for (const perm of missing) {
      await shell.openExternal(perm.url);
      if (perm.id === 'accessibility') systemPreferences.isTrustedAccessibilityClient(true);
    }
    // Wait a moment then re-check — user may have just toggled in System Settings
    await new Promise(r => setTimeout(r, 3000));
    const screenNow = systemPreferences.getMediaAccessStatus('screen');
    const accessNow = systemPreferences.isTrustedAccessibilityClient(false);
    if (screenNow === 'granted' && accessNow) {
      // All good, no need to quit
      writeAppState({ limited_mode_accepted: false });
      return;
    }
    await dialog.showMessageBox({ type: 'info', title: 'Neytreya',
      message: 'After granting permissions in System Preferences, relaunch Neytreya to apply them.', buttons: ['OK'] });
    return;
  }
  // User chose Limited Mode — remember so we don't nag every launch
  writeAppState({ limited_mode_accepted: true });
}

// ---------------------------------------------------------------------------
// IPC Handlers
// ---------------------------------------------------------------------------

ipcMain.handle('complete-onboarding', async (_event, data) => {
  // Save onboarding preferences to settings.json (for Python backend)
  try { writeSettings({ ...readSettings(), ...data }); } catch (err) { console.error(err); }
  // Save completion flag to app_state.json (safe from backend overwrites)
  writeAppState({ onboarding_complete: true });
  onboardingWindow?.close(); onboardingWindow = null;
  app.dock?.hide();
  createTray();
  createPanel();
  showPanel();
  startBackend();
  return { ok: true };
});

ipcMain.handle('start-google-oauth', async () => { openGoogleOAuth(); return { ok: true }; });
ipcMain.handle('get-screen-size', () => screen.getPrimaryDisplay().workAreaSize);
ipcMain.handle('save-settings', (_event, data) => { try { writeSettings(data); return { ok: true }; } catch (e) { return { ok: false, error: e.message }; } });
ipcMain.handle('load-settings', () => readSettings());

ipcMain.handle('get-login-item', () => {
  return app.getLoginItemSettings().openAtLogin;
});

ipcMain.handle('set-login-item', (_event, enabled) => {
  app.setLoginItemSettings({
    openAtLogin: enabled,
    openAsHidden: true,
    name: 'Neytreya',
  });
  return { ok: true };
});
ipcMain.on('open-rk-ai', (_event, context) => console.log('[rk-ai] context:', JSON.stringify(context)));
ipcMain.handle('open-recall', () => { openRecallWindow(); return { ok: true }; });
ipcMain.on('open-gallery', () => openGalleryWindow());
ipcMain.on('close-recall', () => { recallWindow?.close(); });
ipcMain.handle('generate-monthly-report', async () => {
  const http = require('http');
  const fetchReportData = () => new Promise(resolve => {
    http.get(`http://localhost:${BACKEND_PORT}/report/monthly`, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => resolve(JSON.parse(data)));
    }).on('error', () => resolve(null));
  });

  const data = await fetchReportData();
  if (!data) return { ok: false, error: 'Backend unreachable' };

  return new Promise(async (resolve) => {
    const { dialog } = require('electron');
    const { filePath } = await dialog.showSaveDialog({
      title: 'Save Monthly Report',
      defaultPath: path.join(app.getPath('documents'), `Neytreya_Report_${new Date().toISOString().slice(0,7)}.pdf`),
      filters: [{ name: 'PDF Documents', extensions: ['pdf'] }]
    });

    if (!filePath) { resolve({ ok: false, error: 'Cancelled' }); return; }

    const reportWin = new BrowserWindow({
      width: 800, height: 1000, show: false,
      webPreferences: { nodeIntegration: true, contextIsolation: false }
    });

    // Create a temporary HTML file for the report
    const htmlContent = `
      <html>
      <head>
        <style>
          body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #333; padding: 40px; }
          h1 { color: #10b981; border-bottom: 2px solid #eee; padding-bottom: 10px; }
          .stat { margin: 10px 0; font-size: 18px; }
          .stat b { display: inline-block; width: 150px; }
          .card { background: #f9f9f9; padding: 20px; border-radius: 8px; margin-top: 20px; }
        </style>
      </head>
      <body>
        <h1>Neytreya Monthly Report</h1>
        <p>Prepared on ${new Date().toLocaleDateString()}</p>
        <div class="stat"><b>Focus Time:</b> ${data.focus_time}</div>
        <div class="stat"><b>Stuck Events:</b> ${data.stuck_events}</div>
        
        <div class="card">
          <h2>Top Apps</h2>
          <ul>${data.app_usage.map(a => `<li>${a.name}: ${a.hours}h</li>`).join('')}</ul>
        </div>

        <div class="card">
          <h2>Top Websites</h2>
          <ul>${data.top_websites.map(w => `<li>${w}</li>`).join('')}</ul>
        </div>

        <div class="card">
          <h2>Insights</h2>
          <p>${data.insights}</p>
        </div>
      </body>
      </html>
    `;
    
    const tempHtml = path.join(app.getPath('temp'), 'neytreya_report_temp.html');
    fs.writeFileSync(tempHtml, htmlContent, 'utf8');

    await reportWin.loadFile(tempHtml);
    
    try {
      const pdf = await reportWin.webContents.printToPDF({});
      fs.writeFileSync(filePath, pdf);
      resolve({ ok: true });
    } catch (e) {
      resolve({ ok: false, error: e.message });
    } finally {
      reportWin.close();
      try { fs.unlinkSync(tempHtml); } catch(e){}
    }
  });
});

ipcMain.handle('check-screen-permission', () => {
  return process.platform === 'darwin' ? systemPreferences.getMediaAccessStatus('screen') === 'granted' : true;
});

// ── Open snapshot in system image viewer (Preview on macOS) ─────────────────
ipcMain.handle('open-snapshot', async (_event, filename) => {
  try {
    const os  = require('os');
    const http = require('http');
    const tmpPath = path.join(os.tmpdir(), `neytreya_snap_${Date.now()}.webp`);
    await new Promise((resolve, reject) => {
      const file = fs.createWriteStream(tmpPath);
      http.get(`http://localhost:${BACKEND_PORT}/recall/snapshot/${encodeURIComponent(filename)}`, (res) => {
        res.pipe(file);
        file.on('finish', () => { file.close(); resolve(); });
      }).on('error', reject);
    });
    await shell.openPath(tmpPath);
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e.message };
  }
});

ipcMain.handle('request-screen-permission', async () => {
  if (process.platform !== 'darwin') return true;
  if (systemPreferences.getMediaAccessStatus('screen') === 'granted') return true;
  try {
    const { desktopCapturer } = require('electron');
    await desktopCapturer.getSources({ types: ['screen'] });
  } catch (e) {}
  return systemPreferences.getMediaAccessStatus('screen') === 'granted';
});

ipcMain.handle('detect-system-specs', () => getSystemSpecs());
ipcMain.handle('install-vision-model', (event, modelName) => installVisionModel(event, modelName));

ipcMain.handle('run-setup-step', async (event, step) => {
  return new Promise(async (resolve) => {
    try {
      const backendDir = path.join(__dirname, '..', 'backend');
      const sendLog = (msg) => { if (event.sender) event.sender.send('setup-log', msg); };
      
      let cmd = '';
      if (step === 'python') {
        if (app.isPackaged) {
          sendLog("Checking built-in Python environment...");
          setTimeout(() => resolve({ok: true}), 1500);
          return;
        } else {
          cmd = process.platform === 'win32'
            ? `python -m venv venv && .\\venv\\Scripts\\pip install -q -r requirements.txt`
            : `python3 -m venv venv && source venv/bin/activate && pip install -q -r requirements.txt`;
        }
      } else if (step === 'tesseract') {
        if (process.platform === 'darwin') {
          cmd = `if ! command -v tesseract &> /dev/null; then if command -v brew &> /dev/null; then HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_INTERACTIVE=1 brew install tesseract -y; fi; fi`;
        } else {
          sendLog("Tesseract check skipped on Windows");
          setTimeout(() => resolve({ok: true}), 1000);
          return;
        }
      } else if (step === 'ollama') {
        const specs = getSystemSpecs();
        const model = specs.recommended_model || 'qwen3-vl:2b';
        sendLog(`Selected vision model based on system: ${model}`);
        sendLog(`Ensuring Ollama and model are ready...`);
        cmd = `ollama run ${model} "hi" || echo "Failed to pull ollama"`;
      } else if (step === 'tts') {
        // TTS (Kokoro) is lazy-loaded by the backend on first use — nothing to install here
        sendLog('Kokoro TTS: will be loaded on first use by the backend.');
        sendLog('No installation required — voices are bundled.');
        setTimeout(() => resolve({ ok: true }), 800);
        return;
      } else if (step === 'rexycore') {
        // RexyCore bootstrap copies bundled SDK — just verify the .rxc folder exists
        const rxcDir = path.join(__dirname, '..', 'backend', '.rxc');
        const fs = require('fs');
        if (fs.existsSync(rxcDir)) {
          sendLog('RexyCore SDK bundle found.');
        } else {
          sendLog('RexyCore SDK not bundled — cloud features will be unavailable offline.');
        }
        setTimeout(() => resolve({ ok: true }), 600);
        return;
      }

      if (!cmd) { resolve({ok: true}); return; }

      const child = exec(cmd, { cwd: backendDir });
      child.stdout.on('data', data => sendLog(data.toString()));
      child.stderr.on('data', data => sendLog(data.toString()));
      child.on('close', code => {
        if (code === 0) resolve({ ok: true });
        else resolve({ ok: false, error: `Process exited with code ${code}` });
      });
    } catch (e) {
      resolve({ ok: false, error: e.message });
    }
  });
});

ipcMain.handle('finish-setup', async (_event, data = {}) => {
  writeAppState({ setup_complete: true });
  // Save any preferences from setup (e.g. vision_enabled)
  if (Object.keys(data).length > 0) {
    try { writeSettings({ ...readSettings(), ...data }); } catch(e) {}
  }
  setupWindow?.close();
  setupWindow = null;
  if (isFirstTime()) {
    openOnboarding();
  } else {
    app.dock?.hide();
    createTray();
    createPanel();
    startBackend();
  }
  return { ok: true };
});

ipcMain.handle('fetch-recall', async (_event, { type, query }) => {
  const http = require('http');
  return new Promise((resolve) => {
    let url = `http://localhost:${BACKEND_PORT}/recall/${type}`;
    if (query) url += `?q=${encodeURIComponent(query)}`;
    http.get(url, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => { try { resolve(JSON.parse(data)); } catch { resolve({}); } });
    }).on('error', (err) => resolve({ error: err.message }));
  });
});

// Dismiss bubble
ipcMain.on('dismiss-bubble', () => {
  clearTimeout(bubbleDismissTimer);
  if (bubbleWindow && !bubbleWindow.isDestroyed()) {
    bubbleWindow.webContents.send('dismiss-observation');
    setTimeout(() => bubbleWindow?.hide(), 400);
  }
});

// Receive observation from panel (which gets it from WS) → show bubble
ipcMain.on('show-observation-bubble', (_event, obs) => {
  showObservationBubble(obs);
  updateTrayIcon(true);
});

// Tray state control
ipcMain.on('set-watching', (_event, active) => setWatchingState(active));

ipcMain.on('set-audio-recall', (_event, active) => {
  const http = require('http');
  const req = http.request(`http://localhost:${BACKEND_PORT}/settings/audio-recall`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' }
  }, () => {});
  req.on('error', (err) => console.error('Audio recall toggle error:', err));
  req.write(JSON.stringify({ enabled: active }));
  req.end();
});

ipcMain.handle('close-quick-recall', () => {
  quickRecallWindow?.close();
});

function openGoogleOAuth() {
  const successPath = encodeURIComponent('/desktop/oauth-success?product=neytreya');
  shell.openExternal(`${ARKIS_URL}/login?redirect=${successPath}`);
}

// ---------------------------------------------------------------------------
// App Lifecycle
// ---------------------------------------------------------------------------

app.whenReady().then(async () => {
  autoUpdater.checkForUpdatesAndNotify().catch(e => console.error("Auto-updater failed:", e));
  ensureDataDir();
  // Dock stays visible during setup/onboarding so user sees the app is running
  await checkAndRequestPermissions();

  if (!isSetupComplete()) {
    openSetupWindow(); // backend starts after setup + onboarding
  } else if (isFirstTime()) {
    openOnboarding(); // backend starts after onboarding completes
  } else {
    // Already fully set up — hide dock, start tray, backend, panel
    app.dock?.hide();
    createTray();
    createPanel();
    startBackend();
    // Pop open the panel if launched manually (not at login)
    const loginSettings = app.getLoginItemSettings();
    if (!loginSettings.wasOpenedAtLogin && !process.argv.includes('--hidden')) {
      setTimeout(() => showPanel(), 300);
    }
  }

  // Register Global Shortcut for Quick Recall Overlay
  globalShortcut.register('Option+M', () => {
    if (quickRecallWindow && !quickRecallWindow.isDestroyed()) {
      quickRecallWindow.close();
    } else {
      openQuickRecallWindow();
    }
  });
});

app.on('will-quit', () => {
  globalShortcut.unregisterAll();
});

app.on('window-all-closed', () => {
  // Don't quit when all windows close — we live in the menubar
});

app.on('before-quit', stopBackend);

} // end of requestSingleInstanceLock block
