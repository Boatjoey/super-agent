// The web front end's whole behaviour.
//
// It owns no conversation rules: everything it shows arrives as a snapshot or a
// notification from the server, and everything it does is one HTTP call. That is
// deliberate — a rebuild from /api/snapshot must produce the same screen as a
// session that streamed in, or the interface is guessing.

const state = {
  messages: [],
  streaming: null,
  status: { label: "Idle", busy: false, awaiting_approval: false },
  approval: null,
  usage: null,
  running: false,
  config: null,
  sessions: [],
  providers: [],
  error: "",
  note: "",
};

const els = {
  transcript: document.getElementById("transcript"),
  approval: document.getElementById("approval"),
  status: document.getElementById("status"),
  statusLabel: document.getElementById("status-label"),
  usage: document.getElementById("usage"),
  input: document.getElementById("input"),
  send: document.getElementById("send"),
  queue: document.getElementById("queue"),
  stop: document.getElementById("stop"),
  hint: document.getElementById("hint"),
  permission: document.getElementById("permission"),
  memory: document.getElementById("memory"),
  sessions: document.getElementById("sessions"),
  newChat: document.getElementById("new-chat"),
  model: document.getElementById("model"),
  cwd: document.getElementById("cwd"),
  toast: document.getElementById("toast"),
  settings: document.getElementById("settings"),
  settingsModal: document.getElementById("settings-modal"),
  settingsClose: document.getElementById("settings-close"),
  settingsCancel: document.getElementById("settings-cancel"),
  settingsSave: document.getElementById("settings-save"),
  settingsProvider: document.getElementById("settings-provider"),
  settingsKey: document.getElementById("settings-key"),
  settingsModel: document.getElementById("settings-model"),
  sandboxWarning: document.getElementById("sandbox-warning"),
};

const STATUS_LABELS = {
  Idle: "空闲",
  Initializing: "正在启动",
  WaitingLLM: "等待模型",
  WaitingApproval: "等待审批",
  RunningTool: "运行工具",
  AdvancingQueue: "推进队列",
  Unknown: "未知状态",
};

// --- transport -------------------------------------------------------------

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  let payload = {};
  try {
    payload = await response.json();
  } catch {
    payload = {};
  }
  if (!response.ok) {
    throw new Error(payload.error || `${response.status} ${response.statusText}`);
  }
  return payload;
}

function connect() {
  const events = new EventSource("/api/events");
  let retry = 1000;

  events.onopen = () => {
    retry = 1000;
  };
  events.onerror = () => {
    events.close();
    if (events.readyState !== EventSource.CLOSED && retry < 15000) {
      setTimeout(connect, retry);
      retry = Math.min(retry * 2, 15000);
      return;
    }
    setTimeout(connect, 2000);
  };

  for (const kind of EVENT_KINDS) {
    events.addEventListener(kind, (event) => {
      let payload = {};
      try {
        payload = JSON.parse(event.data);
      } catch {
        return;
      }
      apply(kind, payload);
    });
  }
}

const EVENT_KINDS = [
  "Snapshot",
  "TurnStarted",
  "TurnFinished",
  "AgentStatusChanged",
  "StreamChunkReceived",
  "MessageAppended",
  "ToolApprovalRequested",
  "ToolApprovalCleared",
  "UsageReported",
  "SteeringAccepted",
  "SteeringWithdrawn",
  "ConversationError",
  "UnknownNotification",
  "Closed",
];

