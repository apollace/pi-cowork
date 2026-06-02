/* Knowledge Management Page */

(function() {
  let boards = [];
  let categories = [];
  let currentScope = '';
  let currentSearch = '';
  let currentCategory = '';
  let currentAutoContext = false;
  let editingEntryId = null;
  let viewingEntryId = null;

  // ── Initialize ──

  async function init() {
    await loadBoards();
    await loadCategories();
    await loadEntries();

    document.getElementById('knowledge-scope').addEventListener('change', function() {
      currentScope = this.value;
      loadEntries();
    });
    document.getElementById('knowledge-search').addEventListener('input', debounce(function() {
      currentSearch = this.value;
      loadEntries();
    }, 300));
    document.getElementById('knowledge-category').addEventListener('change', function() {
      currentCategory = this.value;
      loadEntries();
    });
    document.getElementById('knowledge-auto-context').addEventListener('change', function() {
      currentAutoContext = this.checked;
      loadEntries();
    });
    document.getElementById('knowledge-create-btn').addEventListener('click', () => openCreateForm());

    // Detail modal
    document.getElementById('knowledge-detail-close').addEventListener('click', () => closeModal('knowledge-detail-modal'));
    document.getElementById('knowledge-edit-btn').addEventListener('click', () => {
      if (viewingEntryId) openEditForm(viewingEntryId);
    });
    document.getElementById('knowledge-versions-btn').addEventListener('click', () => {
      if (viewingEntryId) showVersions(viewingEntryId);
    });

    // Form modal
    document.getElementById('knowledge-form-close').addEventListener('click', () => closeModal('knowledge-form-modal'));
    document.getElementById('knowledge-form-cancel').addEventListener('click', () => closeModal('knowledge-form-modal'));
    document.getElementById('knowledge-form').addEventListener('submit', handleFormSubmit);

    // Editor tabs
    document.querySelectorAll('.knowledge-editor-tab').forEach(tab => {
      tab.addEventListener('click', function() {
        document.querySelectorAll('.knowledge-editor-tab').forEach(t => t.classList.remove('active'));
        this.classList.add('active');
        const target = this.dataset.tab;
        if (target === 'write') {
          document.getElementById('knowledge-form-content').style.display = '';
          document.getElementById('knowledge-form-preview').style.display = 'none';
        } else {
          document.getElementById('knowledge-form-content').style.display = 'none';
          const content = document.getElementById('knowledge-form-content').value;
          document.getElementById('knowledge-form-preview').innerHTML = renderMarkdown(content);
          document.getElementById('knowledge-form-preview').style.display = '';
        }
      });
    });

    // Versions modal
    document.getElementById('knowledge-versions-close').addEventListener('click', () => closeModal('knowledge-versions-modal'));

    // Click outside modal to close
    ['knowledge-detail-modal', 'knowledge-form-modal', 'knowledge-versions-modal'].forEach(id => {
      document.getElementById(id).addEventListener('click', function(e) {
        if (e.target === this) closeModal(id);
      });
    });
  }

  // ── API Calls ──

  async function loadBoards() {
    try {
      const res = await fetch('/api/boards');
      if (res.ok) boards = await res.json();
    } catch(e) { console.error('Failed to load boards', e); }

    // Populate scope filter
    const scopeEl = document.getElementById('knowledge-scope');
    boards.forEach(b => {
      const opt = document.createElement('option');
      opt.value = b.id;
      opt.textContent = 'Board: ' + escapeHtml(b.name);
      scopeEl.appendChild(opt);
    });

    // Populate form board select
    const formSelect = document.getElementById('knowledge-form-board-id');
    boards.forEach(b => {
      const opt = document.createElement('option');
      opt.value = b.id;
      opt.textContent = 'Board: ' + escapeHtml(b.name);
      formSelect.appendChild(opt);
    });
  }

  async function loadCategories() {
    try {
      const params = new URLSearchParams();
      const scopeVal = document.getElementById('knowledge-scope').value;
      if (scopeVal && scopeVal !== 'global') params.set('board_id', scopeVal);
      const res = await fetch('/api/knowledge/categories?' + params.toString());
      if (res.ok) categories = await res.json();
    } catch(e) { console.error('Failed to load categories', e); }

    const catEl = document.getElementById('knowledge-category');
    // Keep "All Categories" option, remove others
    while (catEl.options.length > 1) catEl.removeChild(catEl.lastChild);
    categories.forEach(c => {
      const opt = document.createElement('option');
      opt.value = c;
      opt.textContent = c;
      catEl.appendChild(opt);
    });
  }

  async function loadEntries() {
    const params = new URLSearchParams();
    const scopeVal = document.getElementById('knowledge-scope').value;
    if (scopeVal === 'global') {
      // Global only: no board_id param needed (default)
    } else if (scopeVal) {
      params.set('board_id', scopeVal);
    }
    if (currentSearch) params.set('search', currentSearch);
    if (currentCategory) params.set('category', currentCategory);
    if (currentAutoContext) params.set('auto_context', '1');

    try {
      const res = await fetch('/api/knowledge?' + params.toString());
      if (res.ok) {
        const entries = await res.json();
        renderEntries(entries);
      }
    } catch(e) {
      console.error('Failed to load entries', e);
      document.getElementById('knowledge-grid').innerHTML = '<div class="knowledge-empty">Error loading entries</div>';
    }
  }

  // ── Rendering ──

  function renderEntries(entries) {
    const grid = document.getElementById('knowledge-grid');
    if (!entries.length) {
      grid.innerHTML = '<div class="knowledge-empty">No knowledge entries found. Click "+ New Entry" to create one.</div>';
      return;
    }
    grid.innerHTML = entries.map(entry => {
      const scopeLabel = entry.board_id
        ? `<span class="badge badge-scope-board">Board: ${escapeHtml(entry.board_name || '?')}</span>`
        : '<span class="badge badge-scope-global">Global</span>';
      const categoryLabel = entry.category
        ? `<span class="badge">${escapeHtml(entry.category)}</span>`
        : '';
      const autoContextLabel = entry.auto_context
        ? '<span class="badge badge-auto-context">⚡ Auto-context</span>'
        : '';
      const tagsHtml = (entry.tags || []).map(t =>
        `<span class="knowledge-tag-pill">${escapeHtml(t.name)}</span>`
      ).join('');
      const preview = (entry.content || '').substring(0, 150).replace(/\n/g, ' ');
      const date = entry.updated_at ? entry.updated_at.substring(0, 16).replace('T', ' ') : '';

      return `<div class="knowledge-card" data-id="${entry.id}" onclick="window._knowledgeView(${entry.id})">
        <div class="knowledge-card-title">${escapeHtml(entry.title)}</div>
        <div class="knowledge-card-meta">
          ${scopeLabel}${categoryLabel}${autoContextLabel}
        </div>
        ${tagsHtml ? `<div class="knowledge-tags-list">${tagsHtml}</div>` : ''}
        <div class="knowledge-card-preview">${escapeHtml(preview)}${(entry.content || '').length > 150 ? '…' : ''}</div>
        <div class="knowledge-card-date">${date}</div>
      </div>`;
    }).join('');
  }

  // ── View Detail ──

  window._knowledgeView = async function(id) {
    try {
      const res = await fetch('/api/knowledge/' + id);
      if (!res.ok) { showToast('Entry not found', 'error'); return; }
      const entry = await res.json();
      viewingEntryId = id;

      document.getElementById('knowledge-detail-title').textContent = entry.title;

      const scopeEl = document.getElementById('knowledge-detail-scope');
      if (entry.board_id) {
        scopeEl.textContent = 'Board: ' + (entry.board_name || '?');
        scopeEl.className = 'badge badge-scope-board';
      } else {
        scopeEl.textContent = 'Global';
        scopeEl.className = 'badge badge-scope-global';
      }

      const catEl = document.getElementById('knowledge-detail-category');
      if (entry.category) {
        catEl.textContent = entry.category;
        catEl.className = 'badge';
        catEl.style.display = '';
      } else {
        catEl.style.display = 'none';
      }

      const acEl = document.getElementById('knowledge-detail-auto-context');
      if (entry.auto_context) {
        acEl.textContent = '⚡ Auto-context';
        acEl.className = 'badge badge-auto-context';
        acEl.style.display = '';
      } else {
        acEl.style.display = 'none';
      }

      const date = entry.updated_at ? entry.updated_at.substring(0, 16).replace('T', ' ') : '';
      document.getElementById('knowledge-detail-date').textContent = date;

      const tagsHtml = (entry.tags || []).map(t =>
        `<span class="knowledge-tag-pill">${escapeHtml(t.name)}</span>`
      ).join('');
      document.getElementById('knowledge-detail-tags').innerHTML = tagsHtml;

      document.getElementById('knowledge-detail-content').innerHTML = renderMarkdown(entry.content);

      openModal('knowledge-detail-modal');
    } catch(e) {
      console.error('Failed to load entry', e);
      showToast('Failed to load entry', 'error');
    }
  };

  // ── Create / Edit Form ──

  function openCreateForm() {
    editingEntryId = null;
    document.getElementById('knowledge-form-heading').textContent = 'New Knowledge Entry';
    document.getElementById('knowledge-form-id').value = '';
    document.getElementById('knowledge-form-title').value = '';
    document.getElementById('knowledge-form-content').value = '';
    document.getElementById('knowledge-form-category').value = '';
    document.getElementById('knowledge-form-tags').value = '';
    document.getElementById('knowledge-form-auto-context').checked = false;
    document.getElementById('knowledge-form-sort-order').value = '0';
    document.getElementById('knowledge-form-board-id').value = '__global__';
    showWriteTab();
    openModal('knowledge-form-modal');
  }

  async function openEditForm(id) {
    try {
      const res = await fetch('/api/knowledge/' + id);
      if (!res.ok) return;
      const entry = await res.json();
      editingEntryId = id;
      document.getElementById('knowledge-form-heading').textContent = 'Edit Knowledge Entry';
      document.getElementById('knowledge-form-id').value = id;
      document.getElementById('knowledge-form-title').value = entry.title;
      document.getElementById('knowledge-form-content').value = entry.content;
      document.getElementById('knowledge-form-category').value = entry.category || '';
      document.getElementById('knowledge-form-tags').value = (entry.tags || []).map(t => t.name).join(', ');
      document.getElementById('knowledge-form-auto-context').checked = !!entry.auto_context;
      document.getElementById('knowledge-form-sort-order').value = entry.sort_order || 0;
      document.getElementById('knowledge-form-board-id').value = entry.board_id || '__global__';
      showWriteTab();
      openModal('knowledge-form-modal');
    } catch(e) {
      console.error('Failed to load entry for editing', e);
    }
  }

  async function handleFormSubmit(e) {
    e.preventDefault();
    const title = document.getElementById('knowledge-form-title').value.trim();
    const content = document.getElementById('knowledge-form-content').value;
    if (!title || !content.trim()) {
      showToast('Title and content are required', 'error');
      return;
    }

    const boardIdVal = document.getElementById('knowledge-form-board-id').value;
    const board_id = boardIdVal === '__global__' ? null : parseInt(boardIdVal);

    const data = {
      title: title,
      content: content,
      board_id: board_id,
      category: document.getElementById('knowledge-form-category').value.trim() || null,
      auto_context: document.getElementById('knowledge-form-auto-context').checked,
      tags: document.getElementById('knowledge-form-tags').value
        .split(',')
        .map(t => t.trim())
        .filter(t => t),
      sort_order: parseInt(document.getElementById('knowledge-form-sort-order').value) || 0,
    };

    try {
      let res;
      if (editingEntryId) {
        // PUT — board_id 0 means no change
        const updateData = { ...data };
        if (updateData.board_id === null) {
          updateData.board_id = null;  // set to global
        }
        res = await fetch('/api/knowledge/' + editingEntryId, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(updateData),
        });
      } else {
        res = await fetch('/api/knowledge', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data),
        });
      }

      if (res.ok) {
        showToast(editingEntryId ? 'Entry updated' : 'Entry created', 'success');
        closeModal('knowledge-form-modal');
        closeModal('knowledge-detail-modal');
        loadEntries();
        loadCategories();
      } else {
        const err = await res.json();
        showToast(err.error || 'Failed to save entry', 'error');
      }
    } catch(e) {
      console.error('Failed to save entry', e);
      showToast('Failed to save entry', 'error');
    }
  }

  // ── Versions ──

  async function showVersions(entryId) {
    try {
      const res = await fetch('/api/knowledge/' + entryId + '/versions');
      if (!res.ok) { showToast('Failed to load versions', 'error'); return; }
      const versions = await res.json();
      const listEl = document.getElementById('knowledge-versions-list');

      if (!versions.length) {
        listEl.innerHTML = '<div class="knowledge-empty">No version history yet</div>';
      } else {
        listEl.innerHTML = versions.map(v => {
          const date = v.created_at ? v.created_at.substring(0, 16).replace('T', ' ') : '';
          const byBadge = v.created_by === 'agent'
            ? '<span class="badge" style="background:#3b82f622;color:#2563eb;">Agent</span>'
            : '<span class="badge" style="background:#22c55e22;color:#16a34a;">Human</span>';
          return `<div class="knowledge-version-item">
            <div class="knowledge-version-info">
              <strong>${escapeHtml(v.title)}</strong>
              <div class="knowledge-version-by">${byBadge} ${date}</div>
            </div>
            <button class="btn small" onclick="window._knowledgeRestore(${entryId}, ${v.id})">Restore</button>
          </div>`;
        }).join('');
      }
      openModal('knowledge-versions-modal');
    } catch(e) {
      console.error('Failed to load versions', e);
      showToast('Failed to load versions', 'error');
    }
  }

  window._knowledgeRestore = async function(entryId, versionId) {
    if (!confirm('Restore this version? This will replace the current content.')) return;
    try {
      const res = await fetch('/api/knowledge/' + entryId + '/versions/' + versionId + '/restore', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      if (res.ok) {
        showToast('Version restored', 'success');
        closeModal('knowledge-versions-modal');
        loadEntries();
      } else {
        const err = await res.json();
        showToast(err.error || 'Failed to restore version', 'error');
      }
    } catch(e) {
      console.error('Failed to restore version', e);
      showToast('Failed to restore version', 'error');
    }
  };

  // ── Delete ──

  // (delete is available from the detail view — to be added later if needed)
  // For now agents can also use the DELETE API.

  // ── Helpers ──

  function openModal(id) {
    document.getElementById(id).style.display = 'flex';
  }

  function closeModal(id) {
    document.getElementById(id).style.display = 'none';
  }

  function showWriteTab() {
    document.getElementById('knowledge-form-content').style.display = '';
    document.getElementById('knowledge-form-preview').style.display = 'none';
    document.querySelectorAll('.knowledge-editor-tab').forEach(t => {
      t.classList.toggle('active', t.dataset.tab === 'write');
    });
  }

  function debounce(fn, delay) {
    let timer;
    return function(...args) {
      clearTimeout(timer);
      timer = setTimeout(() => fn.apply(this, args), delay);
    };
  }

  // ── Boot ──
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();