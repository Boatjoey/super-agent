# Repository Details

## Architecture

The dependency rule and target package boundaries are defined in `docs/architecture.md`.

```text
main.go
  -> app.LoadConfig
  -> app.NewSession
       -> app/instructions.Load
       -> llm.NewModel
       -> tools.DefaultRegistry / tools.NoTools
       -> runtime.NewEngineWithExecutorAndPolicy
       -> store.OpenDefault / store.NewRepository
       -> workspace.Workspace
       -> runtime.CreatePersistentSession
  -> app.NewTUIConversation(session)
  -> tui.New(conversation port)
```

- `app/`: config and session assembly.
- `app/instructions/`: user-level spec and layered project instruction loading.
- `runtime/`: public aliases and constructors for runtime packages.
- `runtime/protocol/`: model and tool adapter contracts (`Message`, `ToolCall`, `Model`, `ToolRunner`).
- `runtime/permission/`: permission request and command classification vocabulary.
- `runtime/machine/`: state, events, runtime data, runtime-data changes, action plans, scheduled actions, transitions.
- `runtime/execution/`: scheduled-action runner, executor, action queue, action-result resolver, command analyzer, policy, approvals, run control.
- `runtime/engine/`: orchestration, state lock, lifecycle, dispatch, stale-result dropping.
- `runtime/session/`: application use cases, notification output, and persistence/workspace ports.
- `store/`: durable JSONL session metadata, transcripts, checkpoints, compaction records.
- `workspace/`: filesystem checkpoint capture and undo restoration adapter.
- `llm/`: DeepSeek, OpenAI, Claude adapters.
- `tools/`: file tools, search, patch/write tools, bash runner, registry, no-tool mode.
- `tui/`: Bubble Tea inbound adapter with runtime-independent display DTOs and a `Conversation` input port.
- `app/tui_adapter.go`: composition-boundary conversion between runtime and TUI values.
- `tests/`: external package tests by module.

## Project Instructions

`app/instructions.Load` reads the optional user-level spec from `~/.superagent/AGENTS.md`, then searches upward from the current working directory and merges project instructions from root to leaf. `AGENTS.md` wins in a directory; `CLAUDE.md` is loaded as lower-priority compatibility guidance only when that directory has no `AGENTS.md`. Each instruction file is capped at 128 KiB and oversized files return a clear path-specific error.

`app.NewSession` appends the merged instruction bundle to the built-in system prompt and passes one `system` message to the runtime. OpenAI-compatible providers send it as a chat `system` message. Claude sends it through the Anthropic `system` field. `ResetConversation` clears conversation history but preserves `system` messages. Persistent replay also preserves system messages across reset records.

## Session Persistence

Sessions are stored under `~/.superagent/sessions/<session-id>/` as `meta.json` plus `events.jsonl`. Metadata includes session id, turn id, timestamps, provider/model, cwd, title, instruction fingerprint, and instruction source paths. `runtime/session` owns durable event emission for messages, approvals, tool results, cancel, reset, errors, checkpoints, and compact records. The top-level `store` adapter replays messages for `/resume`.

During a turn the Engine owns the single scheduled-action loop. Session injects the approval waiter and emits a snapshot after every state-changing transition, so the TUI header follows live states (for example `WaitingApproval` and `RunningTool`) without taking over action scheduling. The header shows raw state names such as `Idle` and `WaitingLLM`.

TUI commands:

- `/instructions`: show loaded instruction source paths.
- `/permissions`: show current permission mode and tool approval status.
- `/permissions mode <ask|accept-edits|plan|bypass>`: change the active session permission mode.
- `/sessions`: list saved sessions.
- `/resume <id>`: load a prior transcript into the current engine.
- `/rename <id> <title>`: update session title.
- `/delete-session <id>`: remove an inactive saved session.
- `/compact [summary]`: summarize with the model when no summary is supplied, replace older non-system context with one summary message, and store original messages.
- `/undo`: restore the latest non-empty checkpoint, truncate the stored transcript to that checkpoint, and reload the conversation so workspace and history stay consistent.

