/* exported initBoard */
async function initBoard() {
  const board = document.getElementById("board");
  const showTerminal = document.getElementById("show-terminal");
  const newTicketBtn = document.getElementById("new-ticket-btn");
  const boardTitle = document.getElementById("board-title");
  const boardMeta = document.getElementById("board-meta");

  let statuses = [];
  let tickets = [];
  let currentBoardId = null;
  let currentBoardData = null;
  const collapsed = new Set();
  const filterState = {
    searchQuery: "",
    selectedPriorities: new Set(),
    selectedLabels: new Set(),
  };

  // ── Board preferences persistence (localStorage) ──
  function boardPrefsKey(boardId) {
    return "board_prefs_" + boardId;
  }

  function saveBoardPrefs() {
    if (!currentBoardId) return;
    try {
      const prefs = {
        searchQuery: filterState.searchQuery,
        selectedPriorities: [...filterState.selectedPriorities],
        selectedLabels: [...filterState.selectedLabels],
        collapsedGroups: [...collapsed],
        showTerminal: showTerminal.checked,
      };
      localStorage.setItem(boardPrefsKey(currentBoardId), JSON.stringify(prefs));
    } catch {
      // localStorage unavailable or full — silently ignore
    }
  }

  function restoreBoardPrefs() {
    if (!currentBoardId) return;
    try {
      const raw = localStorage.getItem(boardPrefsKey(currentBoardId));
      if (!raw) return;
      const prefs = JSON.parse(raw);
      if (typeof prefs.searchQuery === "string") {
        filterState.searchQuery = prefs.searchQuery;
        if (searchInput) searchInput.value = prefs.searchQuery;
      }
      if (Array.isArray(prefs.selectedPriorities)) {
        filterState.selectedPriorities = new Set(prefs.selectedPriorities);
      }
      if (Array.isArray(prefs.selectedLabels)) {
        filterState.selectedLabels = new Set(prefs.selectedLabels);
      }
      if (Array.isArray(prefs.collapsedGroups)) {
        collapsed.clear();
        prefs.collapsedGroups.forEach(id => collapsed.add(id));
      }
      if (typeof prefs.showTerminal === "boolean") {
        showTerminal.checked = prefs.showTerminal;
      }
    } catch {
      // Corrupt or stale data — fall back to defaults
    }
  }
  const searchInput = document.getElementById("ticket-search");
  const labelFiltersContainer = document.getElementById("label-filters");
  const priorityToggles = document.querySelectorAll(".priority-toggle");
  const filterDropdownBtn = document.getElementById("filter-dropdown-btn");
  const filterDropdownPanel = document.getElementById("filter-dropdown-panel");
  const filterBadge = document.getElementById("filter-badge");

  // Filter dropdown toggle with viewport-aware positioning
  let _dropdownOpen = false;
  function positionFilterDropdown() {
    // Reset to default positioning first so we can measure natural size
    filterDropdownPanel.style.left = "";
    filterDropdownPanel.style.right = "";
    filterDropdownPanel.style.top = "";
    filterDropdownPanel.style.bottom = "";
    filterDropdownPanel.style.maxHeight = "";
    filterDropdownPanel.style.overflowY = "";
    filterDropdownPanel.classList.remove("dropdown-right", "dropdown-above", "scrollable");

    const triggerRect = filterDropdownBtn.getBoundingClientRect();
    const panelRect = filterDropdownPanel.getBoundingClientRect();
    const viewportW = window.innerWidth;
    const viewportH = window.innerHeight;
    const gap = 6; // px gap between trigger and panel

    // Horizontal: if panel overflows right, align to right edge of trigger
    if (triggerRect.left + panelRect.width > viewportW - 8) {
      filterDropdownPanel.classList.add("dropdown-right");
    }
    // Vertical: if panel overflows bottom, position above the trigger
    if (triggerRect.bottom + gap + panelRect.height > viewportH - 8) {
      filterDropdownPanel.classList.add("dropdown-above");
      // Re-check: if above also overflows, constrain max-height
      const aboveSpace = triggerRect.top - gap - 8;
      if (aboveSpace < panelRect.height) {
        filterDropdownPanel.style.maxHeight = Math.max(aboveSpace, 120) + "px";
        filterDropdownPanel.classList.add("scrollable");
      }
    } else {
      // Below: check if still too tall even when below trigger
      const belowSpace = viewportH - triggerRect.bottom - gap - 8;
      if (belowSpace < panelRect.height) {
        filterDropdownPanel.style.maxHeight = Math.max(belowSpace, 120) + "px";
        filterDropdownPanel.classList.add("scrollable");
      }
    }
  }
  function toggleFilterDropdown(forceClose) {
    if (forceClose || _dropdownOpen) {
      filterDropdownPanel.style.display = "none";
      filterDropdownBtn.classList.remove("active");
      _dropdownOpen = false;
    } else {
      filterDropdownPanel.style.display = "block";
      filterDropdownBtn.classList.add("active");
      positionFilterDropdown();
      _dropdownOpen = true;
    }
  }
  function updateFilterBadge() {
    const count = filterState.selectedPriorities.size + filterState.selectedLabels.size;
    filterBadge.textContent = count;
    filterBadge.style.display = count > 0 ? "inline-flex" : "none";
  }
  if (filterDropdownBtn) {
    filterDropdownBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleFilterDropdown();
    });
  }
  // Close dropdown on click outside
  document.addEventListener("click", (e) => {
    if (_dropdownOpen && !filterDropdownPanel.contains(e.target) && !filterDropdownBtn.contains(e.target)) {
      toggleFilterDropdown(true);
    }
  });
  // Reposition dropdown on viewport resize/scroll while open
  function _repositionIfOpen() {
    if (_dropdownOpen) positionFilterDropdown();
  }
  window.addEventListener("resize", _repositionIfOpen);
  window.addEventListener("scroll", _repositionIfOpen, true);
  // Close dropdown on Escape
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && _dropdownOpen) {
      toggleFilterDropdown(true);
    }
  });
  // Prevent clicks inside dropdown from closing it
  if (filterDropdownPanel) {
    filterDropdownPanel.addEventListener("click", (e) => {
      e.stopPropagation();
    });
  }

  async function loadBoards() {
    const res = await fetch("/api/boards");
    const boards = await res.json();
    // Restore from localStorage
    const saved = localStorage.getItem("activeBoard");
    if (saved && boards.some(b => b.id === parseInt(saved))) {
      currentBoardId = parseInt(saved);
    } else if (boards.length > 0) {
      currentBoardId = boards[0].id;
      localStorage.setItem("activeBoard", currentBoardId);
    }
    if (currentBoardId) {
      await refresh();
    } else {
      board.innerHTML = '<p class="empty">No boards yet. Click "Boards" to create one.</p>';
      boardTitle.textContent = "Board";
      boardMeta.innerHTML = "";
    }
  }

  async function refresh() {
    if (!currentBoardId) {
      board.textContent = "Select a board.";
      return;
    }
    // Show skeleton loading
    const skeleton = document.getElementById("board-skeleton");
    if (skeleton) skeleton.style.display = "block";
    board.innerHTML = "";
    if (skeleton) board.appendChild(skeleton);
    try {
      const boardRes = await fetch(`/api/boards/${currentBoardId}`);
      if (!boardRes.ok) {
        board.textContent = "Board not found.";
        return;
      }
      currentBoardData = await boardRes.json();
      const [sRes, tRes, rRes] = await Promise.all([
        fetch(`/api/statuses?workflow_id=${currentBoardData.workflow_id}`),
        fetch(`/api/tickets?board_id=${currentBoardId}&include_terminal=${showTerminal.checked}`),
        fetch(`/api/running_agent_runs?board_id=${currentBoardId}`),
      ]);
      statuses = await sRes.json();
      tickets = await tRes.json();
      const runningRuns = rRes.ok ? await rRes.json() : [];
      if (newTicketBtn) {
        newTicketBtn.href = `/ticket/new?board_id=${currentBoardId}`;
      }
      // Update header
      boardTitle.textContent = currentBoardData.name;
      boardMeta.innerHTML = `<span class="badge muted">${escapeHtml(currentBoardData.workflow_name)}</span> <a href="/knowledge" class="badge muted" style="cursor:pointer;text-decoration:none;">📚 Knowledge <span id="board-knowledge-count"></span></a>`;
      // Load knowledge count for this board
      try {
        const kRes = await fetch("/api/knowledge?board_id=" + currentBoardId);
        if (kRes.ok) {
          const kEntries = await kRes.json();
          const countEl = document.getElementById("board-knowledge-count");
          if (countEl) countEl.textContent = "(" + kEntries.length + ")";
        }
      } catch { /* silently ignore */ }
      renderRunningPanel(runningRuns);
    } catch (e) {
      showToast("Failed to load board: " + e.message, "error");
      return;
    } finally {
      if (skeleton) skeleton.style.display = "none";
    }
    restoreBoardPrefs();
    render();
  }

  async function syncTickets() {
    if (!currentBoardId) return;
    try {
      const [tRes, rRes] = await Promise.all([
        fetch(`/api/tickets?board_id=${currentBoardId}&include_terminal=${showTerminal.checked}`),
        fetch(`/api/running_agent_runs?board_id=${currentBoardId}`),
      ]);
      const newTickets = await tRes.json();
      const runningRuns = rRes.ok ? await rRes.json() : [];
      diffAndUpdateBoard(newTickets);
      renderRunningPanel(runningRuns);
    } catch {
      // Silently ignore sync failures to avoid toast spam on rapid SSE events
    }
  }

  function getCardsContainer(statusId) {
    const group = board.querySelector(`.group[data-status-id="${statusId}"]`);
    return group ? group.querySelector(".cards") : null;
  }

  function removeCard(ticketId) {
    const card = document.getElementById(`ticket-card-${ticketId}`);
    if (card) {
      if (_activePopoverTicketId === ticketId) {
        closeActivePopover();
      }
      card.remove();
    }
  }

  function appendCardToColumn(ticket) {
    const container = getCardsContainer(ticket.status_id);
    if (!container) return;
    const card = buildCard(ticket);
    container.appendChild(card);
  }

  function moveCardToColumn(ticket, oldStatusId) {
    const card = document.getElementById(`ticket-card-${ticket.id}`);
    if (!card) return;
    const newContainer = getCardsContainer(ticket.status_id);
    if (!newContainer) {
      card.remove();
      return;
    }
    newContainer.appendChild(card);
  }

  function updateCardInPlace(ticket, cardEl) {
    // Update priority class
    const priorityClass = ticket.priority ? `card-priority-${ticket.priority}` : "";
    cardEl.className = `card ${priorityClass}`.trim();

    // Update priority label
    const priorityLabelEl = cardEl.querySelector(".card-priority-label");
    if (priorityLabelEl) {
      if (ticket.priority) {
        priorityLabelEl.className = `card-priority-label p-${ticket.priority}`;
        priorityLabelEl.textContent = `● ${ticket.priority}`;
        priorityLabelEl.style.display = "";
      } else {
        priorityLabelEl.style.display = "none";
      }
    }

    // Update title
    const titleEl = cardEl.querySelector(".card-title");
    if (titleEl) {
      titleEl.textContent = ticket.title;
    }

    // Update labels
    const labelsDiv = cardEl.querySelector(`#card-labels-${ticket.id}`);
    if (labelsDiv) {
      const labelPills = (ticket.labels || []).map(l =>
        `<span class="badge label-pill" style="background:${escapeHtml(l.color)}33;color:${escapeHtml(l.color)};border:1px solid ${escapeHtml(l.color)}55;">${escapeHtml(l.name)}</span>`
      ).join("");
      labelsDiv.innerHTML = labelPills + `<button type="button" class="card-label-add" id="card-label-btn-${ticket.id}" onclick="event.preventDefault(); event.stopPropagation(); toggleCardLabels(${ticket.id});">+</button>`;
    }

    // Update status select and footer badges
    const footer = cardEl.querySelector(".card-footer");
    if (footer) {
      const statusOptions = statuses.map(s =>
        `<option value="${s.id}"${s.id === ticket.status_id ? " selected" : ""}>${escapeHtml(s.name)}</option>`
      ).join("");
      const statusSelectHTML = `<select class="card-status-select" data-id="${ticket.id}">${statusOptions}</select>`;
      const hasAgent = ticket.agent_name ? `<span class="badge agent">🤖 ${escapeHtml(ticket.agent_name)}</span>` : "";
      const queuedBadge = ticket.queued ? `<span class="badge queued" title="${escapeHtml(ticket.queue_reason || "")} limit">⏳ Queued</span>` : "";
      const gateBadge = ticket.gate_pending ? "<span class=\"badge gate\">🚧 Gate</span>" : "";
      const questionBadge = ticket.question_count ? `<span class="badge question">❓ ${ticket.question_count}</span>` : "";
      const recurringBadge = (ticket.recurring_parents && ticket.recurring_parents.length > 0)
        ? `<span class="badge recurring" title="Created by recurring task: ${escapeHtml(ticket.recurring_parents[0].title)}">🔄 Recurring</span>` : "";

      let branchBadge = "";
      if (ticket.branch) {
        const autoPattern = new RegExp(`^ticket-${ticket.id}-[a-z0-9-]+$`);
        const isAuto = autoPattern.test(ticket.branch);
        const displayText = isAuto ? `#${ticket.id}` : escapeHtml(ticket.branch);
        const textClass = isAuto ? "" : "card-branch-text";
        branchBadge = `
          <span class="card-branch-pill" title="Git branch: ${escapeHtml(ticket.branch)}">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#64748B" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="6" y1="3" x2="6" y2="15"></line>
              <circle cx="18" cy="6" r="3"></circle>
              <circle cx="6" cy="18" r="3"></circle>
              <path d="M18 9a9 9 0 0 1-9 9"></path>
            </svg>
            <span class="${textClass}">${displayText}</span>
            <button type="button" class="card-branch-copy" data-branch="${escapeHtml(ticket.branch)}" aria-label="Copy branch name">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
              </svg>
            </button>
          </span>`;
      }

      footer.innerHTML = statusSelectHTML + hasAgent + queuedBadge + gateBadge + questionBadge + recurringBadge + branchBadge;

      const statusSelectEl = footer.querySelector(".card-status-select");
      if (statusSelectEl) {
        statusSelectEl.addEventListener("change", (e) => {
          e.preventDefault();
          e.stopPropagation();
          moveTicket(ticket.id, parseInt(e.target.value));
        });
      }

      const branchCopyBtn = footer.querySelector(".card-branch-copy");
      if (branchCopyBtn) {
        branchCopyBtn.addEventListener("click", (e) => {
          e.preventDefault();
          e.stopPropagation();
          const branch = branchCopyBtn.getAttribute("data-branch");
          navigator.clipboard.writeText(branch).then(() => {
            window.showToast("Branch copied", "success");
          });
        });
      }
    }
  }

  function updateGroupCounts(allTickets) {
    const visibleTickets = allTickets.filter(matchesFilters);
    for (const status of statuses) {
      const group = board.querySelector(`.group[data-status-id="${status.id}"]`);
      if (!group) continue;
      const count = visibleTickets.filter(t => t.status_id === status.id).length;
      const countEl = group.querySelector(".group-count");
      if (countEl) countEl.textContent = count;
    }
  }

  function diffAndUpdateBoard(newTickets) {
    const oldMap = new Map(tickets.map(t => [t.id, t]));
    const newMap = new Map(newTickets.map(t => [t.id, t]));

    // Removed tickets
    for (const id of oldMap.keys()) {
      if (!newMap.has(id)) {
        removeCard(id);
      }
    }

    // New or updated tickets
    for (const newTicket of newTickets) {
      const oldTicket = oldMap.get(newTicket.id);
      const shouldBeVisible = matchesFilters(newTicket);

      if (!oldTicket) {
        // Brand new ticket
        if (shouldBeVisible) {
          appendCardToColumn(newTicket);
        }
      } else {
        const wasVisible = matchesFilters(oldTicket);
        if (!wasVisible && shouldBeVisible) {
          appendCardToColumn(newTicket);
        } else if (wasVisible && !shouldBeVisible) {
          removeCard(newTicket.id);
        } else if (wasVisible && shouldBeVisible) {
          const cardEl = document.getElementById(`ticket-card-${newTicket.id}`);
          if (!cardEl) continue;
          if (oldTicket.status_id !== newTicket.status_id) {
            moveCardToColumn(newTicket, oldTicket.status_id);
          }
          // Check if any displayed property changed
          if (
            oldTicket.priority !== newTicket.priority ||
            oldTicket.title !== newTicket.title ||
            oldTicket.agent_name !== newTicket.agent_name ||
            oldTicket.queued !== newTicket.queued ||
            oldTicket.queue_reason !== newTicket.queue_reason ||
            oldTicket.gate_pending !== newTicket.gate_pending ||
            oldTicket.question_count !== newTicket.question_count ||
            oldTicket.branch !== newTicket.branch ||
            JSON.stringify(oldTicket.labels || []) !== JSON.stringify(newTicket.labels || []) ||
            JSON.stringify(oldTicket.recurring_parents || []) !== JSON.stringify(newTicket.recurring_parents || [])
          ) {
            updateCardInPlace(newTicket, cardEl);
          }
        }
      }
    }

    updateGroupCounts(newTickets);
    rebuildCollapsedMarkers(newTickets);
    tickets = newTickets;
  }

  function formatElapsed(isoString) {
    const start = new Date(isoString);
    const now = new Date();
    const totalSeconds = Math.floor((now - start) / 1000);
    const h = Math.floor(totalSeconds / 3600);
    const m = Math.floor((totalSeconds % 3600) / 60);
    const s = totalSeconds % 60;
    const parts = [];
    if (h) parts.push(h + "h");
    if (m || h) parts.push(m + "m");
    parts.push(s + "s");
    return parts.join(" ");
  }

  function renderRunningPanel(runs) {
    const panel = document.getElementById("running-agents");
    if (!panel) return;
    if (!runs || runs.length === 0) {
      panel.style.display = "none";
      panel.innerHTML = "";
      return;
    }
    panel.style.display = "flex";

    // Map existing cards by run ID for diffing
    const existingCards = new Map();
    panel.querySelectorAll(".running-card").forEach(card => {
      const runId = card.dataset.runId;
      if (runId) existingCards.set(runId, card);
    });

    const newRunIds = new Set(runs.map(r => String(r.id)));

    // Remove cards for runs that no longer exist
    for (const [runId, card] of existingCards) {
      if (!newRunIds.has(runId)) {
        card.remove();
      }
    }

    // Add or update cards
    for (const run of runs) {
      const runIdStr = String(run.id);
      let card = existingCards.get(runIdStr);
      if (!card) {
        card = document.createElement("div");
        card.className = "running-card";
        card.dataset.runId = runIdStr;
        panel.appendChild(card);
      }
      // Update content (elapsed time always changes, so rebuild innerHTML)
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
      const killBtn = card.querySelector(".kill-btn");
      killBtn.addEventListener("click", async function(e) {
        e.stopPropagation();
        e.preventDefault();
        const rid = this.dataset.runId;
        const agentName = this.dataset.agentName;
        const tid = this.dataset.ticketId;
        if (!confirm(`Kill agent '${agentName}' on ticket #${tid}?`)) return;
        this.disabled = true;
        try {
          const res = await fetch("/api/agent_runs/" + rid + "/kill", { method: "POST" });
          const data = await res.json();
          if (res.ok && data.success) {
            this.textContent = "✓";
            this.classList.add("killed");
            syncTickets();
          } else {
            this.disabled = false;
            showToast(data.error || "Failed to kill agent", "error");
          }
        } catch (err) {
          this.disabled = false;
          showToast("Error: " + err.message, "error");
        }
      });
    }
  }

  async function moveTicket(ticketId, statusId) {
    const res = await fetch(`/api/tickets/${ticketId}`, {
      method: "PUT",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({status_id: statusId}),
    });
    if (!res.ok) {
      const data = await res.json();
      showToast(data.error || "Failed to move ticket", "error");
    }
    // Let SSE sync update the board; trigger a lightweight sync after a short delay as fallback
    setTimeout(syncTickets, 300);
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
      mode: "live",
      popover: true,
      selectedIds: (ticket.labels || []).map(l => l.id),
      onChange: (ids) => {
        const updatedLabels = picker.allLabels.filter(l => ids.includes(l.id));
        ticket.labels = updatedLabels;
        const labelsDiv = document.getElementById(`card-labels-${ticketId}`);
        const pillsHtml = updatedLabels.map(l =>
          `<span class="badge label-pill" style="background:${escapeHtml(l.color)}33;color:${escapeHtml(l.color)};border:1px solid ${escapeHtml(l.color)}55;">${escapeHtml(l.name)}</span>`
        ).join("");
        labelsDiv.innerHTML = pillsHtml + `<button type="button" class="card-label-add" id="card-label-btn-${ticketId}" onclick="event.preventDefault(); event.stopPropagation(); toggleCardLabels(${ticketId});">+</button>`;
      }
    });
    await picker.init();
    _activePopover = picker;
    _activePopoverTicketId = ticketId;
  };

  function buildCard(ticket) {
    const card = document.createElement("div");
    card.id = "ticket-card-" + ticket.id;
    const priorityClass = ticket.priority ? ` card-priority-${ticket.priority}` : "";
    card.className = `card${priorityClass}`;
    const statusOptions = statuses.map(s =>
      `<option value="${s.id}"${s.id === ticket.status_id ? " selected" : ""}>${escapeHtml(s.name)}</option>`
    ).join("");
    const priorityLabel = ticket.priority
      ? `<span class="card-priority-label p-${ticket.priority}">● ${escapeHtml(ticket.priority)}</span>`
      : "";
    const statusSelect = `<select class="card-status-select" data-id="${ticket.id}">${statusOptions}</select>`;
    const hasAgent = ticket.agent_name ? `<span class="badge agent">🤖 ${escapeHtml(ticket.agent_name)}</span>` : "";
    const queuedBadge = ticket.queued ? `<span class="badge queued" title="${escapeHtml(ticket.queue_reason || "")} limit">⏳ Queued</span>` : "";
    const gateBadge = ticket.gate_pending ? "<span class=\"badge gate\">🚧 Gate</span>" : "";
    const questionBadge = ticket.question_count ? `<span class="badge question">❓ ${ticket.question_count}</span>` : "";
    const recurringBadge = (ticket.recurring_parents && ticket.recurring_parents.length > 0)
      ? `<span class="badge recurring" title="Created by recurring task: ${escapeHtml(ticket.recurring_parents[0].title)}">🔄 Recurring</span>` : "";
    let branchBadge = "";
    if (ticket.branch) {
      const autoPattern = new RegExp(`^ticket-${ticket.id}-[a-z0-9-]+$`);
      const isAuto = autoPattern.test(ticket.branch);
      const displayText = isAuto ? `#${ticket.id}` : escapeHtml(ticket.branch);
      const textClass = isAuto ? "" : "card-branch-text";
      branchBadge = `
        <span class="card-branch-pill" title="Git branch: ${escapeHtml(ticket.branch)}">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#64748B" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="6" y1="3" x2="6" y2="15"></line>
            <circle cx="18" cy="6" r="3"></circle>
            <circle cx="6" cy="18" r="3"></circle>
            <path d="M18 9a9 9 0 0 1-9 9"></path>
          </svg>
          <span class="${textClass}">${displayText}</span>
          <button type="button" class="card-branch-copy" data-branch="${escapeHtml(ticket.branch)}" aria-label="Copy branch name">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
            </svg>
          </button>
        </span>`;
    }
    const labelPills = (ticket.labels || []).map(l =>
      `<span class="badge label-pill" style="background:${escapeHtml(l.color)}33;color:${escapeHtml(l.color)};border:1px solid ${escapeHtml(l.color)}55;">${escapeHtml(l.name)}</span>`
    ).join("");
    card.innerHTML = `
      <div class="card-indicator"></div>
      <div class="card-inner">
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
          ${branchBadge}
        </div>
      </div>
    `;

    // Attach change listener for the status select
    const statusSelectEl = card.querySelector(".card-status-select");
    if (statusSelectEl) {
      statusSelectEl.addEventListener("change", (e) => {
        e.preventDefault();
        e.stopPropagation();
        moveTicket(ticket.id, parseInt(e.target.value));
      });
    }

    // Attach copy listener for the branch copy button
    const branchCopyBtn = card.querySelector(".card-branch-copy");
    if (branchCopyBtn) {
      branchCopyBtn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        const branch = branchCopyBtn.getAttribute("data-branch");
        navigator.clipboard.writeText(branch).then(() => {
          window.showToast("Branch copied", "success");
        });
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
      labelFiltersContainer.innerHTML = "";
      updateFilterBadge();
      return;
    }
    labelFiltersContainer.innerHTML = "";
    for (const [name, color] of seen) {
      const label = document.createElement("label");
      label.className = "filter-label-pill";
      label.innerHTML = `<input type="checkbox" value="${escapeHtml(name)}" ${filterState.selectedLabels.has(name) ? "checked" : ""}> <span style="color:${escapeHtml(color)};">●</span> ${escapeHtml(name)}`;
      label.querySelector("input").addEventListener("change", (e) => {
        if (e.target.checked) {
          filterState.selectedLabels.add(e.target.value);
        } else {
          filterState.selectedLabels.delete(e.target.value);
        }
        updateFilterBadge();
        saveBoardPrefs();
        render();
      });
      labelFiltersContainer.appendChild(label);
    }
    updateFilterBadge();
  }

  function matchesFilters(ticket) {
    const q = filterState.searchQuery.trim().toLowerCase();
    if (q) {
      const inTitle = ticket.title.toLowerCase().includes(q);
      const inBody = (ticket.body || "").toLowerCase().includes(q);
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

  function buildCollapsedMarker(ticket) {
    const link = document.createElement("a");
    link.className = "collapsed-marker";
    link.href = `/ticket/${ticket.id}`;
    const priorityClass = ticket.priority ? ` priority-${ticket.priority}` : "";
    link.className = `collapsed-marker${priorityClass}`;
    link.innerHTML = `<span class="collapsed-marker-id">#${ticket.id}</span>`;
    return link;
  }

  function rebuildCollapsedMarkers(allTickets) {
    const visibleTickets = allTickets.filter(matchesFilters);
    for (const status of statuses) {
      const group = board.querySelector(`.group[data-status-id="${status.id}"]`);
      if (!group) continue;
      const container = group.querySelector(".cards-collapsed");
      if (!container) continue;
      container.innerHTML = "";
      const filtered = visibleTickets.filter(t => t.status_id === status.id);
      for (const t of filtered) {
        container.appendChild(buildCollapsedMarker(t));
      }
    }
  }

  function buildGroup(status, visibleTickets) {
    const group = document.createElement("div");
    group.className = "group";
    if (collapsed.has(status.id)) group.classList.add("collapsed");
    if (status.is_terminal) group.classList.add("terminal");
    group.dataset.statusId = status.id;

    const filtered = visibleTickets.filter(t => t.status_id === status.id);
    const isCollapsed = collapsed.has(status.id);

    const agentBadge = status.agent_name ? `<span class="badge agent">🤖 ${escapeHtml(status.agent_name)}</span>` : "";

    group.innerHTML = `
      <div class="group-header" role="button" tabindex="0" aria-expanded="${!isCollapsed}">
        <div class="group-header-content">
          <span class="group-chevron" aria-hidden="true">${isCollapsed ? "▶" : "▼"}</span>
          <span class="group-title">${escapeHtml(status.name)}</span>
          ${agentBadge}
          <span class="group-count">${filtered.length}</span>
        </div>
        <a class="add-btn" href="/ticket/new?status_id=${status.id}&board_id=${currentBoardId}" title="Add ticket">+</a>
      </div>
      <div class="cards"></div>
      <div class="cards-collapsed"></div>
    `;

    const header = group.querySelector(".group-header");
    header.addEventListener("click", (e) => {
      if (e.target.closest("a.add-btn")) return;
      e.preventDefault();
      if (collapsed.has(status.id)) {
        collapsed.delete(status.id);
      } else {
        collapsed.add(status.id);
      }
      saveBoardPrefs();
      render();
    });
    header.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        if (collapsed.has(status.id)) {
          collapsed.delete(status.id);
        } else {
          collapsed.add(status.id);
        }
        saveBoardPrefs();
        render();
      }
    });

    const cardsContainer = group.querySelector(".cards");
    for (const t of filtered) {
      cardsContainer.appendChild(buildCard(t));
    }
    return group;
  }


  function render() {
    board.innerHTML = "";
    const visibleTickets = tickets.filter(matchesFilters);
    updateLabelFilters();
    // Update priority toggle visibility based on available priorities
    const availablePriorities = new Set(tickets.map(t => t.priority).filter(Boolean));
    priorityToggles.forEach(btn => {
      const p = btn.dataset.priority;
      btn.style.display = availablePriorities.has(p) ? "inline-flex" : "none";
      if (filterState.selectedPriorities.has(p)) btn.classList.add("active");
      else btn.classList.remove("active");
    });
    for (const status of statuses) {
      if (status.is_terminal && !showTerminal.checked) continue;
      board.appendChild(buildGroup(status, visibleTickets));
    }
    updateFilterBadge();
    rebuildCollapsedMarkers(tickets);
  }

  showTerminal.addEventListener("change", () => {
    saveBoardPrefs();
    refresh();
  });

  if (searchInput) {
    searchInput.addEventListener("input", (e) => {
      filterState.searchQuery = e.target.value;
      saveBoardPrefs();
      render();
    });
  }

  priorityToggles.forEach(btn => {
    btn.addEventListener("click", () => {
      const p = btn.dataset.priority;
      if (filterState.selectedPriorities.has(p)) {
        filterState.selectedPriorities.delete(p);
        btn.classList.remove("active");
      } else {
        filterState.selectedPriorities.add(p);
        btn.classList.add("active");
      }
      updateFilterBadge();
      saveBoardPrefs();
      render();
    });
  });

  // Read search query from URL params
  const urlParams = new URLSearchParams(window.location.search);
  const urlSearch = urlParams.get("search");
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
      if (document.visibilityState === "visible") {
        refresh();
      }
    }, delay || 500);
  }

  let _syncDebounce = null;
  function debounceSync(delay) {
    clearTimeout(_syncDebounce);
    _syncDebounce = setTimeout(function() {
      if (document.visibilityState === "visible") {
        syncTickets();
      }
    }, delay || 500);
  }

  // Board-relevant SSE events trigger a debounced sync (surgical DOM updates)
  const boardEvents = [
    "ticket.created", "ticket.status_changed", "ticket.updated",
    "comment.added", "agent.spawned", "agent.completed", "agent.failed",
    "gate.pending", "gate.passed", "gate.failed",
    "question.asked", "question.answered"
  ];
  boardEvents.forEach(function(type) {
    window.addEventListener("sse:" + type, function(e) {
      debounceSync(500);
    });
  });

  // Re-sync on SSE reconnect — full refresh to re-sync state
  window.addEventListener("sse:open", function() {
    debounceRefresh(100);
  });
}