'use strict';

// ── Elements ────────────────────────────────────────────────────────────────
const wsStatusText    = document.getElementById('ws-status');
const authStatusText  = document.getElementById('auth-status-text');

const liveApp         = document.getElementById('live-app');
const liveActivity    = document.getElementById('live-activity');
const liveTime        = document.getElementById('live-time');
const liveWindow      = document.getElementById('live-window');

const statusVision    = document.getElementById('status-vision');
const statusVisDesc   = document.getElementById('status-vision-desc');

const obsList         = document.getElementById('obs-list');
const btnClearObs     = document.getElementById('btn-clear-obs');
const recallMiniList  = document.getElementById('recall-mini-list');
const btnOpenRecall   = document.getElementById('btn-open-recall');

const tabBtns         = document.querySelectorAll('.tab-btn');
const tabPanes        = document.querySelectorAll('.tab-pane');

const recallChatInput = document.getElementById('recall-chat-input');
const recallChatResp = document.getElementById('recall-chat-response');
if (recallChatInput) {
  recallChatInput.addEventListener('keydown', async (e) => {
    if (e.key === 'Enter' && recallChatInput.value.trim() !== '') {
      const query = recallChatInput.value.trim();
      recallChatInput.value = '';
      if (recallChatResp) recallChatResp.textContent = 'Thinking...';
      try {
        const res = await fetch(`http://127.0.0.1:7432/recall/chat`, {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ prompt: query })
        });
        const data = await res.json();
        if (data.ok && data.response) {
          if (recallChatResp) recallChatResp.textContent = data.response;
          fetch(`http://127.0.0.1:7432/tts/speak`, {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ text: data.response })
          }).catch(console.error);
        } else {
          if (recallChatResp) recallChatResp.textContent = 'Error: ' + (data.error || 'Failed to chat');
        }
      } catch (err) {
        if (recallChatResp) recallChatResp.textContent = 'Network error talking to AI.';
      }
    }
  });
}

const toggleWatching  = document.getElementById('toggle-watching');
const toggleOcr       = document.getElementById('toggle-ocr');
const toggleVision    = document.getElementById('toggle-vision');
const toggleAudioRecall= document.getElementById('toggle-audio-recall');
const toggleIndexing  = document.getElementById('toggle-indexing');
const toggleLoginItem = document.getElementById('toggle-login-item');
const blockedAppsInp  = document.getElementById('blocked-apps');
const btnSaveSettings = document.getElementById('btn-save-settings');

const btnMonthlyReport = document.getElementById('btn-monthly-report');
const btnUpgradePro    = document.getElementById('btn-upgrade-pro');
const ttsVoiceSel      = document.getElementById('tts-voice');

let ws = null;
let observations = [];

// Resource event log — tracks threshold crossings with timestamps
const resourceLog = [];
const RES_MAX_LOG = 20;
let lastCpuHigh = false;
let lastRamHigh = false;
let lastBatLow  = false;

// Live clock
setInterval(() => {
  const now = new Date();
  const h = String(now.getHours()).padStart(2,'0');
  const m = String(now.getMinutes()).padStart(2,'0');
  const s = String(now.getSeconds()).padStart(2,'0');
  if (liveTime) liveTime.textContent = `${h}:${m}:${s}`;
}, 1000);

// ── Tab Routing ─────────────────────────────────────────────────────────────
tabBtns.forEach(btn => {
  btn.addEventListener('click', () => {
    tabBtns.forEach(b => b.classList.remove('active'));
    tabPanes.forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(btn.dataset.target).classList.add('active');
    if (btn.dataset.target === 'tab-recall') updateRecallPreview();
  });
});

// ── Init & State ────────────────────────────────────────────────────────────
async function init() {
  const settings = (await window.neytreya.loadSettings()) || {};
  // Auth
  authStatusText.textContent = settings.is_logged_in
    ? `Logged in as ${settings.user_name || settings.user_email || 'you'}`
    : 'Not Logged In';

  // Restore toggle states from persisted settings
  if (toggleWatching)    toggleWatching.checked  = settings.watching_enabled !== false;
  if (toggleOcr)         toggleOcr.checked        = settings.ocr_enabled !== false;
  if (toggleVision)      toggleVision.checked     = settings.enable_vision === true;
  if (toggleAudioRecall) toggleAudioRecall.checked = settings.enable_audio_recall === true;
  if (toggleIndexing)    toggleIndexing.checked   = settings.enable_indexing !== false;
  if (settings.blocked_apps) blockedAppsInp.value = settings.blocked_apps;
  if (settings.tts_voice) ttsVoiceSel.value = settings.tts_voice;

  if (window.neytreya.getLoginItem) {
    toggleLoginItem.checked = await window.neytreya.getLoginItem();
  }

  if (window.neytreya.onBackendReady) {
    window.neytreya.onBackendReady(connectWS);
  } else {
    connectWS();
  }

  updateRecallPreview();
}

