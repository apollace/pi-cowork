// ── Recurring Tasks Tab ──
let _currentRecurringBoardId = null;

function switchTab(tabName) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelector(`.tab-btn[data-tab="${tabName}"]`).classList.add('active');
  document.querySelectorAll('.tab-content').forEach(c => c.style.display = 'none');
  document.getElementById('tab-' + tabName).style.display = 'block';
  if (tabName === 'recurring') {
    loadRecurringList();
  }
}

function getCurrentBoardId() {
  return parseInt(localStorage.getItem('activeBoard')) || null;
}

async function loadRecurringList() {
  const boardId = getCurrentBoardId();
  if (!boardId) {
    document.getElementById('recurring-list').innerHTML = '<p class="empty">No board selected.</p>';
    return;
  }
  _currentRecurringBoardId = boardId;

  try {
    const res = await fetch(`/api/recurring?board_id=${boardId}`);
    const tasks = await res.json();
    const list = document.getElementById('recurring-list');

    if (tasks.length === 0) {
      list.innerHTML = '<p class="empty">No recurring tasks yet. Create one above.</p>';
      return;
    }

    list.innerHTML = '<table class="recurring-table"><thead><tr>' +
      '<th>Title</th><th>Schedule</th><th>Status</th><th>Next Trigger</th><th>Last Triggered</th><th>Actions</th>' +
      '</tr></thead><tbody>' +
      tasks.map(t => {
        const statusBadge = t.enabled
          ? '<span class="badge enabled">✅ Active</span>'
          : '<span class="badge muted">⏸ Disabled</span>';
        const nextTrigger = t.next_trigger_at ? new Date(t.next_trigger_at).toLocaleString() : '—';
        const lastTriggered = t.last_triggered_at ? new Date(t.last_triggered_at).toLocaleString() : 'Never';
        return `<tr>
          <td><strong>${escapeHtml(t.title)}</strong><br><small class="muted">→ ${escapeHtml(t.status_name)}</small></td>
          <td><code>${escapeHtml(t.human_readable || t.cron_expression)}</code></td>
          <td>${statusBadge}</td>
          <td>${nextTrigger}</td>
          <td>${lastTriggered}</td>
          <td class="recurring-actions">
            <button class="btn small ghost" onclick="showEditRecurring(${t.id})" title="Edit">✏️</button>
            <button class="btn small ghost" onclick="toggleRecurring(${t.id})" title="${t.enabled ? 'Disable' : 'Enable'}">${t.enabled ? '⏸' : '▶️'}</button>
            <button class="btn small ghost" onclick="triggerRecurring(${t.id})" title="Trigger Now">⚡</button>
            <button class="btn small ghost danger-text" onclick="deleteRecurring(${t.id})" title="Delete">🗑️</button>
          </td>
        </tr>`;
      }).join('') +
      '</tbody></table>';
  } catch (e) {
    console.error('Failed to load recurring tasks', e);
    document.getElementById('recurring-list').innerHTML = '<p class="empty">Failed to load recurring tasks.</p>';
  }
}

// ── Create/Edit Modal ──
function showCreateRecurring() {
  const boardId = getCurrentBoardId();
  if (!boardId) { alert('Select a board first.'); return; }

  // Fetch statuses for the board's workflow
  fetch(`/api/boards/${boardId}`).then(r => r.json()).then(board => {
    fetch(`/api/statuses?workflow_id=${board.workflow_id}`).then(r => r.json()).then(statuses => {
      showRecurringForm(null, boardId, statuses);
    });
  });
}

