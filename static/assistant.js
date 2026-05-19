(function () {
  const bubble = document.getElementById('assistant-bubble');
  const panel = document.getElementById('assistant-panel');
  const closeBtn = document.getElementById('assistant-close');
  const messagesEl = document.getElementById('assistant-messages');
  const inputEl = document.getElementById('assistant-input');
  const sendBtn = document.getElementById('assistant-send');
  const compactBtn = document.getElementById('assistant-compact');
  const resetBtn = document.getElementById('assistant-reset');
  const settingsBtn = document.getElementById('assistant-settings-btn');

  let config = {};
  let savedScrollY = 0;

  const savedPromptsEl = document.getElementById('assistant-saved-prompts');

  async function loadSavedPrompts() {
    try {
      const res = await fetch('/api/assistant/saved-prompts');
      if (!res.ok) return;
      const rows = await res.json();
      renderSavedPrompts(rows);
    } catch (e) {
      console.error('Failed to load saved prompts', e);
    }
  }

  function renderSavedPrompts(rows) {
    if (!savedPromptsEl) return;
    savedPromptsEl.innerHTML = '';
    if (rows.length === 0) {
      savedPromptsEl.innerHTML = '<span class="muted" style="font-size:0.8rem;">No saved prompts</span>';
      return;
    }
    rows.forEach(function (r) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'saved-prompt-btn';
      btn.textContent = r.name;
      btn.title = r.prompt_text;
      btn.onclick = function () {
        if (inputEl) {
          inputEl.value = r.prompt_text;
          inputEl.focus();
        }
      };
      savedPromptsEl.appendChild(btn);
    });
  }

  async function loadConfig() {
    try {
      const res = await fetch('/api/assistant/config');
      config = await res.json();
    } catch (e) {
      console.error('Failed to load assistant config', e);
      config = { enabled: 1, auto_context: 1 };
    }
    updateUIFromConfig();
  }

  function updateUIFromConfig() {
    if (!config.enabled) {
      bubble.style.display = 'none';
      panel.classList.remove('open');
    } else {
      bubble.style.display = '';
    }
  }

  function openPanel() {
    panel.classList.add('open');
    bubble.classList.add('panel-open');
    loadHistory();
    loadSavedPrompts();
    inputEl.focus();
    if (window.innerWidth <= 640) {
      savedScrollY = window.scrollY;
      document.body.style.position = 'fixed';
      document.body.style.width = '100%';
      document.body.style.top = -savedScrollY + 'px';
    }
  }

  function closePanel() {
    panel.classList.remove('open');
    bubble.classList.remove('panel-open');
    if (window.innerWidth <= 640) {
      document.body.style.position = '';
      document.body.style.width = '';
      document.body.style.top = '';
      window.scrollTo(0, savedScrollY);
    }
  }

  function togglePanel() {
    if (panel.classList.contains('open')) {
      closePanel();
    } else {
      openPanel();
    }
  }

  function appendMessage(role, content, temporary) {
    const msg = document.createElement('div');
    msg.className = 'assistant-message assistant-message-' + role;
    if (temporary) msg.classList.add('assistant-temporary');
    msg.textContent = content;
    messagesEl.appendChild(msg);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return msg;
  }

  function clearMessages() {
    messagesEl.innerHTML = '<div class="assistant-empty">No messages yet</div>';
  }

  async function loadHistory() {
    try {
      const res = await fetch('/api/assistant/history');
      const rows = await res.json();
      if (rows.length === 0) {
        clearMessages();
        return;
      }
      messagesEl.innerHTML = '';
      rows.forEach(function (r) {
        appendMessage(r.role, r.content);
      });
    } catch (e) {
      messagesEl.innerHTML = '<div class="assistant-error">Failed to load history</div>';
    }
  }

  async function sendMessage() {
    const text = inputEl.value.trim();
    if (!text) return;
    inputEl.value = '';
    appendMessage('user', text);
    const temp = appendMessage('assistant', 'Thinking…', true);
    sendBtn.disabled = true;

    try {
      const res = await fetch('/api/assistant/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, page_url: window.location.pathname }),
      });
      const data = await res.json();
      temp.classList.remove('assistant-temporary');
      if (data.error) {
        temp.textContent = 'Error: ' + data.error;
        temp.classList.add('assistant-error');
      } else {
        temp.textContent = data.response;
      }
    } catch (e) {
      temp.classList.remove('assistant-temporary');
      temp.textContent = 'Error: ' + e.message;
      temp.classList.add('assistant-error');
    } finally {
      sendBtn.disabled = false;
      inputEl.focus();
    }
  }

  async function doCompact() {
    if (!confirm('Compact conversation into a summary and clear history?')) return;
    try {
      const res = await fetch('/api/assistant/compact', { method: 'POST' });
      const data = await res.json();
      clearMessages();
      appendMessage('assistant', 'Compacted: ' + (data.summary || '(empty)'));
    } catch (e) {
      appendMessage('assistant', 'Compact failed: ' + e.message);
    }
  }

  async function doReset() {
    if (!confirm('Reset assistant and clear all history?')) return;
    try {
      const res = await fetch('/api/assistant/reset', { method: 'POST' });
      await res.json();
      clearMessages();
      appendMessage('assistant', 'Assistant has been reset.');
    } catch (e) {
      appendMessage('assistant', 'Reset failed: ' + e.message);
    }
  }

  bubble.addEventListener('click', togglePanel);
  closeBtn.addEventListener('click', function (e) {
    e.stopPropagation();
    closePanel();
  });
  sendBtn.addEventListener('click', sendMessage);
  inputEl.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });
  compactBtn.addEventListener('click', doCompact);
  resetBtn.addEventListener('click', doReset);
  settingsBtn.addEventListener('click', function () {
    window.location.href = '/settings';
  });

  if (typeof ResizeObserver !== 'undefined') {
    const ro = new ResizeObserver(function (entries) {
      for (let i = 0; i < entries.length; i++) {
        const w = entries[i].contentRect.width;
        document.body.style.setProperty('--assistant-panel-width', w + 'px');
      }
    });
    ro.observe(panel);
  }

  loadConfig();
})();
