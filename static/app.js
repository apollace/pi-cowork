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
  const priorityInputs = document.querySelectorAll('.priority-filters input[type="checkbox"]');

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
      board.textContent = 'Failed to load board.';
      return;
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
      alert(data.error || 'Failed to move ticket');
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
        labelsDiv.innerHTML = pillsHtml + `<button type="button" class="btn small ghost" id="card-label-btn-${ticketId}" onclick="event.preventDefault(); event.stopPropagation(); toggleCardLabels(${ticketId});">+</button>`;
      }
    });
    await picker.init();
    _activePopover = picker;
    _activePopoverTicketId = ticketId;
  };

  function buildCard(ticket) {
    const card = document.createElement('div');
    card.className = 'card';
    const hasAgent = ticket.agent_name ? `<span class="badge agent">🤖 ${escapeHtml(ticket.agent_name)}</span>` : '';
    const queuedBadge = ticket.queued ? `<span class="badge queued" title="${escapeHtml(ticket.queue_reason || '')} limit">⏳ Queued</span>` : '';
    const gateBadge = ticket.gate_pending ? `<span class="badge gate">🚧 Gate</span>` : '';
    const questionBadge = ticket.question_count ? `<span class="badge question">❓ ${ticket.question_count}</span>` : '';
    const recurringBadge = (ticket.recurring_parents && ticket.recurring_parents.length > 0)
      ? `<span class="badge recurring" title="Created by recurring task: ${escapeHtml(ticket.recurring_parents[0].title)}">🔄 Recurring</span>` : '';
    const labelPills = (ticket.labels || []).map(l =>
      `<span class="badge label-pill" style="background:${escapeHtml(l.color)}33;color:${escapeHtml(l.color)};border:1px solid ${escapeHtml(l.color)}55;">${escapeHtml(l.name)}</span>`
    ).join('');
    const priorityBadge = ticket.priority ? `<span class="badge" style="background:${escapeHtml(ticket.priority) === 'Critical' ? '#dc2626' : escapeHtml(ticket.priority) === 'High' ? '#d97706' : escapeHtml(ticket.priority) === 'Low' ? '#6b7280' : '#2563eb'}22;color:${escapeHtml(ticket.priority) === 'Critical' ? '#dc2626' : escapeHtml(ticket.priority) === 'High' ? '#d97706' : escapeHtml(ticket.priority) === 'Low' ? '#6b7280' : '#2563eb'};border:1px solid ${escapeHtml(ticket.priority) === 'Critical' ? '#dc2626' : escapeHtml(ticket.priority) === 'High' ? '#d97706' : escapeHtml(ticket.priority) === 'Low' ? '#6b7280' : '#2563eb'}44;">🔥 ${escapeHtml(ticket.priority)}</span>` : '';
    const branchBadge = (currentBoardData && currentBoardData.git_enabled && ticket.branch) ? `<span class="badge" style="background:#4ade8022;color:#166534;border:1px solid #4ade8044;">🌿 ${escapeHtml(ticket.branch)}</span>` : '';
    card.innerHTML = `
      <a class="card-link" href="/ticket/${ticket.id}">
        <div class="card-id">#${ticket.id}</div>
        <div class="card-title">${escapeHtml(ticket.title)}</div>
        <div class="card-labels" id="card-labels-${ticket.id}">
          ${labelPills}
          <button type="button" class="btn small ghost" id="card-label-btn-${ticket.id}" onclick="event.preventDefault(); event.stopPropagation(); toggleCardLabels(${ticket.id});">+</button>
        </div>
      </a>
      <div class="card-actions">
        <select class="status-select" data-id="${ticket.id}">
          ${statuses.map(s => `<option value="${s.id}" ${s.id === ticket.status_id ? 'selected' : ''}>${escapeHtml(s.name)}</option>`).join('')}
        </select>
        ${priorityBadge}
        ${branchBadge}
        ${hasAgent}
        ${queuedBadge}
        ${gateBadge}
        ${questionBadge}
        ${recurringBadge}
      </div>
    `;
    card.querySelector('.status-select').addEventListener('change', (e) => {
      moveTicket(ticket.id, parseInt(e.target.value));
    });
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

  function render() {
    board.innerHTML = '';
    const visibleTickets = tickets.filter(matchesFilters);
    updateLabelFilters();
    for (const status of statuses) {
      if (status.is_terminal && !showTerminal.checked) continue;
      board.appendChild(buildGroup(status, visibleTickets));
    }
  }

  showTerminal.addEventListener('change', render);

  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      filterState.searchQuery = e.target.value;
      render();
    });
  }

  priorityInputs.forEach(input => {
    input.addEventListener('change', () => {
      filterState.selectedPriorities.clear();
      priorityInputs.forEach(cb => {
        if (cb.checked) filterState.selectedPriorities.add(cb.value);
      });
      render();
    });
  });

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