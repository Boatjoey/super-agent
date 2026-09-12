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
  }
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

Permission modes and command classification reduce accidental execution; they are not a sandbox. Shell syntax, absolute paths, interpreters, generated scripts, and indirect network access can evade text classification. Tools run with the current user's authority without namespace, cgroup, or seccomp isolation.

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

## Roadmap

- MCP compatibility.
- Skill compatibility.
- Cross-session memory.
- UI cleanup.