TUI keys: `Enter` submits when idle and cancels/restarts with steering input while a turn runs; `Tab` queues a follow-up during a run. `Ctrl+J`, `Shift+Enter`, or `Alt+Enter` inserts a newline. Typing `/` opens the command palette; arrows select and `Tab` or `Enter` completes a command. `Esc` clears input or cancels a run, `Ctrl+U` clears input, `Ctrl+C` cancels or quits, arrows otherwise navigate multiline input or recall single-line prompts without losing the current draft, and Page Up/Down scrolls.

The full slash-command palette shows command descriptions and argument hints; compact mode shows names only.

The footer previews up to three queued follow-ups in execution order and summarizes any remaining count.
A `states:` line lists the current turn's state transitions with consecutive repeats collapsed (for example `WaitingLLM → AdvancingQueue → WaitingApproval → RunningTool`); the history resets when a new turn starts and the line hides in compact mode.
Manual cancellation with `Esc` or `Ctrl+C` clears queued follow-ups; steering cancellation preserves them.
Below 18 terminal rows, the footer enters compact mode: queue details collapse, the slash palette shows three scrolling choices, and viewport/input dimensions remain positive.
Tool approval is a selectable menu: arrows or `j`/`k` move, `Enter` confirms, and `1`/`y`, `2`/`a`, `3`/`n` remain direct shortcuts. Submitted decisions ignore repeated keys until the runtime advances.

## Default Tools

`tools.DefaultRegistry` exposes `read_file`, `list_files`, `search`, `apply_patch`, `write_file`, `run_command`, `go_test`, `format`, `git_status`, `git_diff`, and `bash`. File-oriented tools use structured JSON inputs and reject paths outside the current working directory. `run_command` supports cwd, timeout, and output limits. `git_status` and `git_diff` are read-only. `apply_patch`, `write_file`, `run_command`, `go_test`, `format`, and `bash` are risky tools and require policy approval unless the active mode allows them.

## Runtime Rule

```text
QueuedAction { RunID, ActionID, ScheduledAction }
  -> ScheduledActionRunner.Run -> ActionCompletion
  -> stale RunID check
  -> ActionResultResolver.Resolve -> transition Event
  -> SnapshotFrom(RuntimeData) -> validated MachineSnapshot
  -> Transition(snapshot, event)
  -> TransitionResult { NextState, RuntimeDataChanges, ActionPlan }
  -> RuntimeDataChangeApplier.ApplyRuntimeDataChanges on cloned RuntimeData -> ValidateRuntimeData
  -> atomic RuntimeData + ActionPlan commit
```

`ActionResultResolver` maps model/tool action results directly to events accepted by the transition table. It starts tool batches and classifies each queued call into `ToolCallNeedsApproval`, `ToolCallReadyToRun`, or `ToolCallDenied`. A denial is appended as that call's tool result, then queue processing continues so the model can choose another action. A batch is the context unit; a call is the approval and execution unit. `runtime/execution` owns command classification, protected path checks, network default-deny behavior, and structured permission requests.

Command classification is a text heuristic for approval routing, not a security boundary. Linux command tools therefore use a strict bubblewrap adapter below the classifier. The host root is read-only, the workspace is the only writable host bind, temporary/home directories are ephemeral, networking follows the configured network policy, and `prlimit` bounds CPU, address space, process count, and open files. Strict mode fails closed when its dependencies are unavailable. Unsupported platforms require explicit `sandbox.mode: off` and then run with the current user's authority.

## Runtime Terms