// ── Websocket Connection ────────────────────────────────────────────────────
let wsRetryDelay = 2000;
let wsRetryTimer = null;

function connectWS() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
  if (ws) { try { ws.close(); } catch(_) {} ws = null; }

  wsStatusText.textContent = 'CONNECTING...';
  wsStatusText.className = 'footer-status';

  ws = new WebSocket('ws://127.0.0.1:7432/ws');

  ws.onopen = () => {
    wsRetryDelay = 2000; // reset on successful connect
    wsStatusText.textContent = 'SYSTEM ONLINE';
    wsStatusText.className = 'footer-status ok';
  };

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === 'perception_update') {
        const state = {
          active_app: msg.perception?.active_app,
          window_title: msg.perception?.window_title,
          time_in_app_str: msg.perception?.time_in_app_str,
          predicted_activity: msg.context?.activity,
          stuck_app: msg.inference?.stuck_app,
          cpu_percent: msg.perception?.cpu_percent,
          ram_percent: msg.perception?.ram_percent,
          battery_percent: msg.perception?.battery_percent,
          battery_plugged: msg.perception?.battery_plugged,
          load_tier: msg.perception?.load_tier,
        };
        updateLiveState(state);
        updateResources(state);
        if (msg.observations && Array.isArray(msg.observations)) {
          observations = msg.observations;
          renderObservations();
        }
      }
      if (msg.type === 'state') updateLiveState(msg.data);
      if (msg.type === 'observation') handleObservation(msg.data);
      if (msg.type === 'recall_summary') {
        const d = msg;
        const sumEl = document.getElementById('recall-last-summary');
        if (sumEl) {
          sumEl.innerHTML = `
            <div>${esc(d.summary)}</div>
            ${d.transcript ? `<div style="font-size: 11px; margin-top: 4px; color: var(--tx-2); font-style: italic;">🎧 "${esc(d.transcript)}"</div>` : ''}
            <div class="recall-summary-meta">
              ${esc(d.time)} \u00b7 ${esc(d.app || 'Unknown')}
            </div>
          `;
        }
        
        // Prepend a new thumb to the strip without full reload
        const stripEl = document.getElementById('recall-timeline-strip');
        if (stripEl && d.snapshot) {
          const baseName = d.snapshot.split('/').pop();
          const snapUrl = `http://127.0.0.1:7432/recall/snapshot/${encodeURIComponent(baseName)}`;
          const thumbHtml = `<div class="recall-thumb" onclick="showRecallOverlay('${baseName}')">
            <img src="${snapUrl}" />
            <div class="recall-thumb-time">${esc(d.time)}</div>
          </div>`;
          stripEl.insertAdjacentHTML('afterbegin', thumbHtml);
        }
        // Blink live dot
        const dot = document.getElementById('recall-live-dot');
        if (dot) {
          dot.style.display = 'inline-block';
          setTimeout(() => dot.style.display = 'none', 3000);
        }
        // Force refresh timeline to show the new snapshot
        fetchActiveTimeline();
      }
    } catch (e) {
      console.warn('WS parse error:', e);
    }
  };

  ws.onerror = () => {
    // suppress error log — onclose will handle retry
  };

  ws.onclose = () => {
    ws = null;
    wsStatusText.textContent = 'OFFLINE';
    wsStatusText.className = 'footer-status offline';
    // Exponential backoff: 2s → 4s → 8s → max 15s
    wsRetryDelay = Math.min(wsRetryDelay * 1.5, 15000);
    clearTimeout(wsRetryTimer);
    wsRetryTimer = setTimeout(connectWS, wsRetryDelay);
  };
}

