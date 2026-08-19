'use strict';

const $ = id => document.getElementById(id);
const contentArea = $('content-area');
const searchInp   = $('search-inp');
const viewTitle   = $('view-title');

let activeTab = 'recent';

// ── CSS Bubble Icon Library ───────────────────────────────────────────────
// Returns HTML string for a CSS-only animated icon, no emojis.
function bblIcon(type, extra = '') {
  const cls = `bbl ${extra}`.trim();
  switch (type) {
    case 'code':
      return `<div class="${cls}"><div class="ic-activity"><div class="ic-bar"></div><div class="ic-bar"></div><div class="ic-bar"></div></div></div>`;
    case 'browser':
      return `<div class="${cls}"><div class="ic-browser"></div></div>`;
    case 'design':
      return `<div class="${cls}"><div class="ic-diamond"></div></div>`;
    case 'terminal':
      return `<div class="${cls}"><div class="ic-terminal"></div></div>`;
    case 'folder':
      return `<div class="${cls}"><div class="ic-folder"></div></div>`;
    case 'error':
      return `<div class="${cls} err"><div class="ic-error"></div></div>`;
    case 'search':
      return `<div class="${cls}"><div class="ic-search"></div></div>`;
    case 'clock':
      return `<div class="${cls}"><div class="ic-clock"></div></div>`;
    case 'dots':
      return `<div class="${cls}"><div class="ic-history"><div class="ic-dot"></div><div class="ic-dot"></div><div class="ic-dot"></div><div class="ic-dot"></div></div></div>`;
    case 'pulse':
    default:
      return `<div class="${cls}"><div class="ic-pulse"></div></div>`;
  }
}

// Map app name → icon type
function iconForApp(appName) {
  const a = (appName || '').toLowerCase();
  if (/code|cursor|intellij|xcode|pycharm|vim|neovim|zed|sublime|atom/i.test(a)) return 'code';
  if (/chrome|safari|firefox|edge|brave|arc/i.test(a)) return 'browser';
  if (/figma|photoshop|sketch|affinity|illustrator/i.test(a)) return 'design';
  if (/terminal|iterm|warp|hyper|ghostty|kitty|alacritty/i.test(a)) return 'terminal';
  if (/finder|files|explorer/i.test(a)) return 'folder';
  return 'pulse';
}

// ── Tab routing ───────────────────────────────────────────────────────────

document.querySelectorAll('.nav-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    activeTab = btn.id.replace('tab-', '');
    const labels = {
      recent: 'Recent Timeline', today: 'Today',
      yesterday: 'Yesterday', projects: 'Projects', errors: 'Errors Seen',
    };
    viewTitle.textContent = labels[activeTab] || activeTab;
    const searchWrap = $('search-wrap');
    searchWrap.style.display = (activeTab === 'projects' || activeTab === 'errors') ? 'none' : '';
    loadData();
  });
});

// ── Search ────────────────────────────────────────────────────────────────
let searchTimeout;
searchInp.addEventListener('input', () => {
  clearTimeout(searchTimeout);
  searchTimeout = setTimeout(() => {
    const q = searchInp.value.trim();
    if (q.length > 0) loadSearch(q);
    else loadData();
  }, 300);
});

// ── Close ─────────────────────────────────────────────────────────────────
$('close-btn').addEventListener('click', () => window.neytreya.closeRecall());

// ── Data Loading ──────────────────────────────────────────────────────────
async function loadData() {
  showLoading();
  try {
    let data;
    if (activeTab === 'recent') {
      data = await window.neytreya.fetchRecall('recent');
      renderTimeline(data.entries || []);
    } else if (activeTab === 'today') {
      data = await window.neytreya.fetchRecall('today');
      renderDaySummary(data);
    } else if (activeTab === 'yesterday') {
      data = await window.neytreya.fetchRecall('yesterday');
      renderDaySummary(data);
    } else if (activeTab === 'projects') {
      data = await window.neytreya.fetchRecall('search', ' ');
      renderProjects(data.results || []);
    } else if (activeTab === 'errors') {
      data = await window.neytreya.fetchRecall('search', ' ');
      renderErrors(data.results || []);
    }
  } catch (err) {
    contentArea.innerHTML = emptyState('Could not load memories. Is the backend running?');
  }
}

async function loadSearch(query) {
  showLoading();
  try {
    const data = await window.neytreya.fetchRecall('search', query);
    renderSearchResults(data.results || [], query);
  } catch {
    contentArea.innerHTML = emptyState('Search failed.');
  }
}

// ── Renderers ─────────────────────────────────────────────────────────────

function renderTimeline(entries) {
  if (!entries.length) {
    contentArea.innerHTML = emptyState('No recent memories recorded yet.');
    return;
  }
  contentArea.innerHTML = entries.map(e => {
    const iconType = iconForApp(e.app);
    return `
      <div class="recall-card">
        ${bblIcon(iconType)}
        <div class="rc-body">
          <div class="rc-top">
            <div class="rc-title">${esc(e.app)}</div>
            <div class="rc-time">${esc(e.time)}</div>
          </div>
          <div class="rc-sub">${esc(e.activity)} &middot; ${esc(e.workflow)}</div>
          <div class="rc-tags">
            ${e.project ? `<span class="rc-tag">${esc(e.project)}</span>` : ''}
            ${e.website ? `<span class="rc-tag">${esc(e.website)}</span>` : ''}
            ${e.error   ? `<span class="rc-tag err">${esc(e.error)}</span>` : ''}
          </div>
        </div>
      </div>`;
  }).join('');
}

