// The web front end's whole behaviour, in strict TypeScript.
//
// It owns no conversation rules: everything it shows arrives as a snapshot or a
// notification from the server, and everything it does is one HTTP call. That is
// deliberate — a rebuild from /api/snapshot must produce the same screen as a
// session that streamed in, or the interface is guessing.
//
// Every JSON payload is narrowed through a type guard before use, every DOM
// lookup goes through one central helper that fails loudly when the document
// and the script drift apart, and no model-controlled string is ever parsed as
// HTML: markdown rendering uses DOM APIs only.
// --- payload guards ---------------------------------------------------------
function isRecord(value) {
    return typeof value === "object" && value !== null && !Array.isArray(value);
}
function asString(value) {
    return typeof value === "string" ? value : "";
}
function asNumber(value) {
    return typeof value === "number" && Number.isFinite(value) ? value : 0;
}
function asBoolean(value) {
    return value === true;
}
function asStringArray(value) {
    if (!Array.isArray(value)) {
        return [];
    }
    return value.filter((item) => typeof item === "string");
}
function parseToolCall(value) {
    if (!isRecord(value)) {
        return null;
    }
    return {
        id: asString(value.id),
        name: asString(value.name),
        input: asString(value.input),
    };
}
function parseAttachments(value) {
    if (!Array.isArray(value)) {
        return [];
    }
    const attachments = [];
    for (const item of value) {
        if (isRecord(item)) {
            attachments.push({ name: asString(item.name), mime: asString(item.mime) });
        }
    }
    return attachments;
}
function parseToolCalls(value) {
    if (!Array.isArray(value)) {
        return [];
    }
    const calls = [];
    for (const item of value) {
        const call = parseToolCall(item);
        if (call) {
            calls.push(call);
        }
    }
    return calls;
}
function parseMessage(value) {
    if (!isRecord(value)) {
        return null;
    }
    return {
        role: asString(value.role) || "user",
        content: asString(value.content),
        reasoning_content: asString(value.reasoning_content),
        tool_call_id: asString(value.tool_call_id),
        tool_name: asString(value.tool_name),
        tool_calls: parseToolCalls(value.tool_calls),
        interrupted: asBoolean(value.interrupted),
        attachments: parseAttachments(value.attachments),
    };
}
function parseStatus(value) {
    if (!isRecord(value)) {
        return { label: "Idle", busy: false, awaiting_approval: false };
    }
    return {
        label: asString(value.label) || "Idle",
        busy: asBoolean(value.busy),
        awaiting_approval: asBoolean(value.awaiting_approval),
    };
}
function parsePermission(value) {
    if (!isRecord(value)) {
        return null;
    }
    return {
        tool_name: asString(value.tool_name),
        command: asString(value.command),
        command_class: asString(value.command_class),
        cwd: asString(value.cwd),
        touched_paths: asStringArray(value.touched_paths),
        env_vars: asStringArray(value.env_vars),
        reason: asString(value.reason),
    };
}
function parseUsage(value) {
    if (!isRecord(value)) {
        return null;
    }
    return {
        input_tokens: asNumber(value.input_tokens),
        output_tokens: asNumber(value.output_tokens),
        total_tokens: asNumber(value.total_tokens),
    };
}
function parseFailure(value) {
    if (!isRecord(value)) {
        return null;
    }
    return {
        message: asString(value.message),
        code: asString(value.code),
        operation: asString(value.operation),
        request_id: asString(value.request_id),
    };
}
function parseApproval(toolCall, request, requestId, batchIndex, batchTotal) {
    const tool = parseToolCall(toolCall);
    const permission = parsePermission(request);
    if (!tool || !permission) {
        return null;
    }
    return {
        tool_call: tool,
        request: permission,
        request_id: requestId,
        batch_index: batchIndex,
        batch_total: batchTotal,
    };
}
function parseMessages(value) {
    if (!Array.isArray(value)) {
        return [];
    }
    const messages = [];
    for (const item of value) {
        const message = parseMessage(item);
        if (message) {
            messages.push(message);
        }
    }
    return messages;
}
function parseSnapshot(value) {
    if (!isRecord(value)) {
        return null;
    }
    return {
        agent_status: parseStatus(value.agent_status),
        messages: parseMessages(value.messages),
        pending_tool: parseToolCall(value.pending_tool),
        pending_permission: parsePermission(value.pending_permission),
        pending_tool_batch_index: asNumber(value.pending_tool_batch_index),
        pending_tool_batch_total: asNumber(value.pending_tool_batch_total),
        pending_approval_id: asString(value.pending_approval_id),
        streaming_message: parseMessage(value.streaming_message),
    };
}
function parseAgentSummary(value) {
    if (!isRecord(value)) {
        return null;
    }
    return {
        name: asString(value.name),
        provider: asString(value.provider),
        model: asString(value.model),
        permission_mode: asString(value.permission_mode),
    };
}
function parseConfig(value) {
    if (!isRecord(value)) {
        return null;
    }
    const agents = [];
    if (Array.isArray(value.agents)) {
        for (const item of value.agents) {
            const agent = parseAgentSummary(item);
            if (agent) {
                agents.push(agent);
            }
        }
    }
    return {
        session_id: asString(value.session_id),
        session_title: asString(value.session_title),
        workspace: asString(value.workspace),
        roots: asStringArray(value.roots),
        agent: asString(value.agent),
        provider: asString(value.provider),
        model: asString(value.model),
        permission_mode: asString(value.permission_mode),
        auto_approve: asBoolean(value.auto_approve),
        reasoning_effort: asString(value.reasoning_effort),
        reasoning_efforts: asStringArray(value.reasoning_efforts),
        agents,
        memory_enabled: asBoolean(value.memory_enabled),
        memory_backend: asString(value.memory_backend),
        credential_missing: asBoolean(value.credential_missing),
        sandbox_downgraded: asBoolean(value.sandbox_downgraded),
        capabilities: asStringArray(value.capabilities),
    };
}
function parseSessions(value) {
    if (!isRecord(value) || !Array.isArray(value.sessions)) {
        return [];
    }
    const sessions = [];
    for (const item of value.sessions) {
        if (!isRecord(item)) {
            continue;
        }
        sessions.push({
            id: asString(item.id),
            title: asString(item.title),
            provider: asString(item.provider),
            model: asString(item.model),
            cwd: asString(item.cwd),
            parent_id: asString(item.parent_id),
        });
    }
    return sessions;
}
function parseProviders(value) {
    if (!isRecord(value) || !Array.isArray(value.providers)) {
        return [];
    }
    const providers = [];
    for (const item of value.providers) {
        if (!isRecord(item)) {
            continue;
        }
        providers.push({
            name: asString(item.name),
            model: asString(item.model),
            base_url: asString(item.base_url),
            has_key: asBoolean(item.has_key),
        });
    }
    return providers;
}
function parseReceipt(value) {
    if (!isRecord(value)) {
        return { status: "", reason: "" };
    }
    return { status: asString(value.status), reason: asString(value.reason) };
}
function parseMemoryState(value) {
    if (!isRecord(value)) {
        return { enabled: false, backend: "" };
    }
    return { enabled: asBoolean(value.enabled), backend: asString(value.backend) };
}
function findElement(id) {
    const element = document.getElementById(id);
    if (!element) {
        throw new Error(`界面结构不完整：缺少元素 #${id}`);
    }
    return element;
}
function typedElement(id, ctor) {
    const element = findElement(id);
    if (!(element instanceof ctor)) {
        throw new Error(`界面结构不正确：#${id} 不是预期的元素类型`);
    }
    return element;
}
function loadElements() {
    return {
        sidebar: findElement("sidebar"),
        sidebarBackdrop: findElement("sidebar-backdrop"),
        sidebarClose: typedElement("sidebar-close", HTMLButtonElement),
        newChat: typedElement("new-chat", HTMLButtonElement),
        sessions: typedElement("sessions", HTMLUListElement),
        sessionTitleTop: findElement("session-title-top"),
        cwd: findElement("cwd"),
        model: findElement("model"),
        reasoning: findElement("reasoning"),
        main: findElement("main"),
        menuToggle: typedElement("menu-toggle", HTMLButtonElement),
        status: findElement("status"),
        statusLabel: findElement("status-label"),
        connection: findElement("connection"),
        connectionLabel: findElement("connection-label"),
        connectionBanner: findElement("connection-banner"),
        errorRegion: findElement("error-region"),
        usage: findElement("usage"),
        memory: typedElement("memory", HTMLButtonElement),
        settings: typedElement("settings", HTMLButtonElement),
        permission: typedElement("permission", HTMLSelectElement),
        transcript: findElement("transcript"),
        conversation: findElement("conversation"),
        approval: findElement("approval"),
        input: typedElement("input", HTMLTextAreaElement),
        send: typedElement("send", HTMLButtonElement),
        queue: typedElement("queue", HTMLButtonElement),
        stop: typedElement("stop", HTMLButtonElement),
        hint: findElement("hint"),
        toast: findElement("toast"),
        settingsModal: findElement("settings-modal"),
        settingsClose: typedElement("settings-close", HTMLButtonElement),
        settingsCancel: typedElement("settings-cancel", HTMLButtonElement),
        settingsSave: typedElement("settings-save", HTMLButtonElement),
        settingsProvider: typedElement("settings-provider", HTMLSelectElement),
        settingsKey: typedElement("settings-key", HTMLInputElement),
        settingsModel: typedElement("settings-model", HTMLInputElement),
        sandboxWarning: findElement("sandbox-warning"),
        tools: typedElement("tools", HTMLButtonElement),
        toolsModal: findElement("tools-modal"),
        toolsClose: typedElement("tools-close", HTMLButtonElement),
        toolsOutput: findElement("tools-output"),
    };
}
const els = loadElements();
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
    connection: "connecting",
    snapshotLoad: { loading: true, error: "" },
    configLoad: { loading: true, error: "" },
    sessionsLoad: { loading: true, error: "" },
    pending: {
        send: false,
        queue: false,
        stop: false,
        approval: false,
        resume: null,
        memory: false,
        permission: false,
        settingsSave: false,
        reset: false,
    },
    error: "",
    notice: "",
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
const EXAMPLES = [
    "总结这个项目的结构",
    "找出失败的测试并修复",
    "解释 web 前端的事件流设计",
];
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
    "QueuedInputAccepted",
    "QueuedInputWithdrawn",
    "ConversationError",
    "UnknownNotification",
    "Closed",
];
// --- helpers ----------------------------------------------------------------
function errorMessage(error) {
    if (error instanceof Error) {
        return error.message;
    }
    return String(error);
}
const SVG_NAMESPACE = "http://www.w3.org/2000/svg";
function svgIcon(name) {
    const svg = document.createElementNS(SVG_NAMESPACE, "svg");
    svg.setAttribute("class", "icon");
    svg.setAttribute("width", "16");
    svg.setAttribute("height", "16");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    const use = document.createElementNS(SVG_NAMESPACE, "use");
    use.setAttribute("href", `#${name}`);
    svg.append(use);
    return svg;
}
function setButtonLabel(button, text) {
    const label = button.querySelector("span");
    if (label) {
        label.textContent = text;
    }
    else {
        button.textContent = text;
    }
}
function markPending(button, pending) {
    button.toggleAttribute("data-pending", pending);
    button.setAttribute("aria-busy", String(pending));
}
function selectValues(select) {
    const values = [];
    for (let index = 0; index < select.options.length; index += 1) {
        const option = select.options.item(index);
        if (option) {
            values.push(option.value);
        }
    }
    return values;
}
// <details> already conveys its state, but the explicit aria-expanded keeps
// assistive technology and the markup in step.
function wireDetails(details) {
    const sync = () => {
        const summary = details.querySelector("summary");
        if (summary) {
            summary.setAttribute("aria-expanded", String(details.open));
        }
    };
    details.addEventListener("toggle", sync);
    sync();
}
function hasCapability(name) {
    // Before the first config read the honest answer is unknown; keep controls
    // visible rather than flashing them away, and hide them once facts arrive.
    const config = state.config;
    return config === null || config.capabilities.includes(name);
}
// --- transport --------------------------------------------------------------
async function api(path, init) {
    const response = await fetch(path, {
        headers: { "Content-Type": "application/json" },
        ...init,
    });
    let payload = {};
    try {
        payload = await response.json();
    }
    catch {
        payload = {};
    }
    if (!response.ok) {
        const message = isRecord(payload) ? asString(payload.error) : "";
        throw new Error(message || `${response.status} ${response.statusText}`);
    }
    return isRecord(payload) ? payload : {};
}
let eventSource = null;
let reconnectTimer = 0;
let reconnectDelay = 1000;
function setConnection(next) {
    state.connection = next;
    renderConnection();
}
function scheduleReconnect() {
    if (reconnectTimer !== 0) {
        return;
    }
    const delay = reconnectDelay;
    reconnectDelay = Math.min(reconnectDelay * 2, 15000);
    reconnectTimer = window.setTimeout(() => {
        reconnectTimer = 0;
        connect();
    }, delay);
}
function connect() {
    if (reconnectTimer !== 0) {
        window.clearTimeout(reconnectTimer);
        reconnectTimer = 0;
    }
    setConnection("connecting");
    const events = new EventSource("/api/events");
    eventSource = events;
    events.onopen = () => {
        reconnectDelay = 1000;
        setConnection("online");
    };
    events.onerror = () => {
        events.close();
        if (eventSource === events) {
            eventSource = null;
        }
        setConnection("offline");
        scheduleReconnect();
    };
    for (const kind of EVENT_KINDS) {
        events.addEventListener(kind, (event) => {
            const data = event.data;
            let payload = null;
            try {
                payload = JSON.parse(data);
            }
            catch {
                return;
            }
            apply(kind, payload);
        });
    }
}
// --- events -----------------------------------------------------------------
function apply(kind, payload) {
    if (!isRecord(payload)) {
        return;
    }
    switch (kind) {
        case "Snapshot": {
            const snapshot = parseSnapshot(payload.snapshot);
            if (snapshot) {
                applySnapshot(snapshot);
                state.snapshotLoad = { loading: false, error: "" };
            }
            break;
        }
        case "TurnStarted": {
            state.running = true;
            state.error = "";
            state.notice = "";
            break;
        }
        case "TurnFinished": {
            state.running = false;
            state.streaming = null;
            state.approval = null;
            state.pending.stop = false;
            disarmStop();
            const failure = parseFailure(payload.error);
            if (!failure) {
                state.error = "";
                state.notice = "";
            }
            else if (failure.code === "cancelled") {
                // A cancelled turn is the user's own decision, not a failure: say so
                // plainly and keep what already happened on the record.
                state.error = "";
                state.notice = "本轮已取消";
            }
            else {
                state.error = failure.message || "本轮失败";
                state.notice = "";
            }
            break;
        }
        case "AgentStatusChanged": {
            state.status = parseStatus(payload.status);
            state.running = state.status.busy || state.status.awaiting_approval;
            break;
        }
        case "StreamChunkReceived": {
            state.streaming = parseMessage(payload.message);
            break;
        }
        case "MessageAppended": {
            const message = parseMessage(payload.message);
            if (message) {
                state.messages.push(message);
                if (message.role !== "user") {
                    state.streaming = null;
                }
            }
            break;
        }
        case "ToolApprovalRequested": {
            const approval = parseApproval(payload.tool_call, payload.request, asString(payload.request_id), asNumber(payload.batch_index), asNumber(payload.batch_total));
            if (approval) {
                state.approval = approval;
            }
            break;
        }
        case "ToolApprovalCleared": {
            const clearedId = asString(payload.request_id);
            if (!clearedIdMatches(clearedId)) {
                break;
            }
            state.approval = null;
            state.pending.approval = false;
            break;
        }
        case "UsageReported": {
            const usage = parseUsage(payload.usage);
            if (usage) {
                state.usage = usage;
            }
            break;
        }
        case "SteeringAccepted": {
            toast(`输入已在第 ${asNumber(payload.step)} 步纳入对话`);
            break;
        }
        case "SteeringWithdrawn": {
            toast("输入未被纳入：本轮已结束");
            break;
        }
        case "QueuedInputAccepted": {
            toast(`排队输入已成为第 ${asNumber(payload.turn)} 轮`);
            break;
        }
        case "QueuedInputWithdrawn": {
            toast("排队输入已作废：本轮被取消");
            break;
        }
        case "ConversationError": {
            const failure = parseFailure(payload.failure);
            state.error = (failure && failure.message) || "本轮失败";
            break;
        }
        case "UnknownNotification": {
            state.error = `收到未知通知：${asString(payload.type)}`;
            break;
        }
        case "Closed": {
            if (eventSource) {
                eventSource.close();
                eventSource = null;
            }
            setConnection("offline");
            scheduleReconnect();
            return;
        }
        default:
            break;
    }
    scheduleRender();
}
function clearedIdMatches(clearedId) {
    // An empty id clears unconditionally; otherwise the id must pair with the
    // pending request so a late clear cannot dismiss a newer prompt.
    if (!clearedId) {
        return true;
    }
    const approval = state.approval;
    return approval === null || approval.request_id === clearedId;
}
function applySnapshot(snapshot) {
    state.messages = [...snapshot.messages];
    state.streaming = snapshot.streaming_message;
    state.status = snapshot.agent_status;
    state.running = snapshot.agent_status.busy || snapshot.agent_status.awaiting_approval;
    const tool = snapshot.pending_tool;
    const permission = snapshot.pending_permission;
    state.approval =
        tool && permission
            ? {
                tool_call: tool,
                request: permission,
                request_id: snapshot.pending_approval_id,
                batch_index: snapshot.pending_tool_batch_index,
                batch_total: snapshot.pending_tool_batch_total,
            }
            : null;
    if (!state.approval) {
        state.pending.approval = false;
    }
}
// --- rendering --------------------------------------------------------------
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
    renderConnection();
    renderErrorRegion();
    renderStatus();
    renderTranscript();
    renderApproval();
    renderComposer();
    renderUsage();
    renderSidebar();
    renderSessions();
}
function renderConnection() {
    const online = state.connection === "online";
    const connecting = state.connection === "connecting";
    els.connectionLabel.textContent = online ? "已连接" : connecting ? "连接中" : "已断开";
    els.connection.dataset.state = state.connection;
    els.connection.classList.toggle("error", state.connection === "offline");
    els.connection.classList.toggle("busy", connecting);
    if (state.connection === "offline") {
        els.connectionBanner.classList.remove("hidden");
        els.connectionBanner.replaceChildren(svgIcon("icon-refresh"), document.createTextNode(" 事件流已断开，正在自动重连。恢复后会自动重建界面，无需重新提交任务。"));
    }
    else {
        els.connectionBanner.classList.add("hidden");
    }
}
function renderErrorRegion() {
    const snapshotError = state.snapshotLoad.error;
    const configError = state.configLoad.error;
    if (!snapshotError && !configError) {
        els.errorRegion.classList.add("hidden");
        els.errorRegion.replaceChildren();
        return;
    }
    els.errorRegion.classList.remove("hidden");
    els.errorRegion.replaceChildren();
    if (snapshotError) {
        els.errorRegion.append(errorLine(`会话读取失败：${snapshotError}`, () => {
            void loadSnapshot();
        }));
    }
    if (configError) {
        els.errorRegion.append(errorLine(`配置读取失败：${configError}`, () => {
            void loadConfig();
        }));
    }
}
function errorLine(text, retry) {
    const line = document.createElement("div");
    line.className = "error-line";
    line.append(svgIcon("icon-alert"), document.createTextNode(` ${text} `));
    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn";
    button.textContent = "重试";
    button.addEventListener("click", retry);
    line.append(button);
    return line;
}
function renderStatus() {
    const busy = state.status.busy || state.running;
    const awaiting = Boolean(state.status.awaiting_approval) || Boolean(state.approval);
    els.status.classList.toggle("busy", busy && !awaiting);
    els.status.classList.toggle("awaiting", awaiting);
    els.status.classList.toggle("error", Boolean(state.error) && !busy);
    const fallback = state.status.label;
    let label = STATUS_LABELS[fallback] ?? fallback;
    if (state.error && !busy) {
        label = "上一轮失败";
    }
    else if (awaiting) {
        label = "等待审批";
    }
    else if (busy && (fallback === "Idle" || fallback === "")) {
        // A turn can start before the application reports its first detailed
        // status. "Working" is the only claim the start event supports.
        label = "执行中";
    }
    els.statusLabel.textContent = label;
}
function renderUsage() {
    if (!state.usage) {
        els.usage.textContent = "";
        return;
    }
    els.usage.textContent = `tokens ${formatTokens(state.usage.total_tokens)}`;
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
function isPinnedToBottom() {
    const el = els.transcript;
    return el.scrollHeight - el.scrollTop - el.clientHeight < 80;
}
function renderTranscript() {
    const pinned = isPinnedToBottom();
    const container = els.conversation;
    const loading = state.snapshotLoad.loading && state.messages.length === 0 && !state.streaming;
    els.transcript.setAttribute("aria-busy", String(loading));
    container.replaceChildren();
    // First load: a structural placeholder, never a premature "no sessions".
    if (loading) {
        const skeleton = document.createElement("div");
        skeleton.className = "loading";
        skeleton.setAttribute("role", "status");
        skeleton.setAttribute("aria-label", "正在读取会话");
        for (let index = 0; index < 4; index += 1) {
            const line = document.createElement("div");
            line.className = "skeleton skeleton-line";
            skeleton.append(line);
        }
        container.append(skeleton);
        return;
    }
    // The empty state only appears after a successful read said "empty".
    const loaded = !state.snapshotLoad.loading && !state.snapshotLoad.error;
    if (loaded && state.messages.length === 0 && !state.streaming && !state.error && !state.notice) {
        container.append(renderEmptyState());
    }
    for (const message of state.messages) {
        container.append(renderMessage(message, false));
    }
    if (state.streaming) {
        container.append(renderMessage(state.streaming, true));
    }
    if (state.notice) {
        const note = document.createElement("div");
        note.className = "note";
        note.textContent = state.notice;
        container.append(note);
    }
    if (state.error) {
        const error = document.createElement("div");
        error.className = "error-banner";
        error.setAttribute("role", "alert");
        const content = document.createElement("div");
        content.className = "error-content";
        content.textContent = `本轮失败：${state.error}`;
        error.append(svgIcon("icon-alert"), content);
        container.append(error);
    }
    if (pinned) {
        els.transcript.scrollTop = els.transcript.scrollHeight;
    }
}
function renderEmptyState() {
    const empty = document.createElement("div");
    empty.className = "empty";
    const title = document.createElement("h1");
    title.className = "empty-title";
    title.textContent = "开始一个任务";
    const hint = document.createElement("p");
    hint.className = "empty-hint";
    hint.textContent = "描述你要做的事。Agent 会自己读代码、改文件、跑命令，需要许可时会在这里问你。";
    empty.append(title, hint);
    if (state.config?.credential_missing === true) {
        const warning = document.createElement("p");
        warning.className = "empty-warning";
        warning.setAttribute("role", "status");
        warning.textContent = "尚未配置模型凭据。打开右上角“配置”填写 API Key 后即可开始。";
        empty.append(warning);
    }
    const examples = document.createElement("div");
    examples.className = "example-list";
    for (const sample of EXAMPLES) {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "example";
        chip.textContent = sample;
        // An example only prepares a draft; it never fakes a submitted message.
        chip.addEventListener("click", () => {
            els.input.value = sample;
            autoGrow();
            renderComposer();
            els.input.focus();
        });
        examples.append(chip);
    }
    empty.append(examples);
    return empty;
}
function renderMessage(message, streaming) {
    const role = message.role || "user";
    const wrapper = document.createElement("div");
    wrapper.className = `msg ${role}`;
    if (role === "tool") {
        const content = message.content || "";
        const label = document.createElement("div");
        label.className = "who";
        label.textContent = message.tool_name ? `工具结果 · ${message.tool_name}` : "工具结果";
        wrapper.append(label);
        if (content.length > 600) {
            // Long results stay collapsed by default so one tool call cannot eat
            // the page; the full text remains one click away.
            const details = document.createElement("details");
            details.className = "tool-result-details";
            const summary = document.createElement("summary");
            summary.textContent = "工具结果（点击展开）";
            const result = document.createElement("div");
            result.className = "tool-result";
            result.textContent = content;
            details.append(summary, result);
            wireDetails(details);
            wrapper.append(details);
        }
        else {
            const result = document.createElement("div");
            result.className = "tool-result";
            result.textContent = content;
            wrapper.append(result);
        }
        return wrapper;
    }
    if (role === "assistant" && message.reasoning_content) {
        const thinking = document.createElement("details");
        thinking.className = "thinking";
        const summary = document.createElement("summary");
        summary.textContent = "思考过程";
        const body = document.createElement("div");
        body.className = "thinking-body";
        body.textContent = message.reasoning_content;
        thinking.append(summary, body);
        wireDetails(thinking);
        wrapper.append(thinking);
    }
    if (message.content) {
        const body = document.createElement("div");
        body.className = "body";
        if (streaming) {
            body.classList.add("cursor");
        }
        renderMarkdown(body, message.content);
        wrapper.append(body);
    }
    else if (role === "assistant" && streaming) {
        const body = document.createElement("div");
        body.className = "body cursor";
        wrapper.append(body);
    }
    if (message.tool_calls.length) {
        for (const call of message.tool_calls) {
            wrapper.append(renderToolCall(call));
        }
    }
    if (message.attachments.length) {
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
    const activity = document.createElement("div");
    activity.className = "tool-activity";
    const summary = document.createElement("div");
    summary.className = "tool-summary";
    const name = document.createElement("span");
    name.className = "tool-name";
    name.textContent = call.name || "tool";
    const detail = document.createElement("code");
    detail.className = "tool-input";
    detail.textContent = summariseToolInput(call.input);
    detail.title = call.input || "";
    summary.append(name, detail);
    activity.append(summary);
    return activity;
}
function summariseToolInput(input) {
    if (!input) {
        return "";
    }
    try {
        const parsed = JSON.parse(input);
        if (isRecord(parsed)) {
            for (const key of ["command", "path", "query", "url", "pattern"]) {
                const value = parsed[key];
                if (typeof value === "string" && value) {
                    return value;
                }
            }
        }
        const text = JSON.stringify(parsed);
        return text.length > 120 ? `${text.slice(0, 117)}…` : text;
    }
    catch {
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
            }
            else if (piece.startsWith("**") && piece.endsWith("**") && piece.length > 4) {
                const strong = document.createElement("strong");
                strong.textContent = piece.slice(2, -2);
                paragraph.append(strong);
            }
            else {
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
    head.append(svgIcon("icon-alert"), document.createTextNode(` 需要许可：${approval.tool_call.name || "工具"}`));
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
    if (approval.request.touched_paths.length) {
        meta.push(`涉及：${approval.request.touched_paths.join("、")}`);
    }
    if (approval.request.env_vars.length) {
        meta.push(`环境变量：${approval.request.env_vars.join("、")}`);
    }
    if (meta.length) {
        const metaEl = document.createElement("div");
        metaEl.className = "approval-meta";
        metaEl.textContent = meta.join(" · ");
        els.approval.append(metaEl);
    }
    const actions = document.createElement("div");
    actions.className = "approval-actions";
    if (hasCapability("approve")) {
        actions.append(decisionButton("允许一次", "once", "btn primary"), decisionButton("始终允许", "always", "btn"), decisionButton("拒绝", "deny", "btn danger"));
        els.approval.append(actions);
    }
    else {
        const unavailable = document.createElement("p");
        unavailable.className = "approval-meta";
        unavailable.textContent = "当前界面不支持提交审批决定。";
        els.approval.append(unavailable);
    }
}
function decisionButton(label, decision, className) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = className;
    button.textContent = label;
    button.disabled = state.pending.approval;
    markPending(button, state.pending.approval);
    button.addEventListener("click", () => {
        void submitDecision(decision);
    });
    return button;
}
async function submitDecision(decision) {
    if (state.pending.approval) {
        return;
    }
    const approval = state.approval;
    if (!approval) {
        return;
    }
    state.pending.approval = true;
    renderApproval();
    try {
        // The id names the prompt this click belongs to: a second click, or one
        // from a tab that reconnected to a different prompt, is refused instead
        // of approving a tool call nobody saw.
        await api("/api/approvals", {
            method: "POST",
            body: JSON.stringify({ decision, request_id: approval.request_id }),
        });
        // Buttons stay locked until ToolApprovalCleared / a snapshot confirms it.
    }
    catch (error) {
        toast(errorMessage(error), "error");
        state.pending.approval = false;
        renderApproval();
    }
}
function renderComposer() {
    const running = state.running;
    const ready = els.input.value.trim().length > 0;
    const canQueue = running && hasCapability("queue");
    const canStop = running && hasCapability("cancel");
    const canSend = running ? hasCapability("steer") : hasCapability("turn");
    const credentialMissing = state.config?.credential_missing === true;
    els.queue.classList.toggle("hidden", !canQueue);
    els.stop.classList.toggle("hidden", !canStop);
    els.send.classList.toggle("hidden", !canSend);
    setButtonLabel(els.send, running ? "引导" : "发送");
    els.send.disabled = !ready || !canSend || credentialMissing || state.pending.send || state.pending.queue;
    els.queue.disabled = !ready || credentialMissing || state.pending.queue || state.pending.send;
    markPending(els.send, state.pending.send);
    markPending(els.queue, state.pending.queue);
    if (state.pending.stop) {
        setButtonLabel(els.stop, "停止中…");
        els.stop.disabled = true;
    }
    else if (stopArmed) {
        setButtonLabel(els.stop, "确认停止");
        els.stop.disabled = false;
    }
    else {
        setButtonLabel(els.stop, "停止");
        els.stop.disabled = false;
    }
    markPending(els.stop, state.pending.stop);
    if (credentialMissing && !running) {
        els.hint.textContent = "请先在“配置”中填写模型凭据";
    }
    else {
        els.hint.textContent = running
            ? "Enter 在当前步骤后插入 · 排队留给下一轮 · Shift+Enter 换行"
            : "Enter 发送 · Shift+Enter 换行";
    }
}
function renderSidebar() {
    const config = state.config;
    const workspace = config?.workspace ?? "";
    if (!config && state.configLoad.loading) {
        els.cwd.textContent = "正在读取工作区…";
        els.model.textContent = "";
    }
    else if (!config && state.configLoad.error) {
        els.cwd.textContent = "工作区配置不可用";
        els.model.textContent = "";
    }
    else {
        els.cwd.textContent = workspace;
        els.model.textContent = config ? `${config.provider} ${config.model}`.trim() : "";
    }
    els.cwd.title = workspace ? `工作目录：${workspace}` : "工作目录";
    // An absent reasoning effort is "not provided": the row hides rather than
    // inventing a default the application never stated.
    const effort = config?.reasoning_effort ?? "";
    els.reasoning.textContent = effort ? `推理：${effort}` : "";
    els.reasoning.classList.toggle("hidden", !effort);
    els.sessionTitleTop.textContent = config?.session_title ?? "";
    if (config) {
        const mode = config.permission_mode;
        if (mode && !selectValues(els.permission).includes(mode)) {
            // Unknown modes display as-is instead of a blank select.
            const option = document.createElement("option");
            option.value = mode;
            option.textContent = mode;
            els.permission.append(option);
        }
        if (mode) {
            els.permission.value = mode;
        }
    }
    // The memory switch only exists when the application actually has the
    // port and a backend; anything else would be an entry that must fail.
    const memorySupported = config !== null && config.capabilities.includes("memory") && config.memory_backend !== "";
    els.memory.classList.toggle("hidden", !memorySupported);
    renderMemory(config?.memory_enabled === true, config?.memory_backend ?? "");
    els.settings.classList.toggle("attention", config?.credential_missing === true);
    renderSandboxWarning(config?.sandbox_downgraded === true);
}
function renderMemory(enabled, backend) {
    els.memory.dataset.on = enabled ? "true" : "false";
    els.memory.setAttribute("aria-pressed", String(enabled));
    const label = els.memory.querySelector("span");
    if (label) {
        label.textContent = enabled ? "记忆 开" : "记忆 关";
    }
    els.memory.title = enabled
        ? `跨会话记忆已开启（${backend || "未知位置"}），点击关闭`
        : `跨会话记忆已关闭（${backend || "未知位置"}），点击开启`;
}
function renderSandboxWarning(downgraded) {
    if (downgraded) {
        els.sandboxWarning.textContent =
            "当前平台不支持严格沙箱，命令将以你的完整权限运行（无隔离）。";
        els.sandboxWarning.classList.remove("hidden");
    }
    else {
        els.sandboxWarning.classList.add("hidden");
    }
}
let sessionsRenderKey = "";
function renderSessions() {
    const currentId = state.config?.session_id ?? "";
    const key = JSON.stringify({
        loading: state.sessionsLoad.loading,
        error: state.sessionsLoad.error,
        sessions: state.sessions,
        currentId,
        resume: state.pending.resume,
    });
    if (key === sessionsRenderKey) {
        return;
    }
    sessionsRenderKey = key;
    const list = els.sessions;
    list.replaceChildren();
    if (state.sessionsLoad.loading) {
        list.append(sessionNote("正在读取会话…"));
        return;
    }
    if (state.sessionsLoad.error) {
        const item = document.createElement("li");
        item.className = "session-empty";
        item.textContent = `会话列表读取失败：${state.sessionsLoad.error} `;
        const retry = document.createElement("button");
        retry.type = "button";
        retry.className = "btn";
        retry.textContent = "重试";
        retry.addEventListener("click", () => {
            void loadSessions();
        });
        item.append(retry);
        list.append(item);
        return;
    }
    if (!state.sessions.length) {
        list.append(sessionNote("还没有保存的会话"));
        return;
    }
    const canResume = hasCapability("resume");
    for (const session of state.sessions) {
        const item = document.createElement("li");
        item.className = "session";
        item.title = session.cwd || session.id;
        item.setAttribute("role", "button");
        item.tabIndex = 0;
        if (!canResume) {
            item.setAttribute("aria-disabled", "true");
            item.classList.add("disabled");
        }
        if (state.pending.resume === session.id) {
            item.setAttribute("aria-busy", "true");
        }
        if (session.id === currentId) {
            item.classList.add("active");
            item.setAttribute("aria-current", "true");
        }
        const title = document.createElement("span");
        title.className = "session-title";
        title.textContent =
            state.pending.resume === session.id ? "恢复中…" : session.title || "未命名会话";
        const model = document.createElement("span");
        model.className = "session-model";
        model.textContent = session.model || "";
        item.append(title, model);
        item.addEventListener("click", () => {
            if (canResume) {
                void resumeSession(session);
            }
        });
        item.addEventListener("keydown", (event) => {
            if (canResume && (event.key === "Enter" || event.key === " ")) {
                event.preventDefault();
                void resumeSession(session);
            }
        });
        list.append(item);
    }
}
function sessionNote(text) {
    const item = document.createElement("li");
    item.className = "session-empty";
    item.textContent = text;
    return item;
}
// --- actions ----------------------------------------------------------------
async function deliver(kind) {
    const text = els.input.value.trim();
    if (!text || state.pending.send || state.pending.queue) {
        return;
    }
    if (kind === "queue" && !hasCapability("queue")) {
        return;
    }
    if (kind === "steer" && state.running && !hasCapability("steer")) {
        return;
    }
    els.input.value = "";
    autoGrow();
    if (kind === "queue") {
        state.pending.queue = true;
    }
    else {
        state.pending.send = true;
    }
    renderComposer();
    if (kind === "turn") {
        try {
            await api("/api/turns", { method: "POST", body: JSON.stringify({ text }) });
        }
        catch (error) {
            toast(errorMessage(error), "error");
            restoreDraft(text);
        }
        finally {
            state.pending.send = false;
            renderComposer();
        }
        return;
    }
    // Two different owners for the same draft: steering joins this turn,
    // queueing becomes the next one. The port answers which one it accepted,
    // and the reason is shown rather than swallowed.
    const path = kind === "queue" ? "/api/queue" : "/api/steering";
    const accepted = kind === "queue" ? "queued" : "held";
    try {
        const receipt = parseReceipt(await api(path, { method: "POST", body: JSON.stringify({ text }) }));
        if (receipt.status === accepted) {
            toast(kind === "queue" ? "已排队：将在下一轮开始时接纳" : "已受理：将在当前步骤后纳入", "success");
        }
        else {
            toast(`未受理：${receipt.reason || "运行时拒绝"}`, "error");
            restoreDraft(text);
        }
    }
    catch (error) {
        toast(errorMessage(error), "error");
        restoreDraft(text);
    }
    finally {
        state.pending.send = false;
        state.pending.queue = false;
        renderComposer();
    }
}
function restoreDraft(text) {
    els.input.value = text;
    autoGrow();
}
function submitDraft() {
    void deliver(state.running ? "steer" : "turn");
}
function queueDraft() {
    void deliver("queue");
}
// Stopping is a two-step action: the first press only arms the intent, the
// second confirms it. A cancel request is just an intent until the
// application reports the turn finished.
let stopArmed = false;
let stopArmTimer = 0;
function disarmStop() {
    stopArmed = false;
    if (stopArmTimer !== 0) {
        window.clearTimeout(stopArmTimer);
        stopArmTimer = 0;
    }
}
function requestStop() {
    if (state.pending.stop) {
        return;
    }
    if (!stopArmed) {
        stopArmed = true;
        if (stopArmTimer !== 0) {
            window.clearTimeout(stopArmTimer);
        }
        stopArmTimer = window.setTimeout(() => {
            stopArmTimer = 0;
            stopArmed = false;
            renderComposer();
        }, 3000);
        renderComposer();
        return;
    }
    disarmStop();
    void confirmStop();
}
async function confirmStop() {
    if (state.pending.stop) {
        return;
    }
    state.pending.stop = true;
    renderComposer();
    try {
        await api("/api/cancel", { method: "POST", body: "{}" });
        // Remains "停止中…" until TurnFinished reports the turn actually ended.
    }
    catch (error) {
        toast(errorMessage(error), "error");
        state.pending.stop = false;
        renderComposer();
    }
}
// --- mobile drawer ----------------------------------------------------------
function drawerOpen() {
    return document.body.classList.contains("sidebar-open");
}
function openDrawer() {
    document.body.classList.add("sidebar-open");
    els.sidebarBackdrop.classList.remove("hidden");
    els.sidebarClose.classList.remove("hidden");
    els.menuToggle.setAttribute("aria-expanded", "true");
    els.sidebarClose.focus();
}
function closeDrawer() {
    const wasOpen = drawerOpen();
    document.body.classList.remove("sidebar-open");
    els.sidebarBackdrop.classList.add("hidden");
    els.sidebarClose.classList.add("hidden");
    els.menuToggle.setAttribute("aria-expanded", "false");
    if (wasOpen) {
        els.menuToggle.focus();
    }
}
// --- settings modal ---------------------------------------------------------
let settingsReturnFocus = null;
function settingsFocusables() {
    const nodes = els.settingsModal.querySelectorAll("button, select, input");
    return Array.from(nodes).filter((node) => !node.hasAttribute("disabled"));
}
async function openSettings() {
    if (!state.providers.length) {
        await loadProviders();
        if (!state.providers.length) {
            toast("无法读取服务商列表", "error");
        }
    }
    settingsReturnFocus = els.settings;
    els.settingsKey.value = "";
    els.settingsProvider.replaceChildren();
    const current = state.config?.provider ?? "";
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
    els.settingsModel.value = selected?.model ?? "";
    renderSandboxWarning(state.config?.sandbox_downgraded === true);
    els.settingsModal.classList.remove("hidden");
    if (els.settingsProvider.options.length > 0) {
        els.settingsProvider.focus();
    }
    else {
        els.settingsKey.focus();
    }
}
function closeSettings() {
    els.settingsModal.classList.add("hidden");
    if (settingsReturnFocus) {
        settingsReturnFocus.focus();
        settingsReturnFocus = null;
    }
}
async function saveSettings() {
    if (state.pending.settingsSave) {
        return;
    }
    const provider = els.settingsProvider.value;
    const apiKey = els.settingsKey.value.trim();
    const model = els.settingsModel.value.trim();
    if (!provider) {
        toast("请选择一个服务商");
        return;
    }
    if (!apiKey) {
        toast("API Key 不能为空");
        return;
    }
    state.pending.settingsSave = true;
    els.settingsSave.disabled = true;
    markPending(els.settingsSave, true);
    try {
        const config = parseConfig(await api(`/api/providers/${encodeURIComponent(provider)}`, {
            method: "POST",
            body: JSON.stringify({ api_key: apiKey, model }),
        }));
        if (config) {
            state.config = config;
        }
        closeSettings();
        toast("配置已保存", "success");
        renderSidebar();
        void loadProviders();
        void loadConfig();
    }
    catch (error) {
        toast(errorMessage(error), "error");
    }
    finally {
        state.pending.settingsSave = false;
        els.settingsSave.disabled = false;
        markPending(els.settingsSave, false);
    }
}
// --- tools and session operations -------------------------------------------
function toolsFocusables() {
    const nodes = els.toolsModal.querySelectorAll("button, input, select, textarea");
    return Array.from(nodes).filter((node) => !node.hasAttribute("disabled"));
}
function openTools() {
    els.toolsModal.classList.remove("hidden");
    els.toolsOutput.textContent = "";
    els.toolsClose.focus();
}
function closeTools() {
    els.toolsModal.classList.add("hidden");
    els.tools.focus();
}
function toolsShow(value) {
    els.toolsOutput.textContent = JSON.stringify(value, null, 2);
}
async function toolsCall(path, init) {
    try {
        toolsShow(await api(path, init));
    }
    catch (error) {
        toast(errorMessage(error), "error");
    }
}
function promptText(label, value = "") {
    const answer = window.prompt(label, value);
    return answer === null ? null : answer.trim();
}
function splitArguments(value) {
    return value.split(/\s+/).filter((item) => item.length > 0);
}
function activeSessionId() {
    const sessionId = state.config?.session_id ?? "";
    if (!sessionId) {
        toast("当前没有活动会话", "error");
    }
    return sessionId;
}
async function toolsMcpAdd() {
    const name = promptText("MCP 服务器名称");
    if (name === null || !name)
        return;
    const command = promptText("启动命令");
    if (command === null || !command)
        return;
    const args = promptText("参数（空格分隔，可留空）");
    if (args === null)
        return;
    await toolsCall("/api/mcp", {
        method: "POST",
        body: JSON.stringify({ name, command, args: splitArguments(args) }),
    });
}
async function toolsMcpRemove() {
    const name = promptText("要删除的 MCP 服务器名称");
    if (name === null || !name)
        return;
    await toolsCall(`/api/mcp/${encodeURIComponent(name)}`, { method: "DELETE" });
}
async function toolsMcpRestart() {
    const name = promptText("要重启的 MCP 服务器名称");
    if (name === null || !name)
        return;
    await toolsCall(`/api/mcp/${encodeURIComponent(name)}/restart`, { method: "POST" });
}
async function toolsAttach() {
    const path = promptText("工作区文件路径");
    if (path === null || !path)
        return;
    await toolsCall("/api/attachments", { method: "POST", body: JSON.stringify({ path }) });
}
async function toolsDiagnostics() {
    const path = promptText("要诊断的文件路径");
    if (path === null || !path)
        return;
    await toolsCall(`/api/workspace/diagnostics?path=${encodeURIComponent(path)}`);
}
async function toolsSession(action) {
    const sessionId = activeSessionId();
    if (!sessionId)
        return;
    const path = `/api/sessions/${encodeURIComponent(sessionId)}/${action}`;
    if (action === "compact") {
        const summary = promptText("压缩摘要（可留空）", "");
        if (summary === null)
            return;
        await toolsCall(path, { method: "POST", body: JSON.stringify({ summary }) });
        return;
    }
    if (action === "fork") {
        const title = promptText("分支标题（可留空）", "");
        if (title === null)
            return;
        await toolsCall(path, { method: "POST", body: JSON.stringify({ title }) });
        return;
    }
    const format = promptText("导出格式", "markdown");
    if (format === null || !format)
        return;
    await toolsCall(path, { method: "POST", body: JSON.stringify({ format }) });
}
async function toolsRemember() {
    const text = promptText("要记住的内容");
    if (text === null || !text)
        return;
    await toolsCall("/api/memory/items", { method: "POST", body: JSON.stringify({ text }) });
}
async function toolsRename() {
    const sessionId = activeSessionId();
    if (!sessionId)
        return;
    const title = promptText("新的会话标题");
    if (title === null || !title)
        return;
    await toolsCall(`/api/sessions/${encodeURIComponent(sessionId)}/rename`, {
        method: "POST",
        body: JSON.stringify({ title }),
    });
}
async function toolsDelete() {
    const sessionId = activeSessionId();
    if (!sessionId)
        return;
    if (!window.confirm("删除当前会话？此操作不可撤销。"))
        return;
    await toolsCall(`/api/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
    void loadSessions(true);
    void loadSnapshot();
}
async function toolsExpand() {
    const name = promptText("自定义命令名称");
    if (name === null || !name)
        return;
    const args = promptText("命令参数（可留空）", "");
    if (args === null)
        return;
    await toolsCall("/api/extensions/expand", {
        method: "POST",
        body: JSON.stringify({ name, arguments: args }),
    });
}
async function toolsAgent() {
    const name = promptText("Agent 名称");
    if (name === null || !name)
        return;
    await toolsCall(`/api/agents/${encodeURIComponent(name)}`, { method: "POST" });
    void loadConfig();
}
function toolsHelp() {
    els.toolsOutput.textContent = [
        "可用操作",
        "· MCP：列表、添加、删除、重启",
        "· 附件：列出、暂存工作区文件",
        "· 仓库：Diff、Status、诊断",
        "· 会话：压缩、分支、导出、重命名、删除、撤销",
        "· 记忆：列表、记住、清空",
        "· 扩展：列表、展开自定义命令",
        "· Agent：切换",
        "· 工作流：Review、Fix CI、Commit message",
        "",
        "输入框 Enter 发送，Shift+Enter 换行；运行中可引导、排队或取消。",
    ].join("\n");
}
function wireTools() {
    els.tools.addEventListener("click", openTools);
    els.toolsClose.addEventListener("click", closeTools);
    els.toolsModal.addEventListener("click", (event) => {
        if (event.target === els.toolsModal) {
            closeTools();
        }
    });
    els.toolsModal.addEventListener("keydown", (event) => {
        if (event.key !== "Tab") {
            return;
        }
        const focusables = toolsFocusables();
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (!first || !last) {
            return;
        }
        if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
        }
        else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
        }
    });
    const actions = {
        "tools-mcp-list": () => void toolsCall("/api/mcp"),
        "tools-mcp-add": () => void toolsMcpAdd(),
        "tools-mcp-remove": () => void toolsMcpRemove(),
        "tools-mcp-restart": () => void toolsMcpRestart(),
        "tools-attach-list": () => void toolsCall("/api/attachments"),
        "tools-attach": () => void toolsAttach(),
        "tools-diff": () => void toolsCall("/api/workspace/diff"),
        "tools-status": () => void toolsCall("/api/workspace/status"),
        "tools-diagnostics": () => void toolsDiagnostics(),
        "tools-compact": () => void toolsSession("compact"),
        "tools-fork": () => void toolsSession("fork"),
        "tools-export": () => void toolsSession("export"),
        "tools-rename": () => void toolsRename(),
        "tools-delete": () => void toolsDelete(),
        "tools-undo": () => void toolsCall("/api/undo", { method: "POST", body: "{}" }),
        "tools-memory-list": () => void toolsCall("/api/memory"),
        "tools-remember": () => void toolsRemember(),
        "tools-forget": () => void toolsCall("/api/memory/items", { method: "DELETE" }),
        "tools-extensions": () => void toolsCall("/api/extensions"),
        "tools-expand": () => void toolsExpand(),
        "tools-agent": () => void toolsAgent(),
        "tools-review": () => void toolsCall("/api/workflows/review", { method: "POST", body: "{}" }),
        "tools-fix-ci": () => void toolsCall("/api/workflows/fix-ci", { method: "POST", body: "{}" }),
        "tools-commit-message": () => void toolsCall("/api/workflows/commit-message", { method: "POST", body: "{}" }),
        "tools-instructions": () => void toolsCall("/api/instructions"),
        "tools-help": toolsHelp,
    };
    for (const [id, action] of Object.entries(actions)) {
        findElement(id).addEventListener("click", action);
    }
}
// --- data loads -------------------------------------------------------------
async function loadConfig() {
    state.configLoad = { loading: true, error: "" };
    renderSidebar();
    try {
        const config = parseConfig(await api("/api/config"));
        if (!config) {
            throw new Error("配置响应格式不正确");
        }
        state.config = config;
        state.configLoad = { loading: false, error: "" };
    }
    catch (error) {
        state.configLoad = { loading: false, error: errorMessage(error) };
    }
    renderSidebar();
    renderSessions();
    renderErrorRegion();
}
async function loadProviders() {
    try {
        state.providers = parseProviders(await api("/api/providers"));
    }
    catch {
        state.providers = [];
    }
}
async function loadSnapshot() {
    state.snapshotLoad = { loading: true, error: "" };
    renderTranscript();
    renderErrorRegion();
    try {
        const payload = await api("/api/snapshot");
        const snapshot = parseSnapshot(payload.snapshot);
        if (!snapshot) {
            throw new Error("快照格式不正确");
        }
        applySnapshot(snapshot);
        if (asBoolean(payload.running)) {
            state.running = true;
        }
        const config = parseConfig(payload.config);
        if (config) {
            state.config = config;
        }
        state.snapshotLoad = { loading: false, error: "" };
    }
    catch (error) {
        // A failed read must not clear what is already on screen; it only adds
        // an error line with a retry next to it. The skeleton ends because the
        // request is no longer loading, even though it did not produce a view.
        state.snapshotLoad = {
            loading: false,
            error: errorMessage(error),
        };
    }
    scheduleRender();
}
async function loadSessions(silent = false) {
    if (!silent) {
        state.sessionsLoad = { loading: true, error: "" };
        renderSessions();
    }
    try {
        state.sessions = parseSessions(await api("/api/sessions"));
        state.sessionsLoad = { loading: false, error: "" };
    }
    catch (error) {
        // A background poll that fails keeps the last known list. The connection
        // banner already reports an offline event stream; replacing a usable list
        // with an error every thirty seconds would be worse than stale data.
        if (!silent || state.sessions.length === 0) {
            state.sessionsLoad = { loading: false, error: errorMessage(error) };
        }
    }
    renderSessions();
}
async function resumeSession(session) {
    if (state.pending.resume !== null || !hasCapability("resume")) {
        return;
    }
    state.pending.resume = session.id;
    renderSessions();
    try {
        await api(`/api/sessions/${encodeURIComponent(session.id)}/resume`, {
            method: "POST",
            body: "{}",
        });
        toast(`已切换到 ${session.title || session.id}`, "success");
        closeDrawer();
        // The pushed snapshot rebuilds the view; the configuration refresh catches
        // the new session identity and the list refresh the current-session marker.
        await loadConfig();
        await loadSessions();
    }
    catch (error) {
        toast(errorMessage(error), "error");
    }
    finally {
        state.pending.resume = null;
        renderSessions();
    }
}
async function newChat() {
    if (state.pending.reset) {
        return;
    }
    state.pending.reset = true;
    els.newChat.disabled = true;
    markPending(els.newChat, true);
    try {
        await api("/api/reset", { method: "POST", body: "{}" });
        state.messages = [];
        state.streaming = null;
        state.error = "";
        state.notice = "";
        state.approval = null;
        state.usage = null;
        state.pending.approval = false;
        closeDrawer();
        scheduleRender();
        void loadConfig();
    }
    catch (error) {
        toast(errorMessage(error), "error");
    }
    finally {
        state.pending.reset = false;
        els.newChat.disabled = false;
        markPending(els.newChat, false);
    }
}
async function toggleMemory() {
    if (state.pending.memory) {
        return;
    }
    const enabled = state.config?.memory_enabled === true;
    state.pending.memory = true;
    els.memory.disabled = true;
    markPending(els.memory, true);
    try {
        const memory = parseMemoryState(await api("/api/memory", {
            method: "POST",
            body: JSON.stringify({ enabled: !enabled }),
        }));
        const config = state.config;
        if (config) {
            state.config = {
                ...config,
                memory_enabled: memory.enabled,
                memory_backend: memory.backend || config.memory_backend,
            };
        }
        toast(memory.enabled ? "跨会话记忆已开启" : "跨会话记忆已关闭", "success");
        renderSidebar();
    }
    catch (error) {
        toast(errorMessage(error), "error");
        void loadConfig();
    }
    finally {
        state.pending.memory = false;
        els.memory.disabled = false;
        markPending(els.memory, false);
    }
}
async function changePermission() {
    if (state.pending.permission) {
        return;
    }
    const mode = els.permission.value;
    const previous = state.config?.permission_mode ?? "";
    state.pending.permission = true;
    els.permission.disabled = true;
    els.permission.setAttribute("aria-busy", "true");
    els.permission.setAttribute("data-pending", "");
    try {
        const config = parseConfig(await api("/api/permission-mode", {
            method: "POST",
            body: JSON.stringify({ mode }),
        }));
        if (config) {
            state.config = config;
        }
        toast("权限模式已更新", "success");
        renderSidebar();
    }
    catch (error) {
        toast(errorMessage(error), "error");
        if (previous) {
            els.permission.value = previous;
        }
        void loadConfig();
    }
    finally {
        state.pending.permission = false;
        els.permission.disabled = false;
        els.permission.removeAttribute("aria-busy");
        els.permission.removeAttribute("data-pending");
    }
}
// --- transient feedback -----------------------------------------------------
let toastTimer = 0;
function toast(message, kind = "info") {
    els.toast.textContent = message;
    els.toast.dataset.kind = kind;
    els.toast.classList.remove("hidden");
    if (toastTimer !== 0) {
        window.clearTimeout(toastTimer);
    }
    toastTimer = window.setTimeout(() => {
        toastTimer = 0;
        els.toast.classList.add("hidden");
    }, kind === "error" ? 4200 : 2600);
}
function autoGrow() {
    els.input.style.height = "auto";
    els.input.style.height = `${Math.min(els.input.scrollHeight, 220)}px`;
}
// --- wiring -----------------------------------------------------------------
els.input.addEventListener("input", () => {
    autoGrow();
    renderComposer();
});
els.input.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.shiftKey) {
        return;
    }
    // During IME composition Enter confirms the candidate, not the draft.
    if (event.isComposing || event.keyCode === 229) {
        return;
    }
    event.preventDefault();
    submitDraft();
});
els.send.addEventListener("click", submitDraft);
els.queue.addEventListener("click", queueDraft);
els.stop.addEventListener("click", requestStop);
els.permission.addEventListener("change", () => {
    void changePermission();
});
els.memory.addEventListener("click", () => {
    void toggleMemory();
});
els.settings.addEventListener("click", () => {
    void openSettings();
});
els.settingsClose.addEventListener("click", closeSettings);
els.settingsCancel.addEventListener("click", closeSettings);
els.settingsSave.addEventListener("click", () => {
    void saveSettings();
});
els.settingsModal.addEventListener("click", (event) => {
    if (event.target === els.settingsModal) {
        closeSettings();
    }
});
els.settingsModal.addEventListener("keydown", (event) => {
    if (event.key !== "Tab") {
        return;
    }
    const focusables = settingsFocusables();
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (!first || !last) {
        return;
    }
    if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
    }
    else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
    }
});
els.settingsProvider.addEventListener("change", () => {
    const selected = state.providers.find((provider) => provider.name === els.settingsProvider.value);
    els.settingsModel.value = selected?.model ?? "";
});
wireTools();
els.newChat.addEventListener("click", () => {
    void newChat();
});
els.menuToggle.addEventListener("click", () => {
    if (drawerOpen()) {
        closeDrawer();
    }
    else {
        openDrawer();
    }
});
els.sidebarClose.addEventListener("click", closeDrawer);
els.sidebarBackdrop.addEventListener("click", closeDrawer);
els.sidebar.addEventListener("keydown", (event) => {
    if (event.key !== "Tab" || !drawerOpen()) {
        return;
    }
    const focusables = Array.from(els.sidebar.querySelectorAll("button:not([disabled]), [role='button'][tabindex='0']"));
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (!first || !last) {
        return;
    }
    if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
    }
    else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
    }
});
// Escape closes the topmost layer first: settings dialog, the tool panel, then
// the mobile drawer, and only then — armed, not immediate — the running turn.
document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") {
        return;
    }
    if (!els.settingsModal.classList.contains("hidden")) {
        closeSettings();
        return;
    }
    if (!els.toolsModal.classList.contains("hidden")) {
        closeTools();
        return;
    }
    if (drawerOpen()) {
        closeDrawer();
        return;
    }
    if (state.running) {
        requestStop();
    }
});
// --- boot -------------------------------------------------------------------
connect();
void loadConfig();
void loadProviders();
void loadSnapshot();
void loadSessions();
window.setInterval(() => {
    void loadSessions(true);
}, 30000);
render();
export {};