// ── Updates  // Vision Engine status — 3 states
function updateLiveState(state) {
  if (state.stuck_app) {
    liveApp.textContent = `${state.stuck_app} (Stuck)`;
    liveApp.style.color = '#f87171';
  } else if (state.active_app) {
    liveApp.textContent = state.active_app;
    liveApp.style.color = 'var(--tx-3)';
  }
  
  if (state.predicted_activity) liveActivity.textContent = state.predicted_activity;
  if (state.window_title)       liveWindow.textContent = state.window_title;

  if (!toggleWatching || !toggleWatching.checked) {
    statusVision.textContent = 'PAUSED';
    statusVision.className = 's-status';
    statusVision.style.color = 'var(--tx-3)';
    statusVisDesc.textContent = 'Watching is paused. Flip the Active Watching toggle to resume.';
  } else if (!toggleVision || !toggleVision.checked) {
    // OCR might still be on — tell the user what IS working
    const ocrOn = toggleOcr && toggleOcr.checked;
    statusVision.textContent = ocrOn ? 'OCR ONLY' : 'INACTIVE';
    statusVision.className = 's-status';
    statusVision.style.color = ocrOn ? 'var(--tx-2)' : 'var(--tx-3)';
    statusVisDesc.textContent = ocrOn
      ? 'Reading screen text. AI Vision (Ollama) is off.'
      : 'Screen reading is off. Enable OCR or AI Vision in Settings.';
  } else {
    statusVision.textContent = 'ONLINE';
    statusVision.className = 's-status ok';
    statusVision.style.color = 'var(--em)';
    statusVisDesc.textContent = 'Monitoring screen for context and errors.';
  }
}

function fmtTime(d) {
  return d.toLocaleTimeString('en-US', { hour:'2-digit', minute:'2-digit' });
}

function pushLog(msg, level='info') {
  const ts = fmtTime(new Date());
  resourceLog.unshift({ ts, msg, level });
  if (resourceLog.length > RES_MAX_LOG) resourceLog.pop();
  renderResourceLog();
}

function renderResourceLog() {
  const el = document.getElementById('res-log');
  if (!el) return;
  if (resourceLog.length === 0) {
    el.innerHTML = '<div class="res-log-empty">Monitoring resources... events will appear here.</div>';
    return;
  }
  el.innerHTML = resourceLog.map(e => {
    const cls = e.level === 'warn' ? 'res-log-warn' : e.level === 'ok' ? 'res-log-ok' : '';
    return `<div class="res-log-row ${cls}"><span class="res-log-ts">${e.ts}</span><span>${esc(e.msg)}</span></div>`;
  }).join('');
}

async function fetchActiveTimeline() {
  try {
    const res = await fetch('http://127.0.0.1:7432/recall/active-timeline');
    if (!res.ok) return;
    const data = await res.json();
    
    // Update last summary
    if (data.summaries && data.summaries.length > 0) {
      const sum = data.summaries[data.summaries.length - 1];
      const sumEl = document.getElementById('recall-last-summary');
      if (sumEl) {
        sumEl.innerHTML = `
          <div>${esc(sum.summary)}</div>
          ${sum.transcript ? `<div style="font-size: 11px; margin-top: 4px; color: var(--tx-2); font-style: italic;">🎧 "${esc(sum.transcript)}"</div>` : ''}
          <div class="recall-summary-meta">
            ${esc(sum.timestamp.substring(11, 16))} \u00b7 ${esc(sum.app || 'Unknown')}
          </div>
        `;
      }
    }

    // Update strip
    const stripEl = document.getElementById('recall-timeline-strip');
    if (stripEl && data.snapshots && data.snapshots.length > 0) {
      stripEl.innerHTML = data.snapshots.reverse().map(snap => {
        const baseName = snap.filename.split('/').pop();
        return `
        <div class="recall-thumb" onclick="showRecallOverlay('${baseName}')">
          <img src="http://127.0.0.1:7432/recall/snapshot/${encodeURIComponent(baseName)}" />
          <div class="recall-thumb-time">${esc(snap.time || '')}</div>
        </div>
      `}).join('');
    } else if (stripEl) {
      stripEl.innerHTML = '<div class="recall-mini-empty">No visual timeline yet today...</div>';
    }
  } catch(e) {}
}

function showRecallOverlay(filename) {
  const div = document.createElement('div');
  div.className = 'recall-overlay';
  div.innerHTML = `
    <button class="recall-overlay-close" onclick="this.parentElement.remove()">\u00d7</button>
    <img src="http://127.0.0.1:7432/recall/snapshot/${encodeURIComponent(filename)}">
  `;
  document.body.appendChild(div);
  div.onclick = (e) => { if (e.target === div) div.remove(); };
}