function renderDaySummary(data) {
  if (!data || !data.entries || !data.entries.length) {
    contentArea.innerHTML = emptyState('No activity recorded for this day.');
    return;
  }
  let html = `
    <div class="day-stat-card">
      Total logged time: <strong>${data.total_minutes || 0} min</strong>
      (~${((data.total_minutes || 0) / 60).toFixed(1)} hours)
    </div>
    <div style="margin-bottom:18px">
      <div class="sidebar-label" style="padding:0 0 8px">Time by Activity</div>
      ${data.entries.map(e => `
        <div class="activity-row">
          ${bblIcon('pulse')}
          <span class="act-name">${esc(e.activity)}</span>
          <span class="act-dur">${esc(e.label)}</span>
        </div>
      `).join('')}
    </div>`;

  if (data.projects?.length)
    html += `<div style="margin-bottom:12px"><span class="sidebar-label" style="padding:0 0 6px;display:block">Projects</span>${data.projects.map(p => `<span class="mini-tag"><div class="mini-dot"></div>${esc(p)}</span>`).join('')}</div>`;
  if (data.websites?.length)
    html += `<div style="margin-bottom:12px"><span class="sidebar-label" style="padding:0 0 6px;display:block">Websites</span>${data.websites.map(w => `<span class="mini-tag"><div class="mini-dot" style="background:var(--tx-3)"></div>${esc(w)}</span>`).join('')}</div>`;
  if (data.errors?.length)
    html += `<div><span class="sidebar-label" style="padding:0 0 6px;display:block;color:#f87171">Errors Detected</span>${data.errors.map(err => `<span class="mini-tag" style="color:#f87171"><div class="mini-dot" style="background:#f87171"></div>${esc(err)}</span>`).join('')}</div>`;

  contentArea.innerHTML = html;
}

function renderProjects(results) {
  const projects = results.filter(r => r.type === 'project');
  if (!projects.length) { contentArea.innerHTML = emptyState('No logged projects.'); return; }
  contentArea.innerHTML = `<div class="project-grid">${projects.map(p => `
    <div class="proj-card" onclick="loadProjectTimeline('${esc(p.title)}')">
      <div class="proj-top">
        ${bblIcon('folder')}
        <div>
          <div class="proj-name">${esc(p.title)}</div>
          <div class="proj-time">${esc(p.time)}</div>
        </div>
      </div>
      <div class="proj-seen">${esc(p.subtitle)}</div>
    </div>`).join('')}
  </div>`;
}

function renderErrors(results) {
  const errors = results.filter(r => r.type === 'error');
  if (!errors.length) { contentArea.innerHTML = emptyState('No errors recorded yet.'); return; }
  contentArea.innerHTML = errors.map(err => `
    <div class="recall-card is-error">
      ${bblIcon('error')}
      <div class="rc-body">
        <div class="rc-top">
          <div class="rc-title" style="color:#f87171;font-family:monospace;font-size:11.5px">${esc(err.title)}</div>
          <div class="rc-time">${esc(err.time)}</div>
        </div>
        <div class="rc-sub">${esc(err.subtitle)}</div>
      </div>
    </div>`).join('');
}

function renderSearchResults(results, query) {
  if (!results.length) { contentArea.innerHTML = emptyState(`No results for "${esc(query)}"`); return; }
  contentArea.innerHTML = results.map(r => {
    const iconType = r.type === 'error' ? 'error' : r.type === 'project' ? 'folder' : iconForApp(r.title);
    return `
      <div class="recall-card${r.type === 'error' ? ' is-error' : ''}">
        ${bblIcon(iconType, r.type === 'error' ? 'err' : '')}
        <div class="rc-body">
          <div class="rc-top">
            <div class="rc-title">${esc(r.title)}</div>
            <div class="rc-time">${esc(r.time)}</div>
          </div>
          <div class="rc-sub">${esc(r.subtitle)}</div>
          ${r.detail ? `<div style="font-size:11px;color:var(--tx-3);margin-top:4px">${esc(r.detail)}</div>` : ''}
        </div>
      </div>`;
  }).join('');
}

async function loadProjectTimeline(projectName) {
  showLoading();
  try {
    const data = await window.neytreya.fetchRecall(`project/${projectName}`);
    viewTitle.textContent = projectName;
    if (!data.entries?.length) { contentArea.innerHTML = emptyState(`No timeline for "${projectName}"`); return; }
    contentArea.innerHTML =
      `<div style="margin-bottom:12px">
        <button onclick="loadData()" style="background:rgba(255,255,255,0.05);border:1px solid var(--bd);color:var(--tx-2);border-radius:6px;padding:6px 12px;cursor:pointer;font-size:12px;font-family:'Inter',sans-serif">
          &larr; Back to Projects
        </button>
      </div>` +
      data.entries.map(e => `
        <div class="recall-card">
          ${bblIcon('folder')}
          <div class="rc-body">
            <div class="rc-top">
              <div class="rc-title">${esc(e.app)}</div>
              <div class="rc-time">${esc(e.time)}</div>
            </div>
            <div class="rc-sub">${esc(e.workflow)}</div>
          </div>
        </div>`).join('');
  } catch {
    contentArea.innerHTML = emptyState('Failed to load project details.');
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────

function showLoading() {
  contentArea.innerHTML = `
    <div class="empty-state">
      <div class="rc-spinner"></div>
      <div class="empty-text" style="font-size:12px">Loading…</div>
    </div>`;
}

function emptyState(msg) {
  return `
    <div class="empty-state">
      <img class="empty-logo" src="logo.jpg" alt="" />
      <div class="empty-text">${esc(msg)}</div>
    </div>`;
}

function esc(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Boot ──────────────────────────────────────────────────────────────────
loadData();
