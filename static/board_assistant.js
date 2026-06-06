(function () {
  const bubble = document.getElementById("board-assistant-bubble");
  const panel = document.getElementById("board-assistant-panel");
  const closeBtn = document.getElementById("board-assistant-close");
  const messagesEl = document.getElementById("board-assistant-messages");
  const inputEl = document.getElementById("board-assistant-input");
  const sendBtn = document.getElementById("board-assistant-send");
  const compactBtn = document.getElementById("board-assistant-compact");
  const resetBtn = document.getElementById("board-assistant-reset");

  let savedScrollY = 0;

  function getBoardId() {
    return localStorage.getItem("activeBoard");
  }

  const savedPromptsEl = document.getElementById("board-assistant-saved-prompts");

  async function loadSavedPrompts() {
    try {
      const res = await fetch("/api/assistant/saved-prompts");
      if (!res.ok) return;
      const rows = await res.json();
      renderSavedPrompts(rows);
    } catch (e) {
      console.error("Failed to load saved prompts", e);
    }
  }

  function renderSavedPrompts(rows) {
    if (!savedPromptsEl) return;
    savedPromptsEl.innerHTML = "";
    if (rows.length === 0) {
      savedPromptsEl.innerHTML = '<span class="muted" style="font-size:0.8rem;">No saved prompts</span>';
      return;
    }
    rows.forEach(function (r) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "saved-prompt-btn";
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

  function openPanel() {
    const bid = getBoardId();
    if (!bid) {
      // No board selected — show a hint and don't open
      alert("Select a board first.");
      return;
    }
    panel.classList.add("open");
    bubble.classList.add("panel-open");
    loadHistory();
    loadSavedPrompts();
    inputEl.focus();
    if (window.innerWidth <= 640) {
      savedScrollY = window.scrollY;
      document.body.style.position = "fixed";
      document.body.style.width = "100%";
      document.body.style.top = -savedScrollY + "px";
    }
  }

  function closePanel() {
    panel.classList.remove("open");
    bubble.classList.remove("panel-open");
    if (window.innerWidth <= 640) {
      document.body.style.position = "";
      document.body.style.width = "";
      document.body.style.top = "";
      window.scrollTo(0, savedScrollY);
    }
  }

  function togglePanel() {
    if (panel.classList.contains("open")) {
      closePanel();
    } else {
      openPanel();
    }
  }

  function appendMessage(role, content, temporary) {
    const msg = document.createElement("div");
    msg.className = "assistant-message assistant-message-" + role;
    if (temporary) msg.classList.add("assistant-temporary");
    msg.textContent = content;
    messagesEl.appendChild(msg);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return msg;
  }

  function clearMessages() {
    messagesEl.innerHTML = '<div class="assistant-empty">No messages yet</div>';
  }

  async function loadHistory() {
    const bid = getBoardId();
    if (!bid) {
      clearMessages();
      return;
    }
    try {
      const res = await fetch("/api/assistant/history?board_id=" + encodeURIComponent(bid));
      const rows = await res.json();
      if (rows.length === 0) {
        clearMessages();
        return;
      }
      messagesEl.innerHTML = "";
      rows.forEach(function (r) {
        appendMessage(r.role, r.content);
      });
    } catch {
      messagesEl.innerHTML = '<div class="assistant-error">Failed to load history</div>';
    }
  }

  async function sendMessage() {
    const bid = getBoardId();
    if (!bid) {
      alert("Select a board first.");
      return;
    }
    const text = inputEl.value.trim();
    if (!text) return;
    inputEl.value = "";
    appendMessage("user", text);
    const temp = appendMessage("assistant", "Thinking…", true);
    sendBtn.disabled = true;

    try {
      const res = await fetch("/api/assistant/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          board_id: bid,
          page_url: window.location.pathname,
        }),
      });
      const data = await res.json();
      temp.classList.remove("assistant-temporary");
      if (data.error) {
        temp.textContent = "Error: " + data.error;
        temp.classList.add("assistant-error");
      } else {
        temp.textContent = data.response;
      }
    } catch (e) {
      temp.classList.remove("assistant-temporary");
      temp.textContent = "Error: " + e.message;
      temp.classList.add("assistant-error");
    } finally {
      sendBtn.disabled = false;
      inputEl.focus();
    }
  }

  async function doCompact() {
    const bid = getBoardId();
    if (!bid) {
      alert("Select a board first.");
      return;
    }
    if (!confirm("Compact board conversation into a summary and clear history?")) return;
    try {
      const res = await fetch("/api/assistant/compact", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ board_id: bid }),
      });
      const data = await res.json();
      clearMessages();
      appendMessage("assistant", "Compacted: " + (data.summary || "(empty)"));
    } catch (e) {
      appendMessage("assistant", "Compact failed: " + e.message);
    }
  }

  async function doReset() {
    const bid = getBoardId();
    if (!bid) {
      alert("Select a board first.");
      return;
    }
    if (!confirm("Reset board assistant and clear all history?")) return;
    try {
      const res = await fetch("/api/assistant/reset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ board_id: bid }),
      });
      await res.json();
      clearMessages();
      appendMessage("assistant", "Board assistant has been reset.");
    } catch (e) {
      appendMessage("assistant", "Reset failed: " + e.message);
    }
  }

  bubble.addEventListener("click", togglePanel);
  closeBtn.addEventListener("click", function (e) {
    e.stopPropagation();
    closePanel();
  });
  sendBtn.addEventListener("click", sendMessage);
  inputEl.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });
  compactBtn.addEventListener("click", doCompact);
  resetBtn.addEventListener("click", doReset);

  if (typeof ResizeObserver !== "undefined") {
    const ro = new ResizeObserver(function (entries) {
      for (let i = 0; i < entries.length; i++) {
        const w = entries[i].contentRect.width;
        document.body.style.setProperty("--board-assistant-panel-width", w + "px");
      }
    });
    ro.observe(panel);
  }

  // Hide bubble when no board is selected
  function updateVisibility() {
    const bid = getBoardId();
    if (!bid) {
      bubble.style.display = "none";
      panel.classList.remove("open");
    } else {
      bubble.style.display = "";
    }
  }
  window.addEventListener("storage", function (e) {
    if (e.key === "activeBoard") {
      updateVisibility();
      if (panel.classList.contains("open")) {
        // Reload history for the new board
        loadHistory();
      }
    }
  });
  updateVisibility();
})();
