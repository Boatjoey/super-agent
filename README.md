# Super Agent

Go agent runtime with a state-machine core, LLM providers, local tools, and a Bubble Tea TUI.

![TUI screenshot](./static/ui.png)

## Run

- `go run .`: start the TUI. Default provider: DeepSeek.
- `go run . --no-tools`: disable tool calling.
- `go run . --yolo`: allow autonomous tool execution.
- `go run . --approval-mode <ask|accept-edits|plan|bypass>`: choose the permission mode.
- `NO_TOOLS=true go run .`: disable tools by env.
- `YOLO=true go run .`: enable bypass when no explicit approval mode is supplied.

## Test

- `go test ./...`: run all tests.
- `gofmt -w <files>`: format changed Go files.
- `./scripts/coverage.sh`: run external tests with whole-project coverage.
- `./scripts/verify.sh`: run vet, tests, race detection, and coverage.

## Build

- `./scripts/build-local.sh`: install `/usr/local/bin/super-agent`.

The binary is self-contained and can be run from any working directory. Set
`SUPER_AGENT_INSTALL_DIR` to choose another install directory. If your user
cannot write `/usr/local/bin`, run the script with `sudo`.

## Configuration

`main.go` loads `.env` with `godotenv`.

`.env` supports runtime switches:

- `NO_TOOLS=true`: disable tools.
- `YOLO=true`: auto-approve tools.

LLM provider config lives in `~/.superagent/settings.json`. On first run, the
app creates this template if the file does not exist:

```json
{
  "provider": "deepseek",
  "providers": {
    "deepseek": {
      "base_url": "https://api.deepseek.com",
      "api_key": "sk-...",
      "model": "deepseek-reasoner"
    },
    "openai": {
      "api_key": "sk-...",
      "model": "gpt-4o"
    },
    "claude": {
      "api_key": "sk-ant-...",
      "model": "claude-3-7-sonnet-20250219"
    }
  },
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
  },
  "sandbox": {
    "mode": "strict",
    "cpu_seconds": 120,
    "memory_mb": 1024,
    "max_processes": 128,
    "max_open_files": 256
  },
  "mcp_servers": {}
}
```

The built-in system prompt lives in `app/system_prompt.go` and is compiled into
the binary.

Instructions are loaded from optional `~/.superagent/AGENTS.md`, then from
project `AGENTS.md` files from root to the working directory. `CLAUDE.md` is the
fallback when a directory has no non-empty `AGENTS.md`.

## Sessions

The TUI persists sessions under `~/.superagent/sessions/`. Use `/sessions`,
`/resume`, `/rename`, and `/delete-session` to manage them. `/compact` reduces
model context, while `/undo` restores the latest workspace checkpoint and
truncates the corresponding transcript.

## Tools

Permission modes route approvals but are not the security boundary. On Linux, `sandbox.mode: strict` is the default and requires `bwrap` plus `prlimit`. It exposes the host root read-only, makes only the workspace writable, uses ephemeral temporary/home directories, denies network access unless `permissions.network` is `allow`, and applies CPU, address-space, process, and open-file limits. Strict mode fails closed when unavailable. Other platforms require explicit `sandbox.mode: off`, which runs commands with the current user's authority.

Default tools:

- `read_file`: read workspace files with optional line ranges.
- `list_files`: list workspace files with optional glob filtering.
- `search`: search workspace files by regular expression.
- `apply_patch`: replace expected text in a workspace file.
- `write_file`: write workspace files and create parent directories.
- `run_command`: run workspace commands with cwd, timeout, and output limits.
- `go_test`: run `go test` for workspace packages.
- `format`: run `gofmt -w` on workspace files.
- `git_status`: show `git status --short`.
- `git_diff`: show `git diff` for optional paths.
- `bash`: run shell commands after approval.

MCP stdio servers are configured in `mcp_servers` by name. Each entry accepts
`command`, `args`, `env`, `cwd`, `connect_timeout_seconds`, and
`call_timeout_seconds`. Discovered schemas join the built-in registry; MCP tools
are treated as risky and use the same approval flow. Server environment
variables are explicit except for basic process variables such as `PATH` and
`HOME`.

## Roadmap

- Kernel-enforced tool isolation.
- MCP and dynamic tool providers.
- Agent profiles, subagents, worktrees, and cross-session memory.
- LSP diagnostics and review workflows.
- Hooks, custom commands, skills, and plugins.
- Observability, export, multimodal input, and network tools.

The Bubble Tea TUI remains the only interaction surface; headless, server, and
alternate UI entry points are out of scope.