- `State`: current runtime phase.
- `Event`: fact that triggers a transition.
- `RuntimeDataChange`: synchronous transformation of cloned `RuntimeData`.
- `ActionPlan`: one queue plan committed with runtime data; it can clear obsolete work and schedule new work.
- `ScheduledAction`: requested work such as model calls, tool execution, queue processing, or approval waiting.
- `MachineSnapshot`: validated read-only view containing only transition guards.
- `Transition`: pure state-machine decision with state, call, and queue guards.
- `RuntimeDataChangeApplier`: applies runtime-data changes to cloned `RuntimeData` and validates it.
- `ActionQueue`: stores post-commit scheduled actions.
- `ActionResultResolver`: turns `ScheduledActionResult` into transition-ready events and applies tool policy.
- `Policy`: permission mode, allow/deny rules, command classification, and approval decision.
- `ApprovalStore`: stores always-allow and auto-approve state.
- `RunController`: owns run id, cancel function, and stale-result checks.
- `ScheduledActionRunner`: executes scheduled actions and returns `ActionCompletion` values.
- `Engine`: unified external event dispatch, the single agent loop, action queue, state lock, run lifecycle, scheduled-action drain, stale dropping.
- `Session`: channel boundary that supplies approval input, streaming output, notifications, and persistence without scheduling actions.

## Runtime Package Boundaries

- `runtime/machine/transition.go`: pure context-aware transition handlers selected from one package-private static registry keyed by state and event kind; a zero-state key represents events accepted from any state.
- `runtime/machine/state.go`: runtime state type and constants.
- `runtime/machine/runtime_data.go`: complete mutable machine data.
- `runtime/machine/action_plan.go`: post-transition action-queue plan.
- `runtime/machine/tool_batch.go`: queued tool-batch state.
- `runtime/machine/snapshot.go`: machine snapshot construction and state invariants.
- `runtime/machine/runtime_data_change.go`: runtime-data change vocabulary.
- `runtime/machine/scheduled_action.go`: post-commit scheduled-action vocabulary.
- `runtime/machine/runtime_data_change_applier.go`: transactional runtime-data change application.
- `runtime/engine/engine.go`: engine construction and dependencies.
- Engine files name `machine`, `execution`, and `protocol` types explicitly; the package has no internal alias facade.
- `runtime/engine/commands.go`: lifecycle, approval, policy, and context commands.
- `runtime/engine/action_loop.go`: transition dispatch and queued-action draining.
- `runtime/engine/query.go`: state queries and snapshots.
- `runtime/execution/scheduled_action_executor.go`: calls the model or tool runner.
- `runtime/execution/action_queue.go`: post-commit scheduled-action queue.
- `runtime/execution/scheduled_action_result.go`: scheduled-action result vocabulary.
- `runtime/execution/action_result_resolver.go`: maps action results to transition-ready events and classifies tool calls.
- `runtime/session/session.go`: serializes turns and coordinates application use cases.
- `runtime/session/notifications.go`: session-to-UI notification protocol.
- `runtime/session/turn.go`: turn I/O wiring and approval waiter.
- `runtime/session/history.go`: resume, rename, delete, compact, and undo use cases.
- `runtime/session/persistence.go`: repository notifications.
- `runtime/session/repository.go`: persistence and workspace ports, including checkpoint creation, `LoadUndoPoint`, and `TruncateAfter`.
- `store/repository.go`: `runtime/session.Repository` JSONL adapter.
- `workspace/workspace.go`: `runtime/session.Workspace` filesystem adapter.
- `tui/commands.go`: slash-command handling and turn submission.
- `tui/update.go`: Bubble Tea message routing and UI state updates.
- `tui/actions.go`: cancellation and clipboard actions.
- `tui/view.go`: top-level layout and informational views.
- `tui/styles.go`: visual theme construction.
- `store/store.go`: writes and replays durable session records. All access is serialized; creation writes the transcript first and `meta.json` last so partial failures cannot leave orphan sessions; undo uses `CheckpointUndo` (skipping empty checkpoints) and an atomic `TruncateAfter`.
- `runtime/api_*.go`: compatibility facade grouped by model, machine, execution, engine, and session. It exposes session persistence ports and metadata without importing concrete adapters. The pre-facade `ToolCallsReceived`, `ToolCallAvailable`, `EventClassifier`, and `ResultResolver` names were intentionally retired in favor of `ToolBatchReceived`/`ToolCallNeedsApproval` and `ActionResultResolver` and are not re-exported.
- `runtime/execution/command_analyzer.go`: shell command classification and metadata extraction.