function showRecurringForm(task, boardId, statuses) {
  // Remove existing modal
  document.getElementById('recurring-modal')?.remove();

  const isEdit = task !== null;
  const modal = document.createElement('div');
  modal.id = 'recurring-modal';
  modal.className = 'modal';
  modal.style.display = 'flex';
  modal.innerHTML = `
    <div class="modal-content" style="max-width:600px;">
      <h2>${isEdit ? 'Edit' : 'New'} Recurring Task</h2>
      <form id="recurring-form" class="form-card">
        ${isEdit ? `<input type="hidden" name="id" value="${task.id}">` : ''}
        <label>
          Title *
          <input type="text" name="title" value="${isEdit ? escapeHtml(task.title) : ''}" required
            placeholder="e.g. Weekly standup notes — [Recurring {datetime}]">
        </label>
        <label>
          Body (template)
          <textarea name="body" rows="4">${isEdit ? escapeHtml(task.body || '') : ''}</textarea>
        </label>
        <label>
          Destination Status *
          <select name="status_id" required>
            <option value="">Select…</option>
            ${statuses.map(s => `<option value="${s.id}" ${isEdit && s.id === task.status_id ? 'selected' : ''}>${escapeHtml(s.name)}</option>`).join('')}
          </select>
        </label>
        <label>
          Cron Expression *
          <div class="cron-presets" style="display:flex;gap:0.25rem;flex-wrap:wrap;margin-bottom:0.5rem;">
            <button type="button" class="btn small ghost cron-preset" data-cron="0 * * * *">Every hour</button>
            <button type="button" class="btn small ghost cron-preset" data-cron="0 9 * * *">Daily 9am</button>
            <button type="button" class="btn small ghost cron-preset" data-cron="0 9 * * 1">Mon 9am</button>
            <button type="button" class="btn small ghost cron-preset" data-cron="0 9 1 * *">1st of month</button>
            <button type="button" class="btn small ghost cron-preset" data-cron="* * * * *">Every minute</button>
          </div>
          <input type="text" name="cron_expression" id="cron-expression-input"
            value="${isEdit ? escapeHtml(task.cron_expression) : ''}" required
            placeholder="0 9 * * 1">
        </label>
        <div id="cron-preview" class="cron-preview" style="margin-bottom:0.75rem;"></div>
        <div style="display:flex;gap:1rem;">
          <label style="flex:1;">
            Start at
            <input type="datetime-local" name="start_at"
              value="${isEdit && task.start_at ? task.start_at.replace('Z','').slice(0,16) : ''}">
          </label>
          <label style="flex:1;">
            End at
            <input type="datetime-local" name="end_at"
              value="${isEdit && task.end_at ? task.end_at.replace('Z','').slice(0,16) : ''}">
          </label>
        </div>
        <div class="form-actions" style="margin-top:1rem;">
          <button type="submit" class="btn primary">${isEdit ? 'Save' : 'Create'}</button>
          <button type="button" class="btn" onclick="closeRecurringModal()">Cancel</button>
        </div>
      </form>
    </div>
  `;
  document.body.appendChild(modal);

  // Overlay
  const overlay = document.createElement('div');
  overlay.className = 'panel-overlay open';
  overlay.onclick = closeRecurringModal;
  overlay.id = 'recurring-modal-overlay';
  document.body.appendChild(overlay);

  // Cron preset buttons
  modal.querySelectorAll('.cron-preset').forEach(btn => {
    btn.addEventListener('click', () => {
      document.getElementById('cron-expression-input').value = btn.dataset.cron;
      previewCron();
    });
  });

  // Live preview
  const cronInput = document.getElementById('cron-expression-input');
  cronInput.addEventListener('input', debounce(previewCron, 500));
  if (isEdit && task.cron_expression) previewCron();

  // Form submit
  document.getElementById('recurring-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const payload = {
      board_id: boardId,
      title: fd.get('title'),
      body: fd.get('body') || '',
      status_id: parseInt(fd.get('status_id')),
      cron_expression: fd.get('cron_expression'),
      start_at: fd.get('start_at') || null,
      end_at: fd.get('end_at') || null,
    };
    const method = isEdit ? 'PUT' : 'POST';
    const url = isEdit ? `/api/recurring/${task.id}` : '/api/recurring';

    const res = await fetch(url, {
      method,
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      closeRecurringModal();
      loadRecurringList();
    } else {
      const data = await res.json();
      alert(data.error || 'Failed to save recurring task');
    }
  });
}

function closeRecurringModal() {
  document.getElementById('recurring-modal')?.remove();
  document.getElementById('recurring-modal-overlay')?.remove();
}

async function previewCron() {
  const val = document.getElementById('cron-expression-input')?.value.trim();
  const preview = document.getElementById('cron-preview');
  if (!val || !preview) return;
  try {
    const res = await fetch(`/api/recurring/preview?cron=${encodeURIComponent(val)}`);
    const data = await res.json();
    if (res.ok && data.times) {
      preview.innerHTML = `
        <div class="cron-preview-box">
          <strong>${escapeHtml(data.human_readable || val)}</strong>
          <div style="margin-top:0.25rem;">Next 5: ${data.times.map(t => new Date(t).toLocaleString()).join(' → ')}</div>
        </div>`;
    } else {
      preview.innerHTML = `<div class="cron-preview-box error">${escapeHtml(data.error || 'Invalid expression')}</div>`;
    }
  } catch (e) {
    preview.innerHTML = '';
  }
}

function debounce(fn, delay) {
  let timer;
  return function (...args) {
    clearTimeout(timer);
    timer = setTimeout(() => fn.apply(this, args), delay);
  };
}

async function showEditRecurring(id) {
  const boardId = getCurrentBoardId();
  if (!boardId) return;
  const [taskRes, boardRes] = await Promise.all([
    fetch(`/api/recurring/${id}`),
    fetch(`/api/boards/${boardId}`),
  ]);
  const task = await taskRes.json();
  const board = await boardRes.json();
  const statusesRes = await fetch(`/api/statuses?workflow_id=${board.workflow_id}`);
  const statuses = await statusesRes.json();
  showRecurringForm(task, boardId, statuses);
}

async function toggleRecurring(id) {
  const res = await fetch(`/api/recurring/${id}/toggle`, { method: 'POST' });
  if (res.ok) {
    loadRecurringList();
  } else {
    const data = await res.json();
    alert(data.error || 'Failed to toggle');
  }
}

async function triggerRecurring(id) {
  if (!confirm('Manually trigger this recurring task now?')) return;
  const res = await fetch(`/api/recurring/${id}/trigger`, { method: 'POST' });
  if (res.ok) {
    const data = await res.json();
    alert(`Ticket #${data.ticket_id} created!`);
    loadRecurringList();
    // Trigger board refresh
    window.dispatchEvent(new CustomEvent('sse:ticket.created', { detail: { ticket_id: data.ticket_id } }));
  } else {
    const data = await res.json();
    alert(data.error || 'Failed to trigger');
  }
}

async function deleteRecurring(id) {
  if (!confirm('Delete this recurring task? If tickets were created from it, it will be soft-disabled instead.')) return;
  const res = await fetch(`/api/recurring/${id}`, { method: 'DELETE' });
  if (res.ok) {
    loadRecurringList();
  } else {
    const data = await res.json();
    alert(data.error || 'Failed to delete');
  }
}