function apply(kind, payload) {
  switch (kind) {
    case "Snapshot":
      applySnapshot(payload.snapshot);
      break;
    case "TurnStarted":
      state.running = true;
      state.error = "";
      break;
    case "TurnFinished":
      state.running = false;
      state.streaming = null;
      state.approval = null;
      if (payload.error && payload.error.message) {
        state.error = payload.error.message;
      }
      break;
    case "AgentStatusChanged":
      state.status = payload.status;
      state.running = Boolean(payload.status.busy || payload.status.awaiting_approval);
      break;
    case "StreamChunkReceived":
      state.streaming = payload.message;
      break;
    case "MessageAppended":
      state.messages.push(payload.message);
      if (payload.message.role !== "user") {
        state.streaming = null;
      }
      break;
    case "ToolApprovalRequested":
      state.approval = payload;
      break;
    case "ToolApprovalCleared":
      state.approval = null;
      break;
    case "UsageReported":
      state.usage = payload.usage;
      break;
    case "SteeringAccepted":
      toast(`输入已在第 ${payload.step} 步纳入对话`);
      break;
    case "SteeringWithdrawn":
      toast("输入未被纳入：本轮已结束");
      break;
    case "ConversationError":
      state.error = (payload.failure && payload.failure.message) || "本轮失败";
      break;
    case "UnknownNotification":
      state.error = `收到未知通知：${payload.type}`;
      break;
    case "Closed":
      setTimeout(connect, 500);
      return;
    default:
      break;
  }
  scheduleRender();
}

function applySnapshot(snapshot) {
  if (!snapshot) {
    return;
  }
  state.messages = snapshot.messages || [];
  state.streaming = snapshot.streaming_message || null;
  state.status = snapshot.agent_status;
  state.running = Boolean(snapshot.agent_status.busy || snapshot.agent_status.awaiting_approval);
  state.approval =
    snapshot.pending_permission && snapshot.pending_tool
      ? {
          tool_call: snapshot.pending_tool,
          request: snapshot.pending_permission,
          request_id: snapshot.pending_approval_id || "",
          batch_index: snapshot.pending_tool_batch_index,
          batch_total: snapshot.pending_tool_batch_total,
        }
      : null;
}

// --- rendering -------------------------------------------------------------

let renderQueued = false;

function scheduleRender() {
  if (renderQueued) {
    return;
  }
  renderQueued = true;
  requestAnimationFrame(() => {
    renderQueued = false;
    render();
  });
}

function render() {
  renderStatus();
  renderTranscript();
  renderApproval();
  renderComposer();
  renderUsage();
}

function renderStatus() {
  const busy = state.status.busy || state.running;
  const awaiting = Boolean(state.status.awaiting_approval) || Boolean(state.approval);
  els.status.classList.toggle("busy", busy && !awaiting);
  els.status.classList.toggle("approval", awaiting);
  els.status.classList.toggle("error", Boolean(state.error) && !busy);
  const label = state.error && !busy ? "上一轮失败" : STATUS_LABELS[state.status.label] || state.status.label;
  els.statusLabel.textContent = label;
}

function renderUsage() {
  if (!state.usage) {
    els.usage.textContent = "";
    return;
  }
  const total = state.usage.total_tokens || 0;
  els.usage.textContent = `tokens ${formatTokens(total)}`;
}

function formatTokens(value) {
  if (value >= 1000000) {
    return `${(value / 1000000).toFixed(1)}m`;
  }
  if (value >= 1000) {
    return `${(value / 1000).toFixed(1)}k`;
  }
  return String(value);
}

function renderTranscript() {
  const pinned = isPinnedToBottom();
  const container = els.transcript;
  container.replaceChildren();

  if (state.messages.length === 0 && !state.streaming && !state.error) {
    const empty = document.createElement("div");
    empty.className = "empty";
    const title = document.createElement("h1");
    title.textContent = "开始一个任务";
    const hint = document.createElement("p");
    hint.textContent = "描述你要做的事。Agent 会自己读代码、改文件、跑命令，需要许可时会在这里问你。";
    empty.append(title, hint);
    container.append(empty);
  }

  for (const message of state.messages) {
    container.append(renderMessage(message));
  }
  if (state.streaming) {
    container.append(renderMessage(state.streaming, { streaming: true }));
  }
  if (state.error) {
    const note = document.createElement("div");
    note.className = "note";
    note.textContent = `错误：${state.error}`;
    container.append(note);
  }
  if (pinned) {
    container.scrollTop = container.scrollHeight;
  }
}