## Transition Table

| State | Event | Next | RuntimeDataChanges | ActionPlan |
|---|---|---|---|---|
| Initializing | EngineReady | Idle | - | - |
| Idle | UserMessageSubmitted | WaitingLLM | AppendUserMessage | Schedule CallModel |
| WaitingLLM | AssistantMessageReceived | Idle | AppendAssistantMessage | - |
| WaitingLLM | ToolBatchReceived | AdvancingQueue | AppendAssistantMessage, SetToolCallBatch | Schedule CheckToolQueue |
| WaitingApproval | ApprovalGranted | RunningTool | SetCurrentTool, ClearPendingTool | Schedule RunTool |
| WaitingApproval | ApprovalAlwaysGranted | RunningTool | SetCurrentTool, ClearPendingTool | Schedule RunTool |
| WaitingApproval | ApprovalDenied | AdvancingQueue | ClearPendingTool, AppendToolResult | Schedule CheckToolQueue |
| RunningTool | ToolResultReceived | AdvancingQueue | AppendToolResult, ClearCurrentTool | Schedule CheckToolQueue |
| AdvancingQueue | ToolBatchFinished | WaitingLLM | ClearToolCallBatch | Schedule CallModel |
| AdvancingQueue | ToolCallNeedsApproval | WaitingApproval | SetPendingTool, AdvanceToolCallBatch | Schedule AwaitApproval |
| AdvancingQueue | ToolCallReadyToRun | RunningTool | AdvanceToolCallBatch, SetCurrentTool | Schedule RunTool |
| any | ErrorOccurred | Idle | FlushStreamingAssistant, AppendToolResult, ClearPendingTool, ClearCurrentTool, ClearToolCallBatch | Clear existing |
| any | CancelRequested | Idle | FlushStreamingAssistant, ClearPendingTool, ClearCurrentTool, ClearToolCallBatch | Clear existing |
| any | ResetRequested | Idle | ResetConversation | Clear existing |

## Git And PR Notes

- Use concise conventional commit messages, for example `fix: preserve reasoning replay`.
- Name branches by scope: `feat/session-notifications`, `fix/tool-approval`.
- PRs should include purpose, main files changed, test output, and local config notes.
- Add screenshots only for visible TUI changes.

## Config

`main.go` loads `.env` with `godotenv` for runtime switches such as `NO_TOOLS` and `YOLO`. LLM provider config is read from `~/.superagent/settings.json`, including provider name, API keys, base URLs, and model names. Permission config also lives there:

```json
{
  "permissions": {
    "mode": "ask",
    "network": "deny",
    "allow_tools": [],
    "deny_tools": [],
    "allow_command_prefixes": [],
    "deny_command_prefixes": [],
    "allow_paths": [],
    "deny_paths": [],
    "allow_env": [],
    "deny_env": []
  }
}
```

Supported permission modes are `ask`, `accept-edits`, `plan`, and `bypass`; `--yolo` maps to `bypass`. The `YOLO=true` environment variable enables bypass only when no explicit `--approval-mode` flag was passed, so a checked-in `.env` cannot silently disable permission prompts. The top-level `sandbox` settings select `strict` or `off` and configure `cpu_seconds`, `memory_mb`, `max_processes`, and `max_open_files`. Strict is the default. Invalid modes fail config load. If the settings file is missing, the app creates a template on startup.

## Build

`./scripts/build-local.sh` builds the app and installs it as `/usr/local/bin/super-agent`. Set `SUPER_AGENT_INSTALL_DIR` to override the install directory for tests or automation.

## Documentation Maintenance

At the end of each work session, update `AGENTS.md` when project rules, architecture, commands, tests, or security guidance changed. Update this file when detailed architecture or runtime flow changed.