function updateResources(state) {
  const cpu = state.cpu_percent ?? null;
  const ram = state.ram_percent ?? null;
  const bat = state.battery_percent ?? null;
  const plugged = state.battery_plugged;
  const tier = state.load_tier || 'LOW';

  // Update bars
  const cpuBar = document.getElementById('res-cpu-bar');
  const ramBar = document.getElementById('res-ram-bar');
  const batBar = document.getElementById('res-bat-bar');
  const cpuVal = document.getElementById('res-cpu-val');
  const ramVal = document.getElementById('res-ram-val');
  const batVal = document.getElementById('res-bat-val');
  const batRow = document.getElementById('res-battery-row');
  const tierEl = document.getElementById('res-load-tier');

  if (cpu !== null && cpuBar && cpuVal) {
    cpuBar.style.width = cpu + '%';
    cpuBar.style.background = cpu > 80 ? '#f87171' : cpu > 50 ? '#fbbf24' : 'var(--em)';
    cpuVal.textContent = Math.round(cpu) + '%';
  }
  if (ram !== null && ramBar && ramVal) {
    ramBar.style.width = ram + '%';
    ramBar.style.background = ram > 85 ? '#f87171' : ram > 65 ? '#fbbf24' : 'var(--em)';
    ramVal.textContent = Math.round(ram) + '%';
  }
  if (bat !== null && batRow && batBar && batVal) {
    batRow.style.display = 'flex';
    batBar.style.width = bat + '%';
    batBar.style.background = bat < 20 ? '#f87171' : bat < 40 ? '#fbbf24' : 'var(--em)';
    batVal.textContent = Math.round(bat) + '%' + (plugged ? ' ⚡' : '');
  }
  if (tierEl) {
    tierEl.textContent = tier;
    tierEl.style.color = tier === 'HIGH' ? '#f87171' : tier === 'MEDIUM' ? '#fbbf24' : 'var(--em)';
  }

  // Event detection — push to log on threshold crossing
  const cpuHigh = cpu !== null && cpu > 75;
  const ramHigh = ram !== null && ram > 80;
  const batLow  = bat !== null && bat < 20 && !plugged;

  if (cpuHigh && !lastCpuHigh) pushLog(`CPU spiked to ${Math.round(cpu)}% — system under heavy load.`, 'warn');
  if (!cpuHigh && lastCpuHigh) pushLog(`CPU load dropped back to normal (${Math.round(cpu)}%).`, 'ok');
  if (ramHigh && !lastRamHigh) pushLog(`RAM usage reached ${Math.round(ram)}% — memory pressure detected.`, 'warn');
  if (!ramHigh && lastRamHigh) pushLog(`RAM pressure eased (${Math.round(ram)}%).`, 'ok');
  if (batLow  && !lastBatLow)  pushLog(`Battery at ${Math.round(bat)}% — plug in soon.`, 'warn');
  if (!batLow  && lastBatLow)  pushLog(`Battery status returned to safe range.`, 'ok');

  lastCpuHigh = cpuHigh;
  lastRamHigh = ramHigh;
  lastBatLow  = batLow;
}

function handleObservation(obs) {
  window.neytreya.triggerBubble(obs);
  observations.unshift(obs);
  if (observations.length > 10) observations.pop();
  renderObservations();
}

function renderObservations() {
  if (observations.length === 0) {
    obsList.innerHTML = '<div class="obs-empty">No observations yet. Leave Neytreya running in the background.</div>';
    return;
  }
  obsList.innerHTML = observations.map(o => {
    const isErr = !!o.is_error;
    return `<div class="obs-item ${isErr ? 'error' : ''}">${esc(o.message || o.text)}</div>`;
  }).join('');
}

btnClearObs.addEventListener('click', () => { observations = []; renderObservations(); });

// ── Recall ──────────────────────────────────────────────────────────────────
btnOpenRecall.addEventListener('click', () => window.neytreya.openRecall());