function isPinnedToBottom() {
  const el = els.transcript;
  return el.scrollHeight - el.scrollTop - el.clientHeight < 80;
}

function renderMessage(message, options = {}) {
  const role = message.role || "user";
  const wrapper = document.createElement("div");
  wrapper.className = `msg ${role}`;

  if (role === "tool") {
    const result = document.createElement("div");
    result.className = "tool-result";
    result.textContent = message.content || "";
    wrapper.append(result);
    return wrapper;
  }

  if (role === "assistant") {
    if (message.reasoning_content) {
      const thinking = document.createElement("div");
      thinking.className = "thinking";
      thinking.textContent = message.reasoning_content;
      wrapper.append(thinking);
    }
  }

  if (message.content) {
    const body = document.createElement("div");
    body.className = "body";
    if (options.streaming) {
      body.classList.add("cursor");
    }
    renderMarkdown(body, message.content);
    wrapper.append(body);
  } else if (role === "assistant" && options.streaming) {
    const body = document.createElement("div");
    body.className = "body cursor";
    wrapper.append(body);
  }

  if (message.tool_calls && message.tool_calls.length) {
    for (const call of message.tool_calls) {
      wrapper.append(renderToolCall(call));
    }
  }

  if (message.attachments && message.attachments.length) {
    const note = document.createElement("div");
    note.className = "note";
    note.textContent = `附件：${message.attachments.map((item) => item.name).join("、")}`;
    wrapper.append(note);
  }

  if (message.interrupted) {
    const note = document.createElement("div");
    note.className = "interrupted";
    note.textContent = "（本轮被中断）";
    wrapper.append(note);
  }
  return wrapper;
}

function renderToolCall(call) {
  const row = document.createElement("div");
  row.className = "tool";
  const name = document.createElement("span");
  name.className = "tool-name";
  name.textContent = call.name || "tool";
  const detail = document.createElement("code");
  detail.textContent = summariseToolInput(call.input);
  detail.title = call.input || "";
  row.append(name, detail);
  return row;
}

function summariseToolInput(input) {
  if (!input) {
    return "";
  }
  try {
    const parsed = JSON.parse(input);
    for (const key of ["command", "path", "query", "url", "pattern"]) {
      if (typeof parsed[key] === "string" && parsed[key]) {
        return parsed[key];
      }
    }
    const text = JSON.stringify(parsed);
    return text.length > 120 ? `${text.slice(0, 117)}…` : text;
  } catch {
    return input.length > 120 ? `${input.slice(0, 117)}…` : input;
  }
}

// A small markdown renderer: fenced code, inline code, bold, paragraphs.
// Anything else stays text, which is the honest failure mode — no HTML is ever
// interpreted, so model output cannot inject markup into the page.
function renderMarkdown(container, text) {
  const segments = text.split("```");
  segments.forEach((segment, index) => {
    if (index % 2 === 1) {
      const newline = segment.indexOf("\n");
      const language = newline >= 0 ? segment.slice(0, newline).trim() : "";
      const code = newline >= 0 ? segment.slice(newline + 1) : segment;
      const pre = document.createElement("pre");
      const codeEl = document.createElement("code");
      if (language) {
        codeEl.dataset.language = language;
      }
      codeEl.textContent = code.replace(/\n$/, "");
      pre.append(codeEl);
      container.append(pre);
      return;
    }
    appendProse(container, segment);
  });
}

