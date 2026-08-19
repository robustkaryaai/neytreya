const input = document.getElementById('qr-input');
const results = document.getElementById('qr-results');

input.addEventListener('keydown', async (e) => {
  if (e.key === 'Escape') {
    window.neytreya.closeQuickRecall();
  }
  
  if (e.key === 'Enter') {
    const q = input.value.trim();
    if (!q) return;
    
    results.style.display = 'block';
    results.innerHTML = '<div style="text-align:center; padding:20px;">Thinking...</div>';
    
    // Expand window size to show results
    window.resizeTo(700, 420);
    
    try {
      const res = await window.neytreya.queryQuickRecall(q);
      if (res.ok && res.data) {
        // Display the markdown-ish response as simple HTML (just basic replacing for now)
        let html = res.data.replace(/\n/g, '<br>');
        results.innerHTML = html;
      } else {
        results.innerHTML = '<i>Could not retrieve memory.</i>';
      }
    } catch (err) {
      results.innerHTML = `<i>Error: ${err.message}</i>`;
    }
  }
});

// Reset when window shown (we can catch focus)
window.addEventListener('focus', () => {
  input.value = '';
  results.style.display = 'none';
  window.resizeTo(700, 100);
});
