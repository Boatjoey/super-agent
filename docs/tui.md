# TUI

`tui` is the inbound adapter and the only interaction surface. It depends on its `Conversation` port
and its own display DTOs, never on `runtime` — see `architecture.md`. Runtime values become TUI values
at the composition boundary in `app/tui_adapter.go`.

## Commands

Session and configuration:

- `/instructions`: show the loaded instruction source paths.
- `/permissions`: show the current permission mode and tool approval status.
- `/permissions mode <ask|accept-edits|plan|bypass>`: change the session permission mode.
- `/sessions`, `/resume <id>`, `/rename <id> <title>`, `/delete-session <id>`, `/fork [title]`.

Agents:

- `/agent`: list built-in and configured agent profiles.
- `/agent <name>`: switch model, system instructions, and permission mode.
- `/plan`, `/build`, and `/mode <plan|build>`: shortcuts for the built-in profiles.
- Custom profiles live under `agents` in settings and may restrict tools.

MCP:

- `/mcp list`, `/mcp add <name> <command> [args...]`, `/mcp remove <name>`, `/mcp restart <name>`.

Context:

- `/memory`, `/remember <text>`, `/forget`: inspect, add, or clear cross-session memory.
- `/compact [summary]`: summarize and shrink the model context. See `session.md`.
- `/undo`: restore the latest non-empty checkpoint and truncate the transcript to match.
- `/attach <path>`, `/attachments`: queue a bounded workspace attachment for the next turn.

Workflows:

- `/review`, `/diff`, `/fix-ci`, `/branch`, `/commit-message`, `/diagnostics <path>`.
- `/export <markdown|json>` and `/share` write local files under `.super-agent/exports/`.

Extensions:

- `/commands`, `/skills`, `/plugins`: inspect discovered custom commands, `SKILL.md` instructions, and
  local plugin bundles.

## Keys

| Key | Behaviour |
|---|---|
| `Enter` | Submit when idle; cancel and restart with steering input while a turn runs |
| `Tab` | Queue a follow-up while a turn runs |
| `Ctrl+J`, `Shift+Enter`, `Alt+Enter` | Insert a newline in the composer |
| `/` | Open the command palette; arrows select, `Tab` or `Enter` completes |
| `Esc` | Clear input, or cancel a run |
| `Ctrl+U` | Clear input |
| `Ctrl+L` | Clear the visible main screen; terminal scrollback remains available |
| `Ctrl+C` | Cancel a run, or quit |
| Arrows | Navigate multiline input, or recall a single-line prompt without losing the draft |
| `Ctrl+Y` | Copy the latest assistant code block |
| `Ctrl+O` | Expand or collapse the latest tool-call group |
| `Alt+O` | Expand or collapse all tool-call groups |
| `Ctrl+T` | Expand or collapse the latest reasoning block |
| `Alt+T` | Expand or collapse all reasoning blocks |

## Mouse

The program does not capture the mouse. Selection, copying, wheel scrolling, and scrollback belong to
the terminal and use its normal bindings.

Composer rules worth knowing:

- The composer is multiline. `Enter` submits; the newline bindings above do not.
- Prompt-history navigation preserves and restores the current unsubmitted draft.
- Typing `/` opens the palette. The full palette shows descriptions and argument hints; compact mode
  shows names only.

Run rules:

- Queued prompts run in order. The footer previews the first three and summarises the remainder.
- Manual cancellation with `Esc` or `Ctrl+C` clears queued prompts. Steering cancellation preserves
  them, because the user is mid-thought rather than abandoning the work.

## Layout

The TUI uses the terminal's main screen. `View` owns the welcome block, conversation, live streaming
content, approval and command menus, composer, and status line. This single managed transcript lets
tool details expand in place without duplicating conversation history.

- The compact welcome block contains the product name, model, working directory, and final loaded
  instruction-source filename.
- User prompts are visually prominent. Assistant prose uses the available width without an extra
  left indent.
- Reasoning defaults to a compact `Thinking...` line. The reasoning text expands in place for the
  latest or all model steps with the keys above.
- Tool calls are printed as compact action summaries. Expanding or collapsing rebuilds the visible
  transcript so inputs and affected paths stay directly below their owning tool-call summary.
- The dynamic area is clamped to the terminal width and height and shows its tail when content exceeds
  the available rows.
- Reset, resume, compact, and undo rebuild the managed transcript from current conversation state.
- Below 18 terminal rows, queue details and command choices use their compact forms.
- The bottom status line contains permission mode, model, and whether tools are enabled.

## Approval UI

Tool approval is a selectable menu rather than a bare prompt:

- Arrows or `j`/`k` move the selection; `Enter` confirms.
- `1`/`y`, `2`/`a`, and `3`/`n` remain direct shortcuts for approve-once, always-approve, and deny.
- A submitted decision ignores repeated keys until the runtime advances, so a double keypress cannot
  answer the next prompt by accident.

The engine reports live states while actions run, so the header follows `WaitingApproval` and
`RunningTool` as they happen rather than only at snapshot boundaries.
