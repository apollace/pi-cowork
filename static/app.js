async function initBoard() {
  const board = document.getElementById('board');
  const showTerminal = document.getElementById('show-terminal');
  const newTicketBtn = document.getElementById('new-ticket-btn');
  const boardTitle = document.getElementById('board-title');
  const boardMeta = document.getElementById('board-meta');

  let statuses = [];
  let tickets = [];
  let workflowLabels = [];
  let currentBoardId = null;
  let currentBoardData = null;
  const collapsed = new Set();
  const filterState = {
    searchQuery: '',
    selectedPriorities: new Set(),
    selectedLabels: new Set(),
  };
  const searchInput = document.getElementById('ticket-search');
  const labelFiltersContainer = document.getElementById('label-filters');
  const priorityToggles = document.querySelectorAll('.priority-toggle');
  const filterSummary = document.getElementById('filter-summary');

  async function loadBoards() {
    const res = await fetch('/api/boards');
    const boards = await res.json();
    // Restore from localStorage
    const saved = localStorage.getItem('activeBoard');
    if (saved && boards.some(b => b.id === parseInt(saved))) {
      currentBoardId = parseInt(saved);
    } else if (boards.length > 0) {
      currentBoardId = boards[0].id;
      localStorage.setItem('activeBoard', currentBoardId);
    }
    if (currentBoardId) {
      await refresh();
    } else {
      board.innerHTML = '<p class="empty">No boards yet. Click "Boards" to create one.</p>';
      boardTitle.textContent = 'Board';
      boardMeta.innerHTML = '';
    }
  }

  async function refresh() {
    if (!currentBoardId) {
      board.textContent = 'Select a board.';
      return;
    }
    // Show skeleton loading
    const skeleton = document.getElementById('board-skeleton');
    if (skeleton) skeleton.style.display = 'block';
    board.innerHTML = '';
    if (skeleton) board.appendChild(skeleton);
    try {
      const boardRes = await fetch(`/api/boards/${currentBoardId}`);
      if (!boardRes.ok) {
        board.textContent = 'Board not found.';
        return;
      }
      currentBoardData = await boardRes.json();
      const [sRes, tRes, rRes, lRes] = await Promise.all([
        fetch(`/api/statuses?workflow_id=${currentBoardData.workflow_id}`),
        fetch(`/api/tickets?board_id=${currentBoardId}`),
        fetch(`/api/running_agent_runs?board_id=${currentBoardId}`),
        fetch(`/api/labels?workflow_id=${currentBoardData.workflow_id}`),
      ]);
      statuses = await sRes.json();
      tickets = await tRes.json();
      workflowLabels = lRes.ok ? await lRes.json() : [];
      const runningRuns = rRes.ok ? await rRes.json() : [];
      if (newTicketBtn) {
        newTicketBtn.href = `/ticket/new?board_id=${currentBoardId}`;
      }
      // Update header
      boardTitle.textContent = currentBoardData.name;
      boardMeta.innerHTML = `<span class="badge muted">${escapeHtml(currentBoardData.workflow_name)}</span>`;
      renderRunningPanel(runningRuns);
    } catch (e) {
      if (typeof showToast === 'function') showToast('Failed to load board: ' + e.message, 'error');
      else alert('Failed to load board: ' + e.message);
      return;
    } finally {
      if (skeleton) skeleton.style.display = 'none';
    }
    render();
  }

  function formatElapsed(isoString) {
    const start = new Date(isoString);
    const now = new Date();
    const totalSeconds = Math.floor((now - start) / 1000);
    const h = Math.floor(totalSeconds / 3600);
    const m = Math.floor((totalSeconds % 3600) / 60);
    const s = totalSeconds % 60;
    const parts = [];
    if (h) parts.push(h + 'h');
    if (m || h) parts.push(m + 'm');
    parts.push(s + 's');
    return parts.join(' ');
  }

  function renderRunningPanel(runs) {
    const panel = document.getElementById('running-agents');
    if (!panel) return;
    if (!runs || runs.length === 0) {
      panel.style.display = 'none';
      panel.innerHTML = '';
      return;
    }
    panel.style.display = 'flex';
    panel.innerHTML = '';
    for (const run of runs) {
      const card = document.createElement('div');
      card.className = 'running-card';
      card.innerHTML = `
        <a href="/agent_run/${run.id}/live" style="text-decoration:none;color:inherit;display:inline-flex;align-items:center;gap:0.4rem;">
          <span class="pulse-indicator"></span>
          <span class="running-agent">${escapeHtml(run.agent_name)}</span>
          <span class="running-ticket">#${run.ticket_id} ${escapeHtml(run.ticket_title)}</span>
          <span class="running-status">${escapeHtml(run.status_name)}</span>
          <span class="running-elapsed">${formatElapsed(run.started_at)}</span>
        </a>
        <button class="kill-btn" data-run-id="${run.id}" data-agent-name="${escapeHtml(run.agent_name)}" data-ticket-id="${run.ticket_id}" title="Kill agent">🛑</button>
      `;
      // Kill button handler
      const killBtn = card.querySelector('.kill-btn');
      killBtn.addEventListener('click', async function(e) {
        e.stopPropagation();
        e.preventDefault();
        const rid = this.dataset.runId;
        const agentName = this.dataset.agentName;
        const tid = this.dataset.ticketId;
        if (!confirm(`Kill agent '${agentName}' on ticket #${tid}?`)) return;
        this.disabled = true;
        try {
          const res = await fetch('/api/agent_runs/' + rid + '/kill', { method: 'POST' });
          const data = await res.json();
          if (res.ok && data.success) {
            this.textContent = '✓';
            this.classList.add('killed');
            refresh();
          } else {
            this.disabled = false;
            alert(data.error || 'Failed to kill agent');
          }
        } catch (err) {
          this.disabled = false;
          alert('Error: ' + err.message);
        }
      });
      panel.appendChild(card);
    }
  }

  async function moveTicket(ticketId, statusId) {
    const res = await fetch(`/api/tickets/${ticketId}`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({status_id: statusId}),
    });
    if (!res.ok) {
      const data = await res.json();
      if (typeof showToast === 'function') showToast(data.error || 'Failed to move ticket', 'error');
      else alert(data.error || 'Failed to move ticket');
    }
    await refresh();
  }

  // Track active popover picker and its ticket for cleanup
  let _activePopover = null;
  let _activePopoverTicketId = null;

  function closeActivePopover() {
    if (_activePopover) {
      _activePopover.closePopover();
      _activePopover = null;
      _activePopoverTicketId = null;
    }
  }

  window.toggleCardLabels = async function(ticketId) {
    // If same ticket's popover is open, close it
    if (_activePopoverTicketId === ticketId) {
      closeActivePopover();
      return;
    }
    // Close any existing popover
    closeActivePopover();

    const ticket = tickets.find(t => t.id === ticketId);
    if (!ticket) return;

    // Find the trigger button for this card to position the popover
    const trigger = document.getElementById(`card-label-btn-${ticketId}`);
    if (!trigger) return;

    const picker = new LabelPicker({
      container: trigger,
      workflowId: currentBoardData.workflow_id,
      ticketId: ticketId,
      mode: 'live',
      popover: true,
      selectedIds: (ticket.labels || []).map(l => l.id),
      onChange: (ids) => {
        const updatedLabels = picker.allLabels.filter(l => ids.includes(l.id));
        ticket.labels = updatedLabels;
        const labelsDiv = document.getElementById(`card-labels-${ticketId}`);
        const pillsHtml = updatedLabels.map(l =>
          `<span class="badge label-pill" style="background:${escapeHtml(l.color)}33;color:${escapeHtml(l.color)};border:1px solid ${escapeHtml(l.color)}55;">${escapeHtml(l.name)}</span>`
        ).join('');
        labelsDiv.innerHTML = pillsHtml + `<button type="button" class="card-label-add" id="card-label-btn-${ticketId}" onclick="event.preventDefault(); event.stopPropagation(); toggleCardLabels(${ticketId});">+</button>`;
      }
    });
    await picker.init();
    _activePopover = picker;
    _activePopoverTicketId = ticketId;
  };

  function buildCard(ticket) {
    const card = document.createElement('div');
    const priorityClass = ticket.priority ? ` card-priority-${ticket.priority}` : '';
    card.className = `card${priorityClass}`;
    const priorityColors = { Critical: '#dc2626', High: '#d97706', Medium: '#2563eb', Low: '#6b7280' };
    const statusOptions = statuses.map(s =>
      `<option value="${s.id}"${s.id === ticket.status_id ? ' selected' : ''}>${escapeHtml(s.name)}</option>`
    ).join('');
    const priorityLabel = ticket.priority
      ? `<span class="card-priority-label p-${ticket.priority}">● ${escapeHtml(ticket.priority)}</span>`
      : '';
    const statusSelect = `<select class="card-status-select" data-id="${ticket.id}">${statusOptions}</select>`;
    const hasAgent = ticket.agent_name ? `<span class="badge agent">🤖 ${escapeHtml(ticket.agent_name)}</span>` : '';
    const queuedBadge = ticket.queued ? `<span class="badge queued" title="${escapeHtml(ticket.queue_reason || '')} limit">⏳ Queued</span>` : '';
    const gateBadge = ticket.gate_pending ? `<span class="badge gate">🚧 Gate</span>` : '';
    const questionBadge = ticket.question_count ? `<span class="badge question">❓ ${ticket.question_count}</span>` : '';
    const recurringBadge = (ticket.recurring_parents && ticket.recurring_parents.length > 0)
      ? `<span class="badge recurring" title="Created by recurring task: ${escapeHtml(ticket.recurring_parents[0].title)}">🔄 Recurring</span>` : '';
    const labelPills = (ticket.labels || []).map(l =>
      `<span class="badge label-pill" style="background:${escapeHtml(l.color)}33;color:${escapeHtml(l.color)};border:1px solid ${escapeHtml(l.color)}55;">${escapeHtml(l.name)}</span>`
    ).join('');
    card.innerHTML = `
      <a class="card-link" href="/ticket/${ticket.id}">
        <div class="card-header">
          <div style="display:flex;align-items:center;gap:0.4rem;">
            <span class="card-id">#${ticket.id}</span>
            ${priorityLabel}
          </div>
        </div>
        <div class="card-body">
          <div class="card-title">${escapeHtml(ticket.title)}</div>
          <div class="card-labels" id="card-labels-${ticket.id}">
            ${labelPills}
            <button type="button" class="card-label-add" id="card-label-btn-${ticket.id}" onclick="event.preventDefault(); event.stopPropagation(); toggleCardLabels(${ticket.id});">+</button>
          </div>
        </div>
      </a>
      <div class="card-footer">
        ${statusSelect}
        ${hasAgent}
        ${queuedBadge}
        ${gateBadge}
        ${questionBadge}
        ${recurringBadge}
      </div>
    `;

    // Attach change listener for the status select
    const statusSelectEl = card.querySelector('.card-status-select');
    if (statusSelectEl) {
      statusSelectEl.addEventListener('change', (e) => {
        e.preventDefault();
        e.stopPropagation();
        moveTicket(ticket.id, parseInt(e.target.value));
      });
    }

    return card;
  }

  function updateLabelFilters() {
    if (!labelFiltersContainer) return;
    const seen = new Map();
    for (const t of tickets) {
      for (const l of (t.labels || [])) {
        if (!seen.has(l.name)) seen.set(l.name, l.color);
      }
    }
    if (seen.size === 0) {
      labelFiltersContainer.innerHTML = '';
      renderFilterSummary();
      return;
    }
    labelFiltersContainer.innerHTML = '';
    for (const [name, color] of seen) {
      const label = document.createElement('label');
      label.className = 'filter-label-pill';
      label.innerHTML = `<input type="checkbox" value="${escapeHtml(name)}" ${filterState.selectedLabels.has(name) ? 'checked' : ''}> <span style="color:${escapeHtml(color)};">●</span> ${escapeHtml(name)}`;
      label.querySelector('input').addEventListener('change', (e) => {
        if (e.target.checked) {
          filterState.selectedLabels.add(e.target.value);
        } else {
          filterState.selectedLabels.delete(e.target.value);
        }
        render();
      });
      labelFiltersContainer.appendChild(label);
    }
    renderFilterSummary();
  }

  function matchesFilters(ticket) {
    const q = filterState.searchQuery.trim().toLowerCase();
    if (q) {
      const inTitle = ticket.title.toLowerCase().includes(q);
      const inBody = (ticket.body || '').toLowerCase().includes(q);
      if (!inTitle && !inBody) return false;
    }
    if (filterState.selectedPriorities.size > 0 && !filterState.selectedPriorities.has(ticket.priority)) {
      return false;
    }
    if (filterState.selectedLabels.size > 0) {
      const names = (ticket.labels || []).map(l => l.name);
      const hasMatch = names.some(name => filterState.selectedLabels.has(name));
      if (!hasMatch) return false;
    }
    return true;
  }

  function buildGroup(status, visibleTickets) {
    const group = document.createElement('div');
    group.className = 'group';
    if (collapsed.has(status.id)) group.classList.add('collapsed');
    if (status.is_terminal) group.classList.add('terminal');
    group.dataset.statusId = status.id;

    const filtered = visibleTickets.filter(t => t.status_id === status.id);
    const isCollapsed = collapsed.has(status.id);

    const agentBadge = status.agent_name ? `<span class="badge agent">🤖 ${escapeHtml(status.agent_name)}</span>` : '';

    group.innerHTML = `
      <div class="group-header" role="button" tabindex="0" aria-expanded="${!isCollapsed}">
        <div class="group-header-content">
          <span class="group-chevron" aria-hidden="true">${isCollapsed ? '▶' : '▼'}</span>
          <span class="group-title">${escapeHtml(status.name)}</span>
          ${agentBadge}
          <span class="group-count">${filtered.length}</span>
        </div>
        <a class="add-btn" href="/ticket/new?status_id=${status.id}&board_id=${currentBoardId}" title="Add ticket">+</a>
      </div>
      <div class="cards"></div>
    `;

    const header = group.querySelector('.group-header');
    header.addEventListener('click', (e) => {
      if (e.target.closest('a.add-btn')) return;
      e.preventDefault();
      if (collapsed.has(status.id)) {
        collapsed.delete(status.id);
      } else {
        collapsed.add(status.id);
      }
      render();
    });
    header.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        if (collapsed.has(status.id)) {
          collapsed.delete(status.id);
        } else {
          collapsed.add(status.id);
        }
        render();
      }
    });

    const cardsContainer = group.querySelector('.cards');
    for (const t of filtered) {
      cardsContainer.appendChild(buildCard(t));
    }
    return group;
  }

  function renderFilterSummary() {
    if (!filterSummary) return;
    filterSummary.innerHTML = '';
    const activeFilters = [];
    if (filterState.searchQuery.trim()) {
      activeFilters.push({ type: 'search', value: filterState.searchQuery.trim(), label: '"' + filterState.searchQuery.trim() + '"', clearFn: () => { filterState.searchQuery = ''; if (searchInput) searchInput.value = ''; } });
    }
    for (const p of filterState.selectedPriorities) {
      activeFilters.push({ type: 'priority', value: p, label: p, color: { Critical: '#dc2626', High: '#d97706', Medium: '#2563eb', Low: '#6b7280' }[p], clearFn: () => { filterState.selectedPriorities.delete(p); updatePriorityToggles(); } });
    }
    for (const l of filterState.selectedLabels) {
      const label = workflowLabels.find(ll => ll.name === l);
      const color = label ? label.color : '#6b7280';
      activeFilters.push({ type: 'label', value: l, label: l, color: color, clearFn: () => { filterState.selectedLabels.delete(l); updateLabelFilters(); } });
    }
    if (activeFilters.length === 0) { filterSummary.innerHTML = ''; return; }
    for (const f of activeFilters) {
      const pill = document.createElement('button');
      pill.className = 'filter-pill';
      const bg = f.color || '#2563eb';
      pill.style.cssText = `background:${bg}22;color:${bg};border:1px solid ${bg}55;`;
      pill.innerHTML = `${escapeHtml(f.label)} <span class="filter-pill-remove">✕</span>`;
      pill.onclick = () => { f.clearFn(); render(); };
      filterSummary.appendChild(pill);
    }
    if (activeFilters.length > 1) {
      const clearAll = document.createElement('button');
      clearAll.className = 'filter-clear-all';
      clearAll.textContent = 'Clear all';
      clearAll.onclick = () => {
        filterState.searchQuery = '';
        filterState.selectedPriorities.clear();
        filterState.selectedLabels.clear();
        if (searchInput) searchInput.value = '';
        updatePriorityToggles();
        render();
      };
      filterSummary.appendChild(clearAll);
    }
  }

  function updatePriorityToggles() {
    priorityToggles.forEach(btn => {
      const p = btn.dataset.priority;
      if (filterState.selectedPriorities.has(p)) {
        btn.classList.add('active');
      } else {
        btn.classList.remove('active');
      }
    });
  }

  function render() {
    board.innerHTML = '';
    const visibleTickets = tickets.filter(matchesFilters);
    updateLabelFilters();
    // Update priority toggle visibility based on available priorities
    const availablePriorities = new Set(tickets.map(t => t.priority).filter(Boolean));
    priorityToggles.forEach(btn => {
      const p = btn.dataset.priority;
      btn.style.display = availablePriorities.has(p) ? 'inline-flex' : 'none';
      if (filterState.selectedPriorities.has(p)) btn.classList.add('active');
      else btn.classList.remove('active');
    });
    for (const status of statuses) {
      if (status.is_terminal && !showTerminal.checked) continue;
      board.appendChild(buildGroup(status, visibleTickets));
    }
    renderFilterSummary();
  }

  showTerminal.addEventListener('change', render);

  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      filterState.searchQuery = e.target.value;
      render();
    });
  }

  priorityToggles.forEach(btn => {
    btn.addEventListener('click', () => {
      const p = btn.dataset.priority;
      if (filterState.selectedPriorities.has(p)) {
        filterState.selectedPriorities.delete(p);
        btn.classList.remove('active');
      } else {
        filterState.selectedPriorities.add(p);
        btn.classList.add('active');
      }
      render();
    });
  });

  // Read search query from URL params
  const urlParams = new URLSearchParams(window.location.search);
  const urlSearch = urlParams.get('search');
  if (urlSearch && searchInput) {
    searchInput.value = urlSearch;
    filterState.searchQuery = urlSearch;
  }

  await loadBoards();

  // Real-time refresh via SSE events (replaces 30s polling)
  let _refreshDebounce = null;
  function debounceRefresh(delay) {
    clearTimeout(_refreshDebounce);
    _refreshDebounce = setTimeout(function() {
      if (document.visibilityState === 'visible') {
        refresh();
      }
    }, delay || 500);
  }

  // Board-relevant SSE events trigger a debounced refresh
  const boardEvents = [
    'ticket.created', 'ticket.status_changed', 'ticket.updated',
    'comment.added', 'agent.spawned', 'agent.completed', 'agent.failed',
    'gate.pending', 'gate.passed', 'gate.failed',
    'question.asked', 'question.answered'
  ];
  boardEvents.forEach(function(type) {
    window.addEventListener('sse:' + type, function(e) {
      debounceRefresh(500);
    });
  });

  // Re-sync on SSE reconnect
  window.addEventListener('sse:open', function() {
    debounceRefresh(100);
  });
}