(function () {
  const bubble = document.getElementById("assistant-bubble");
  const panel = document.getElementById("assistant-panel");
  const closeBtn = document.getElementById("assistant-close");
  const messagesEl = document.getElementById("assistant-messages");
  const inputEl = document.getElementById("assistant-input");
  const sendBtn = document.getElementById("assistant-send");
  const compactBtn = document.getElementById("assistant-compact");
  const resetBtn = document.getElementById("assistant-reset");
  const settingsBtn = document.getElementById("assistant-settings-btn");

  let config = {};
  let savedScrollY = 0;
  let piModelsData = { models: [], thinking_levels: [] };

  const savedPromptsEl = document.getElementById("assistant-saved-prompts");

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
          autoResize();
          inputEl.focus();
        }
      };
      savedPromptsEl.appendChild(btn);
    });
  }

  async function loadPiModels() {
    try {
      const res = await fetch("/api/pi-models");
      if (res.ok) {
        piModelsData = await res.json();
      }
    } catch (e) {
      console.warn("Failed to load pi models", e);
    }
  }

  function populateModelSelect(selectEl, currentValue) {
    if (!selectEl) return;
    selectEl.innerHTML = '<option value="">default</option>';
    const models = piModelsData.models || [];
    for (const m of models) {
      const opt = document.createElement("option");
      opt.value = m.id;
      opt.textContent = m.id;
      selectEl.appendChild(opt);
    }
    if (currentValue) {
      if (!Array.from(selectEl.options).some(o => o.value === currentValue)) {
        const opt = document.createElement("option");
        opt.value = currentValue;
        opt.textContent = currentValue + " (unavailable)";
        selectEl.appendChild(opt);
      }
      selectEl.value = currentValue;
    }
  }

  function getModelThinkingLevels(modelId) {
    if (!modelId) return null;
    const models = piModelsData.models || [];
    const model = models.find(m => m.id === modelId);
    if (!model) return null;
    return model.thinking_levels || null;
  }

  function populateThinkingSelect(selectEl, currentValue, modelThinkingLevels) {
    if (!selectEl) return;
    selectEl.innerHTML = "<option value=\"\">default</option>";
    const allLevels = piModelsData.thinking_levels || ["off","minimal","low","medium","high","xhigh"];
    const levels = Array.isArray(modelThinkingLevels) ? modelThinkingLevels : allLevels;
    for (const level of levels) {
      const opt = document.createElement("option");
      opt.value = level;
      opt.textContent = level;
      selectEl.appendChild(opt);
    }
    if (currentValue && !levels.includes(currentValue)) {
      selectEl.value = "";
    } else {
      selectEl.value = currentValue || "";
    }
  }

  function getAssistantBoardId() {
    const raw = localStorage.getItem("activeBoard");
    if (!raw) return null;
    const id = parseInt(raw, 10);
    if (isNaN(id) || id <= 0) return null;
    return id;
  }

  async function saveQuickConfig() {
    const model = document.getElementById("assistant-model").value.trim() || null;
    const thinking = document.getElementById("assistant-thinking").value || "";
    try {
      const res = await fetch("/api/assistant/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model, thinking }),
      });
      const data = await res.json();
      if (!data.success) {
        showToast("Failed to save assistant config: " + (data.error || "unknown error"), "error");
      }
    } catch (e) {
      showToast("Failed to save assistant config: " + e.message, "error");
    }
  }

  async function loadConfig() {
    try {
      const res = await fetch("/api/assistant/config");
      config = await res.json();
    } catch (e) {
      console.error("Failed to load assistant config", e);
      config = { enabled: 1, auto_context: 1 };
    }
    await loadPiModels();
    populateModelSelect(document.getElementById("assistant-model"), config.model || "");
    populateThinkingSelect(document.getElementById("assistant-thinking"), config.thinking || "", getModelThinkingLevels(config.model));
    updateUIFromConfig();
  }

  function updateUIFromConfig() {
    if (!config.enabled) {
      bubble.style.display = "none";
      panel.classList.remove("open");
    } else {
      bubble.style.display = "";
    }
  }

  async function openPanel(activeRunId) {
    panel.classList.add("open");
    bubble.classList.add("panel-open");
    localStorage.setItem("assistantPanelOpen", "1");
    await loadConfig();
    await loadHistory();
    await loadSavedPrompts();
    inputEl.focus();
    if (window.innerWidth <= 640) {
      savedScrollY = window.scrollY;
      document.documentElement.style.overflow = "hidden";
      document.body.style.overflow = "hidden";
    }
    if (activeRunId) {
      await reconnectToRun(activeRunId);
    }
  }

  function closePanel() {
    panel.classList.remove("open");
    bubble.classList.remove("panel-open");
    localStorage.removeItem("assistantPanelOpen");
    if (window.innerWidth <= 640) {
      document.documentElement.style.overflow = "";
      document.body.style.overflow = "";
      window.scrollTo(0, savedScrollY);
    }
  }

  async function togglePanel() {
    if (panel.classList.contains("open")) {
      closePanel();
    } else {
      await openPanel();
    }
  }

  function appendMessage(role, content, temporary, renderMd) {
    const msg = document.createElement("div");
    msg.className = "assistant-message assistant-message-" + role;
    if (temporary) msg.classList.add("assistant-temporary");
    if (renderMd && window.renderMarkdown) {
      msg.innerHTML = `<div class="markdown-content">${window.renderMarkdown(content)}</div>`;
    } else {
      msg.textContent = content;
    }
    messagesEl.appendChild(msg);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return msg;
  }

  function clearMessages() {
    messagesEl.innerHTML = '<div class="assistant-empty">No messages yet</div>';
  }

  async function loadHistory() {
    try {
      const boardId = getAssistantBoardId();
      const url = "/api/assistant/history" + (boardId ? "?board_id=" + encodeURIComponent(boardId) : "");
      const res = await fetch(url);
      const rows = await res.json();
      if (rows.length === 0) {
        clearMessages();
        return;
      }
      messagesEl.innerHTML = "";
      rows.forEach(function (r) {
        appendMessage(r.role, r.content, false, r.role === "assistant");
      });
    } catch {
      messagesEl.innerHTML = '<div class="assistant-error">Failed to load history</div>';
    }
  }

  function formatDuration(startMs) {
    const elapsed = Math.floor((Date.now() - startMs) / 1000);
    const m = Math.floor(elapsed / 60);
    const s = elapsed % 60;
    return m + ":" + (s < 10 ? "0" + s : s);
  }

  function createStreamPlaceholder() {
    const msg = document.createElement("div");
    msg.className = "assistant-message assistant-message-assistant assistant-temporary";

    const header = document.createElement("div");
    header.className = "assistant-stream-header";

    const thinking = document.createElement("span");
    thinking.className = "thinking-indicator";
    thinking.textContent = "Thinking";

    const timer = document.createElement("span");
    timer.className = "assistant-timer";
    timer.textContent = "0:00";

    const stopBtn = document.createElement("button");
    stopBtn.className = "assistant-stop-btn";
    stopBtn.textContent = "Stop";
    stopBtn.title = "Stop generation";

    header.appendChild(thinking);
    header.appendChild(timer);
    header.appendChild(stopBtn);

    const body = document.createElement("div");
    body.className = "assistant-stream-body";

    msg.appendChild(header);
    msg.appendChild(body);

    messagesEl.appendChild(msg);
    messagesEl.scrollTop = messagesEl.scrollHeight;

    return {
      msg: msg,
      body: body,
      timer: timer,
      stopBtn: stopBtn,
      startTime: Date.now(),
      timerInterval: null,
      rawText: "",
      thinkingText: "",
      error: null,
      stopped: false,
    };
  }

  function handleStreamEvent(placeholder, eventName, payload) {
    const type = payload.type;
    if (type === "text_delta") {
      const chunk = payload.chunk || "";
      placeholder.rawText += chunk;
      // Reset reconnecting/thinking label once real content arrives
      const thinkingEl = placeholder.msg.querySelector(".thinking-indicator");
      if (thinkingEl) {
        thinkingEl.textContent = "Generating…";
      }
      const span = document.createElement("span");
      span.textContent = chunk;
      placeholder.body.appendChild(span);
      messagesEl.scrollTop = messagesEl.scrollHeight;
    } else if (type === "thinking_delta") {
      const chunk = payload.chunk || "";
      placeholder.thinkingText += chunk;
      // Reset reconnecting label once real content arrives
      const thinkingEl = placeholder.msg.querySelector(".thinking-indicator");
      if (thinkingEl) {
        thinkingEl.textContent = "Thinking…";
      }
      let block = placeholder.msg.querySelector(".assistant-thinking-block");
      if (!block) {
        block = document.createElement("div");
        block.className = "assistant-thinking-block";
        const label = document.createElement("div");
        label.className = "assistant-thinking-label";
        label.textContent = "Thinking";
        block.appendChild(label);
        const content = document.createElement("div");
        content.className = "assistant-thinking-content";
        block.appendChild(content);
        placeholder.msg.insertBefore(block, placeholder.body);
      }
      block.querySelector(".assistant-thinking-content").textContent = placeholder.thinkingText;
    } else if (type === "tool_start") {
      let badge = placeholder.msg.querySelector('.assistant-tool-badge[data-name="' + (payload.name || "") + '"]');
      if (!badge) {
        badge = document.createElement("span");
        badge.className = "assistant-tool-badge";
        badge.dataset.name = payload.name || "";
        badge.textContent = (payload.name || "tool") + "…";
        placeholder.msg.querySelector(".assistant-stream-header").appendChild(badge);
      }
    } else if (type === "tool_end") {
      const badge = placeholder.msg.querySelector('.assistant-tool-badge[data-name="' + (payload.name || "") + '"]');
      if (badge) {
        badge.textContent = (payload.name || "tool") + " ✅";
      }
    } else if (type === "done") {
      // Only use full_text from the server when no text was streamed live
      // (e.g. synthetic reconnect done event). When rawText already has
      // content from text_delta events, keep it — it is authoritative and
      // the server's full_text may be truncated if the generator stopped
      // consuming before the process finished.
      if (payload.full_text && !placeholder.rawText) {
        placeholder.rawText = payload.full_text;
      }
    } else if (type === "error") {
      placeholder.error = payload.error || "Unknown error";
    } else if (type === "stopped") {
      if (payload.partial && !placeholder.rawText) {
        placeholder.rawText = payload.partial;
      }
      placeholder.stopped = true;
    }
  }

  function finalizePlaceholder(placeholder) {
    placeholder.msg.classList.remove("assistant-temporary");
    const thinking = placeholder.msg.querySelector(".thinking-indicator");
    if (thinking) thinking.remove();
    const stopBtn = placeholder.msg.querySelector(".assistant-stop-btn");
    if (stopBtn) stopBtn.remove();

    if (placeholder.error) {
      placeholder.msg.classList.add("assistant-error");
      placeholder.body.innerHTML = window.renderMarkdown ? window.renderMarkdown("Error: " + placeholder.error) : "Error: " + placeholder.error;
    } else {
      if (window.renderMarkdown) {
        placeholder.body.innerHTML = window.renderMarkdown(placeholder.rawText);
      } else {
        placeholder.body.textContent = placeholder.rawText;
      }
    }
  }

  async function checkActiveRun() {
    try {
      const boardId = localStorage.getItem("activeBoard") || "";
      const url = "/api/assistant/active-run" + (boardId ? "?board_id=" + encodeURIComponent(boardId) : "");
      const res = await fetch(url);
      if (!res.ok) return null;
      const run = await res.json();
      return run || null;
    } catch (e) {
      console.error("Failed to check active run", e);
      return null;
    }
  }

  async function reconnectToRun(runId) {
    const placeholder = createStreamPlaceholder();
    // Show a reconnecting label while the log is replayed
    const thinkingEl = placeholder.msg.querySelector(".thinking-indicator");
    if (thinkingEl) {
      thinkingEl.textContent = "Reconnecting…";
    }
    placeholder.timerInterval = setInterval(function () {
      placeholder.timer.textContent = formatDuration(placeholder.startTime);
    }, 1000);

    sendBtn.disabled = true;
    bubble.classList.add("assistant-bubble-active");

    placeholder.stopBtn.onclick = async function () {
      try {
        await fetch("/api/assistant/stop", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ board_id: getAssistantBoardId() }),
        });
      } catch (e) {
        console.error("Stop failed", e);
      }
    };

    let buffer = "";

    try {
      const boardId = localStorage.getItem("activeBoard") || "";
      const url = "/api/assistant/stream?run_id=" + encodeURIComponent(runId) + (boardId ? "&board_id=" + encodeURIComponent(boardId) : "");
      const res = await fetch(url);
      if (!res.ok) {
        const data = await res.json().catch(function () { return { error: "Request failed" }; });
        throw new Error(data.error || "Request failed");
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunk = decoder.decode(value, { stream: true });
        buffer += chunk;

        let start = 0;
        while (true) {
          const sep = buffer.indexOf("\n\n", start);
          if (sep === -1) break;
          const block = buffer.slice(start, sep);
          start = sep + 2;

          const lines = block.split("\n");
          let eventName = "message";
          const dataLines = [];
          for (let i = 0; i < lines.length; i++) {
            const line = lines[i];
            if (line.startsWith("event:")) {
              eventName = line.slice(6).trim();
            } else if (line.startsWith("data:")) {
              dataLines.push(line.slice(5));
            }
          }
          if (!dataLines.length) continue;

          let payload;
          try {
            payload = JSON.parse(dataLines.join("\n"));
          } catch (e) {
            console.error("SSE JSON parse error", e, dataLines);
            continue;
          }
          handleStreamEvent(placeholder, eventName, payload);
        }
        buffer = buffer.slice(start);
      }
    } catch (e) {
      placeholder.error = e.message;
    } finally {
      clearInterval(placeholder.timerInterval);
      sendBtn.disabled = false;
      inputEl.focus();
      bubble.classList.remove("assistant-bubble-active");
      finalizePlaceholder(placeholder);
    }
  }

  function autoResize() {
    if (!inputEl) return;
    inputEl.style.height = "auto";
    const maxHeightPx = parseFloat(getComputedStyle(inputEl).maxHeight) || Infinity;
    inputEl.style.height = Math.min(inputEl.scrollHeight, maxHeightPx) + "px";
  }

  async function sendMessage() {
    const text = inputEl.value.trim();
    if (!text) return;
    inputEl.value = "";
    inputEl.style.height = "auto";
    appendMessage("user", text);

    const placeholder = createStreamPlaceholder();
    placeholder.timerInterval = setInterval(function () {
      placeholder.timer.textContent = formatDuration(placeholder.startTime);
    }, 1000);

    sendBtn.disabled = true;
    bubble.classList.add("assistant-bubble-active");

    placeholder.stopBtn.onclick = async function () {
      try {
        await fetch("/api/assistant/stop", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ board_id: getAssistantBoardId() }),
        });
      } catch (e) {
        console.error("Stop failed", e);
      }
    };

    let buffer = "";

    try {
      const res = await fetch("/api/assistant/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, page_url: window.location.pathname, board_id: getAssistantBoardId() }),
      });
      if (!res.ok) {
        const data = await res.json().catch(function () { return { error: "Request failed" }; });
        throw new Error(data.error || "Request failed");
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunk = decoder.decode(value, { stream: true });
        buffer += chunk;

        let start = 0;
        while (true) {
          const sep = buffer.indexOf("\n\n", start);
          if (sep === -1) break;
          const block = buffer.slice(start, sep);
          start = sep + 2;

          const lines = block.split("\n");
          let eventName = "message";
          const dataLines = [];
          for (let i = 0; i < lines.length; i++) {
            const line = lines[i];
            if (line.startsWith("event:")) {
              eventName = line.slice(6).trim();
            } else if (line.startsWith("data:")) {
              dataLines.push(line.slice(5));
            }
          }
          if (!dataLines.length) continue;

          let payload;
          try {
            payload = JSON.parse(dataLines.join("\n"));
          } catch (e) {
            console.error("SSE JSON parse error", e, dataLines);
            continue;
          }
          handleStreamEvent(placeholder, eventName, payload);
        }
        buffer = buffer.slice(start);
      }
    } catch (e) {
      placeholder.error = e.message;
    } finally {
      clearInterval(placeholder.timerInterval);
      sendBtn.disabled = false;
      inputEl.focus();
      bubble.classList.remove("assistant-bubble-active");
      finalizePlaceholder(placeholder);
    }
  }

  async function doCompact() {
    if (!confirm("Compact conversation into a summary and clear history?")) return;
    try {
      const res = await fetch("/api/assistant/compact", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ board_id: getAssistantBoardId() }),
      });
      const data = await res.json();
      clearMessages();
      appendMessage("assistant", "Compacted: " + (data.summary || "(empty)"));
    } catch (e) {
      appendMessage("assistant", "Compact failed: " + e.message);
    }
  }

  async function doReset() {
    if (!confirm("Reset assistant and clear all history?")) return;
    try {
      const res = await fetch("/api/assistant/reset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ board_id: getAssistantBoardId() }),
      });
      await res.json();
      clearMessages();
      appendMessage("assistant", "Assistant has been reset.");
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
  inputEl.addEventListener("input", autoResize);
  inputEl.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });
  compactBtn.addEventListener("click", doCompact);
  resetBtn.addEventListener("click", doReset);
  settingsBtn.addEventListener("click", function () {
    window.location.href = "/settings";
  });

  if (typeof ResizeObserver !== "undefined") {
    const ro = new ResizeObserver(function (entries) {
      for (let i = 0; i < entries.length; i++) {
        const w = entries[i].contentRect.width;
        document.body.style.setProperty("--assistant-panel-width", w + "px");
      }
    });
    ro.observe(panel);
  }

  const modelSelect = document.getElementById("assistant-model");
  const thinkingSelect = document.getElementById("assistant-thinking");
  if (modelSelect) {
    modelSelect.addEventListener("change", function () {
      const thinkingLevels = getModelThinkingLevels(this.value);
      populateThinkingSelect(thinkingSelect, thinkingSelect.value, thinkingLevels);
      saveQuickConfig();
    });
  }
  if (thinkingSelect) {
    thinkingSelect.addEventListener("change", saveQuickConfig);
  }

  async function initAssistant() {
    await loadConfig();
    const run = await checkActiveRun();
    if (run && run.id) {
      await openPanel(run.id);
    } else if (localStorage.getItem("assistantPanelOpen") === "1") {
      await openPanel();
    }
  }

  initAssistant();
})();
