'use strict';

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('neytreya', {
  /** Toggle window mouse interactivity */
  setInteractive: (val) => ipcRenderer.send('set-interactive', val),

  /** Get primary display work area size */
  getScreenSize: () => ipcRenderer.invoke('get-screen-size'),

  /** Persist settings to disk */
  saveSettings: (settings) => ipcRenderer.invoke('save-settings', settings),

  /** Load settings from disk */
  loadSettings: () => ipcRenderer.invoke('load-settings'),

  /** Send context to RK AI */
  openRkAi: (context) => ipcRenderer.send('open-rk-ai', context),

  /** Called when Python backend signals it is ready */
  onBackendReady: (cb) => ipcRenderer.on('backend-ready', (_event) => cb()),

  /** Complete onboarding — saves data and launches main window */
  completeOnboarding: (data) => ipcRenderer.invoke('complete-onboarding', data),

  // ── Google OAuth ──────────────────────────────────────────────────────────

  /** Open the Arkis Google OAuth popup. Returns immediately. */
  startGoogleOAuth: () => ipcRenderer.invoke('start-google-oauth'),

  /** Register a callback for when OAuth completes and the deep-link fires. */
  onOAuthSuccess: (cb) => {
    const handler = (_event, payload) => cb(payload);
    ipcRenderer.on('oauth-success', handler);
    return () => ipcRenderer.removeListener('oauth-success', handler);
  },

  // ── System & Model Installation ───────────────────────────────────────────

  /** Check macOS screen recording permission */
  checkScreenPermission: () => ipcRenderer.invoke('check-screen-permission'),

  /** Request macOS screen recording permission */
  requestScreenPermission: () => ipcRenderer.invoke('request-screen-permission'),

  /** Detect system specs: RAM, platform, Apple Silicon, model tiers */
  detectSystemSpecs: () => ipcRenderer.invoke('detect-system-specs'),

  /** Pull an Ollama model. Returns Promise<{ok, model}>. */
  installVisionModel: (modelName) => ipcRenderer.invoke('install-vision-model', modelName),

  /** Register a callback for Ollama pull progress updates */
  onOllamaProgress: (cb) => {
    const handler = (_event, data) => cb(data);
    ipcRenderer.on('ollama-pull-progress', handler);
    return () => ipcRenderer.removeListener('ollama-pull-progress', handler);
  },
  
  /** First-time setup step execution */
  runSetupStep: (step, onLog) => {
    const logHandler = (_event, msg) => onLog(msg);
    ipcRenderer.on('setup-log', logHandler);
    return ipcRenderer.invoke('run-setup-step', step).finally(() => {
      ipcRenderer.removeListener('setup-log', logHandler);
    });
  },
  
  /** Mark setup as complete and continue launch */
  finishSetup: (data = {}) => ipcRenderer.invoke('finish-setup', data),

  // ── Recall ────────────────────────────────────────────────────────────────

  /** Open the dedicated Recall window */
  openRecall: () => ipcRenderer.invoke('open-recall'),

  /** Generate monthly report PDF */
  generateMonthlyReport: () => ipcRenderer.invoke('generate-monthly-report'),

  /** Close the recall window (called from within it) */
  closeRecall: () => ipcRenderer.send('close-recall'),

  /** Fetch recall data from backend. type: 'recent'|'today'|'yesterday'|'search' */
  fetchRecall: (type, query) => ipcRenderer.invoke('fetch-recall', { type, query }),

  // ── Quick Recall ──────────────────────────────────────────────────────────
  closeQuickRecall: () => ipcRenderer.invoke('close-quick-recall'),
  queryQuickRecall: (q) => ipcRenderer.invoke('fetch-recall', { type: 'quick', query: q }),

  // ── Observation Bubble ────────────────────────────────────────────────────

  triggerBubble: (obs) => ipcRenderer.send('show-observation-bubble', obs),
  dismissBubble: () => ipcRenderer.send('dismiss-bubble'),
  onShowObservation: (cb) => ipcRenderer.on('show-observation', (_event, obs) => cb(obs)),
  onDismissObservation: (cb) => ipcRenderer.on('dismiss-observation', () => cb()),

  // ── Tray State ────────────────────────────────────────────────────────────

  setWatching: (active) => ipcRenderer.send('set-watching', active),
  setAudioRecall: (active) => ipcRenderer.send('set-audio-recall', active),
  onWatchingState: (cb) => ipcRenderer.on('watching-state', (_event, active) => cb(active)),

  // ── Startup ──────────────────────────────────────────────────────────────

  /** Get whether app launches at login */
  getLoginItem: () => ipcRenderer.invoke('get-login-item'),

  /** Set whether app launches at login */
  setLoginItem: (enabled) => ipcRenderer.invoke('set-login-item', enabled),
});