async function updateRecallPreview() {
  try {
    const data = await window.neytreya.fetchRecall('recent');
    
    // Deduplicate consecutive identical apps
    const rawEntries = data.entries || [];
    const uniqueEntries = [];
    for (const e of rawEntries) {
      if (uniqueEntries.length === 0 || uniqueEntries[uniqueEntries.length - 1].app !== e.app) {
        uniqueEntries.push(e);
      }
    }
    const entries = uniqueEntries.slice(0, 5);

    if (entries.length === 0) {
      recallMiniList.innerHTML = '<div class="recall-mini-empty">No recent memories yet.</div>';
      return;
    }

    recallMiniList.innerHTML = entries.map(e => `
      <div class="recall-mini-row">
        <div class="recall-mini-icon"><div class="rmi-pulse"></div></div>
        <span class="recall-mini-name">${esc(e.app || '—')}</span>
        <span class="recall-mini-time">${esc(e.time || '')}</span>
      </div>
    `).join('');
  } catch (err) {
    console.warn('Recall preview load failed:', err);
  }
}

// ── Settings ────────────────────────────────────────────────────────────────
toggleWatching.addEventListener('change', (e) => {
  const active = e.target.checked;
  window.neytreya.setWatching(active);
  if (!active) {
    liveApp.textContent = 'Paused';
    liveActivity.textContent = 'Observation is currently suspended.';
    liveApp.style.color = 'var(--tx-3)';
  }
  updateLiveState({});
});

if (toggleAudioRecall) {
  toggleAudioRecall.addEventListener('change', (e) => {
    window.neytreya.setAudioRecall(e.target.checked);
  });
}

btnSaveSettings.addEventListener('click', async () => {
  const settings = (await window.neytreya.loadSettings()) || {};
  settings.watching_enabled      = toggleWatching ? toggleWatching.checked : true;
  settings.ocr_enabled           = toggleOcr ? toggleOcr.checked : true;
  settings.enable_vision         = toggleVision ? toggleVision.checked : false;
  settings.enable_audio_recall   = toggleAudioRecall ? toggleAudioRecall.checked : false;
  settings.enable_indexing       = toggleIndexing ? toggleIndexing.checked : true;
  settings.blocked_apps          = blockedAppsInp.value;
  settings.tts_voice             = ttsVoiceSel.value;

  await window.neytreya.saveSettings(settings);
  if (window.neytreya.setLoginItem) {
    await window.neytreya.setLoginItem(toggleLoginItem.checked);
  }
  btnSaveSettings.textContent = 'Saved!';
  setTimeout(() => btnSaveSettings.textContent = 'Save Settings', 2000);
  
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'settings_update', data: settings }));
  }

  // Notify backend to start/stop audio capture
  try {
    const isAudioOn = toggleAudioRecall.checked;
    if (isAudioOn) {
      document.getElementById('audio-recall-desc').textContent = "Starting transcription engine... (may download models)";
    }
    await fetch('http://127.0.0.1:7432/settings/audio-recall', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: isAudioOn })
    });
    if (isAudioOn) {
      document.getElementById('audio-recall-desc').textContent = "Audio Recall is active. Transcribing live audio.";
    } else {
      document.getElementById('audio-recall-desc').textContent = "Transcribe speaker audio (Hindi+English). Downloads ~150MB Whisper model on first use.";
    }
  } catch (err) {
    console.error("Failed to toggle audio recall:", err);
  }

  updateLiveState({});
});

if (btnMonthlyReport) {
  btnMonthlyReport.addEventListener('click', async () => {
    btnMonthlyReport.textContent = 'Generating...';
    btnMonthlyReport.disabled = true;
    const res = await window.neytreya.generateMonthlyReport();
    btnMonthlyReport.textContent = res.ok ? 'Report Saved!' : 'Error Generating';
    setTimeout(() => {
      btnMonthlyReport.textContent = 'Generate Monthly Report (PDF)';
      btnMonthlyReport.disabled = false;
    }, 3000);
  });
  const btnTimelineRefresh = document.getElementById('recall-timeline-refresh');
  if (btnTimelineRefresh) {
    btnTimelineRefresh.addEventListener('click', () => {
      btnTimelineRefresh.style.opacity = '0.5';
      fetchActiveTimeline().then(() => {
        btnTimelineRefresh.style.opacity = '1';
      });
    });
  }

  fetchActiveTimeline();
  connectWS();
}

// Pro upgrade button is disabled (Coming Soon) — no click handler needed.

// ── Helpers ─────────────────────────────────────────────────────────────────
function esc(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

init();
