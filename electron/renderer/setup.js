'use strict';

const steps = ['python', 'tesseract', 'tts', 'rexycore'];
const logContainer  = document.getElementById('log-container');
const progressBar   = document.getElementById('progress-bar');
const btnFinish     = document.getElementById('btn-finish');

function log(msg) {
  const line = msg.trim();
  if (!line) return;
  const el = document.createElement('div');
  el.className = 'log-line';
  el.textContent = line;
  logContainer.appendChild(el);
  logContainer.scrollTop = logContainer.scrollHeight;
}

function updateStep(id, status, statusText) {
  const el = document.getElementById(`step-${id}`);
  if (!el) return;
  el.className = `step ${status}`;
  el.querySelector('.step-status').textContent = statusText;
}

async function runSetup() {
  const total = steps.length;
  let completed = 0;

  for (const step of steps) {
    updateStep(step, 'active', 'Checking...');
    try {
      const res = await window.neytreya.runSetupStep(step, (msg) => log(msg));
      if (!res.ok) throw new Error(res.error || 'Unknown error');
      updateStep(step, 'done', 'Done ✓');
    } catch (e) {
      updateStep(step, 'error', 'Skipped');
      log(`⚠ ${step}: ${e.message}`);
    }
    completed++;
    progressBar.style.width = `${(completed / total) * 100}%`;
  }

  log('✓ All checks complete.');

  btnFinish.classList.remove('hidden');

  btnFinish.addEventListener('click', async () => {
    btnFinish.textContent   = 'Setting up…';
    btnFinish.disabled      = true;
    await window.neytreya.finishSetup();
  });
}

runSetup();