function appendProse(container, text) {
  const blocks = text.split(/\n{2,}/);
  for (const block of blocks) {
    if (!block.trim()) {
      continue;
    }
    const paragraph = document.createElement("p");
    const inline = block.split(/(`[^`]*`|\*\*[^*]+\*\*)/g);
    for (const piece of inline) {
      if (!piece) {
        continue;
      }
      if (piece.startsWith("`") && piece.endsWith("`") && piece.length > 1) {
        const code = document.createElement("code");
        code.textContent = piece.slice(1, -1);
        paragraph.append(code);
      } else if (piece.startsWith("**") && piece.endsWith("**") && piece.length > 4) {
        const strong = document.createElement("strong");
        strong.textContent = piece.slice(2, -2);
        paragraph.append(strong);
      } else {
        paragraph.append(document.createTextNode(piece));
      }
    }
    container.append(paragraph);
  }
}

function renderApproval() {
  const approval = state.approval;
  if (!approval) {
    els.approval.classList.add("hidden");
    els.approval.replaceChildren();
    return;
  }
  els.approval.classList.remove("hidden");
  els.approval.replaceChildren();

  const head = document.createElement("div");
  head.className = "approval-head";
  head.append(document.createTextNode(`需要许可：${approval.tool_call.name || "工具"}`));
  if (approval.batch_total > 1) {
    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = `${approval.batch_index + 1}/${approval.batch_total}`;
    head.append(badge);
  }
  els.approval.append(head);

  const detail = document.createElement("div");
  detail.className = "approval-detail";
  detail.textContent = approval.request.command || approval.tool_call.input || approval.request.tool_name;
  els.approval.append(detail);

  const meta = [];
  if (approval.request.reason) {
    meta.push(approval.request.reason);
  }
  if (approval.request.command_class) {
    meta.push(`分类：${approval.request.command_class}`);
  }
  if (approval.request.cwd) {
    meta.push(`目录：${approval.request.cwd}`);
  }
  if (approval.request.touched_paths && approval.request.touched_paths.length) {
    meta.push(`涉及：${approval.request.touched_paths.join("、")}`);
  }
  if (meta.length) {
    const metaEl = document.createElement("div");
    metaEl.className = "approval-meta";
    metaEl.textContent = meta.join(" · ");
    els.approval.append(metaEl);
  }

  const actions = document.createElement("div");
  actions.className = "approval-actions";
  actions.append(decisionButton("允许一次", "once", "btn primary"));
  actions.append(decisionButton("始终允许", "always", "btn"));
  actions.append(decisionButton("拒绝", "deny", "btn danger"));
  els.approval.append(actions);
}

function decisionButton(label, decision, className) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = className;
  button.textContent = label;
  button.addEventListener("click", async () => {
    button.disabled = true;
    // The id names the prompt this click belongs to: a second click, or one from
    // a tab that reconnected to a different prompt, is refused instead of
    // approving a tool call nobody saw.
    const request_id = (state.approval && state.approval.request_id) || "";
    try {
      await api("/api/approvals", { method: "POST", body: JSON.stringify({ decision, request_id }) });
    } catch (error) {
      toast(error.message);
      button.disabled = false;
    }
  });
  return button;
}

function renderComposer() {
  const running = state.running;
  const ready = Boolean(els.input.value.trim());
  els.stop.classList.toggle("hidden", !running);
  // Queueing only exists while a turn runs: without one there is nothing to
  // queue behind, so the button must not be there to fail a click.
  els.queue.classList.toggle("hidden", !running);
  els.send.textContent = running ? "引导" : "发送";
  els.hint.textContent = running
    ? "Enter 在当前步骤后插入 · 排队留给下一轮 · Shift+Enter 换行"
    : "Enter 发送 · Shift+Enter 换行";
  els.send.disabled = !ready;
  els.queue.disabled = !ready;
}

// --- actions ---------------------------------------------------------------

async function deliver(kind) {
  const text = els.input.value.trim();
  if (!text) {
    return;
  }
  els.input.value = "";
  autoGrow();
  els.send.disabled = true;
  els.queue.disabled = true;

  if (state.running) {
    // Two different owners for the same draft: steering joins this turn,
    // queueing becomes the next one. The port answers which one it accepted,
    // and the reason is shown rather than swallowed.
    const path = kind === "queue" ? "/api/queue" : "/api/steering";
    const accepted = kind === "queue" ? "queued" : "held";
    try {
      const receipt = await api(path, { method: "POST", body: JSON.stringify({ text }) });
      if (receipt.status === accepted) {
        toast(kind === "queue" ? "已排队，下一轮开始时接纳" : "已受理，将在当前步骤后纳入");
      } else {
        toast(`未受理：${receipt.reason || "运行时拒绝"}`);
        restoreDraft(text);
      }
    } catch (error) {
      toast(error.message);
      restoreDraft(text);
    }
    render();
    return;
  }

  try {
    await api("/api/turns", { method: "POST", body: JSON.stringify({ text }) });
  } catch (error) {
    toast(error.message);
    restoreDraft(text);
    render();
  }
}

function restoreDraft(text) {
  els.input.value = text;
  autoGrow();
}

function submit() {
  return deliver("steer");
}

function queueInput() {
  return deliver("queue");
}

async function cancel() {
  try {
    await api("/api/cancel", { method: "POST", body: "{}" });
  } catch (error) {
    toast(error.message);
  }
}

async function loadConfig() {
  try {
    const config = await api("/api/config");
    state.config = config;
    if (config.permission_mode) {
      els.permission.value = config.permission_mode;
    }
    els.model.textContent = `${config.provider || ""} ${config.model || ""}`.trim();
    renderMemory(config.memory_enabled, config.memory_backend);
    // A missing credential is the one thing worth surfacing unprompted: the
    // interface can open, but the first turn will fail until a key is entered.
    if (config.credential_missing) {
      els.settings.classList.add("attention");
    } else {
      els.settings.classList.remove("attention");
    }
    renderSandboxWarning(config.sandbox_downgraded);
  } catch {
    // The status line is decoration; a failed read must not block the interface.
  }
}

function renderSandboxWarning(downgraded) {
  if (downgraded) {
    els.sandboxWarning.textContent = "当前平台不支持严格沙箱，命令将以你的完整权限运行（无隔离）。";
    els.sandboxWarning.classList.remove("hidden");
  } else {
    els.sandboxWarning.classList.add("hidden");
  }
}

// The memory switch shows its own state: the label says whether the memory is
// in use, and the title names the backend that holds the lines.
function renderMemory(enabled, backend) {
  const on = Boolean(enabled);
  els.memory.dataset.on = on ? "true" : "false";
  els.memory.textContent = on ? "记忆 开" : "记忆 关";
  els.memory.title = on
    ? `跨会话记忆已开启（${backend || "未知位置"}），点击关闭`
    : `跨会话记忆已关闭（${backend || "未知位置"}），点击开启`;
}

async function toggleMemory() {
  const on = els.memory.dataset.on === "true";
  try {
    const memory = await api("/api/memory", {
      method: "POST",
      body: JSON.stringify({ enabled: !on }),
    });
    renderMemory(memory.enabled, memory.backend);
    toast(memory.enabled ? "跨会话记忆已开启" : "跨会话记忆已关闭");
  } catch (error) {
    toast(error.message);
    loadConfig();
  }
}

// --- provider configuration ------------------------------------------------

async function loadProviders() {
  try {
    const payload = await api("/api/providers");
    state.providers = payload.providers || [];
  } catch {
    state.providers = [];
  }
}

function openSettings() {
  els.settingsKey.value = "";
  els.settingsModel.value = "";
  els.settingsProvider.replaceChildren();
  const current = (state.config && state.config.provider) || "";
  for (const provider of state.providers) {
    const option = document.createElement("option");
    option.value = provider.name;
    option.textContent = `${provider.name}${provider.has_key ? "" : "（未配置）"}`;
    if (provider.name === current) {
      option.selected = true;
    }
    els.settingsProvider.append(option);
  }
  const selected = state.providers.find((provider) => provider.name === (els.settingsProvider.value || current));
  if (selected) {
    els.settingsModel.value = selected.model || "";
  }
  renderSandboxWarning(state.config && state.config.sandbox_downgraded);
  els.settingsModal.classList.remove("hidden");
}

function closeSettings() {
  els.settingsModal.classList.add("hidden");
}

async function saveSettings() {
  const provider = els.settingsProvider.value;
  const api_key = els.settingsKey.value.trim();
  const model = els.settingsModel.value.trim();
  if (!provider) {
    toast("请选择一个服务商");
    return;
  }
  if (!api_key) {
    toast("API Key 不能为空");
    return;
  }
  els.settingsSave.disabled = true;
  try {
    const config = await api(`/api/providers/${encodeURIComponent(provider)}`, {
      method: "POST",
      body: JSON.stringify({ api_key, model }),
    });
    state.config = config;
    els.model.textContent = `${config.provider || ""} ${config.model || ""}`.trim();
    closeSettings();
    toast("配置已保存");
    loadConfig();
    loadProviders();
  } catch (error) {
    toast(error.message);
  } finally {
    els.settingsSave.disabled = false;
  }
}

async function loadSnapshot() {
  try {
    const payload = await api("/api/snapshot");
    applySnapshot(payload.snapshot);
    state.running = Boolean(payload.running);
    scheduleRender();
  } catch (error) {
    toast(`无法读取会话：${error.message}`);
  }
}

async function loadSessions() {
  try {
    const payload = await api("/api/sessions");
    state.sessions = payload.sessions || [];
    renderSessions();
  } catch {
    state.sessions = [];
    renderSessions();
  }
}

function renderSessions() {
  els.sessions.replaceChildren();
  if (!state.sessions.length) {
    const empty = document.createElement("li");
    empty.className = "session-empty";
    empty.textContent = "还没有保存的会话";
    els.sessions.append(empty);
    return;
  }
  for (const session of state.sessions) {
    const item = document.createElement("li");
    item.className = "session";
    item.title = session.cwd || session.id;
    const title = document.createElement("span");
    title.className = "session-title";
    title.textContent = session.title || "未命名会话";
    const model = document.createElement("span");
    model.className = "session-model";
    model.textContent = session.model || "";
    item.append(title, model);
    item.addEventListener("click", async () => {
      try {
        await api(`/api/sessions/${encodeURIComponent(session.id)}/resume`, { method: "POST", body: "{}" });
        toast(`已切换到 ${session.title || session.id}`);
      } catch (error) {
        toast(error.message);
      }
    });
    els.sessions.append(item);
  }
}

function toast(message) {
  els.toast.textContent = message;
  els.toast.classList.remove("hidden");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => els.toast.classList.add("hidden"), 2600);
}

function autoGrow() {
  els.input.style.height = "auto";
  els.input.style.height = `${Math.min(els.input.scrollHeight, 220)}px`;
}

// --- wiring ----------------------------------------------------------------

els.input.addEventListener("input", () => {
  autoGrow();
  renderComposer();
});

els.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    submit();
  }
});

els.send.addEventListener("click", submit);
els.queue.addEventListener("click", queueInput);
els.stop.addEventListener("click", cancel);

els.permission.addEventListener("change", async () => {
  try {
    const config = await api("/api/permission-mode", {
      method: "POST",
      body: JSON.stringify({ mode: els.permission.value }),
    });
    state.config = config;
    toast("权限模式已更新");
  } catch (error) {
    toast(error.message);
    loadConfig();
  }
});

els.memory.addEventListener("click", toggleMemory);

els.settings.addEventListener("click", openSettings);
els.settingsClose.addEventListener("click", closeSettings);
els.settingsCancel.addEventListener("click", closeSettings);
els.settingsSave.addEventListener("click", saveSettings);
els.settingsModal.addEventListener("click", (event) => {
  if (event.target === els.settingsModal) {
    closeSettings();
  }
});

els.newChat.addEventListener("click", async () => {
  try {
    await api("/api/reset", { method: "POST", body: "{}" });
    state.messages = [];
    state.streaming = null;
    state.error = "";
    render();
  } catch (error) {
    toast(error.message);
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && state.running) {
    cancel();
  }
});

connect();
loadConfig();
loadProviders();
loadSnapshot();
loadSessions();
setInterval(loadSessions, 30000);
render();
