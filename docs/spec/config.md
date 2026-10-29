# 配置

## 来源

| 来源 | 提供内容 |
|---|---|
| `.env`（通过 `python-dotenv`） | `NO_TOOLS`、`YOLO` 等运行时开关 |
| `~/.superagent/settings.json` | 模型服务商、权限、沙箱、服务器、Agent、扩展、遥测 |
| 命令行参数 | `--yolo`、`--no-tools`、`--approval-mode` |
| `~/.superagent/AGENTS.md` 和项目 `AGENTS.md` | 分层指令，见 `session.md` |

`settings.json` 不存在时，应用在启动时创建模板。无效值（例如未知权限模式）会使配置加载失败，不会悄悄回退。
为兼容旧版生成的文件，集合字段上的 `null` 表示空集合；可选标量字段保留文档规定的 `null` 含义。

## 模型服务商

```json
{
  "provider": "deepseek",
  "providers": {
    "deepseek": { "base_url": "https://api.deepseek.com", "api_key": "sk-...", "model": "deepseek-reasoner" },
    "openai":   { "api_key": "sk-...", "model": "gpt-4o" },
    "claude":   { "api_key": "sk-ant-...", "model": "claude-3-7-sonnet-20250219" }
  }
}
```

`provider` 选择默认服务商。适配器位于 `llm/`；兼容 OpenAI 的服务商将系统提示词作为聊天 `system` 消息发送，Claude 则通过 Anthropic 的 `system` 字段发送。

选中服务商的凭据在配置加载时解析。模板占位符（`sk-...`、`sk-ant-...`）视为未设置；配置条目未设置凭据时，从 `<PROVIDER>_API_KEY`（例如 `DEEPSEEK_API_KEY`）获取。服务商未出现在 `providers` 中仍属配置结构错误，配置加载失败；**已列出的服务商最终没有凭据时不再阻断启动**——应用以空凭据启动，使各前端能提供配置入口，认证错误推迟到第一轮才出现。运行时的凭据与模型修改见[运行时配置](#运行时配置)。

**构建模型必须使用解析后的配置。** `new_session_with_extensions` 从解析后的条目构造适配器，不使用原始 `providers` 映射，因此仍含模板占位符的配置文件不会把 `sk-...` 作为 bearer token 发送。自定义 Agent 配置若指定其他服务商，则按原样使用该服务商条目；若覆盖 `model`，则在选中条目的基础上叠加该覆盖值。

## 运行时配置

服务商凭据与模型可在运行中修改，由终端 `/config` 与 Web 的 `GET/POST /api/providers` 提供。修改先写入 `settings.json`（重启后仍生效），成功后更新内存配置并立即重建当前模型，使新凭据在下一轮生效；保存失败时向调用方报告错误，内存中的服务商配置保持原值。凭据缺失与沙箱降级作为启动状态暴露在 `ConfigView` 的 `credential_missing` 与 `sandbox_downgraded`，前端据此提示而非静默。

## Agent 配置

顶层 `agent` 选择 `build`、`plan`，或 `agents` 中的自定义配置。自定义配置可覆盖 `provider`、`model`、`prompt`、`tools` 和 `permission_mode`：

```json
{
  "agent": "build",
  "agents": {
    "reviewer": {
      "prompt": "审查变更并报告缺陷。",
      "permission_mode": "plan",
      "tools": ["read_file", "search", "git_diff", "lsp_diagnostics"]
    }
  }
}
```

切换 Agent 配置会清空当前对话记录。

## 权限

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

模式包括 `ask`、`accept-edits`、`plan` 和 `bypass`；`--yolo` 映射为 `bypass`。

**仅在未显式传入 `--approval-mode` 时，`.env` 中的 `YOLO=true` 才启用绕过审批。** 命令行参数始终优先于环境变量，纳入版本控制的 `.env` 不能悄悄关闭权限提示。

命令分类用于决定审批路径，不是安全边界；执行隔离由 `tools.md` 中的沙箱负责。

## 沙箱

```json
{
  "sandbox": {
    "mode": "strict",
    "cpu_seconds": 120,
    "memory_mb": 1024,
    "max_processes": 128,
    "max_open_files": 256
  }
}
```

默认模式为 `strict`；`off` 显式关闭隔离。平台支持及依赖缺失时的执行行为见[工具沙箱](tools.md#沙箱)。

`strict` 依赖 Linux 的 `bubblewrap`。在非 Linux 平台，未显式设置的默认 `strict` 自动降级为 `off` 并记录 `sandbox_downgraded`，使应用仍能启动、让操作者看到“命令将以完整权限运行”的提示；显式选择 `strict` 仍按不支持处理（见[工具沙箱](tools.md#沙箱)）。

## 服务器

`mcp_servers` 按名称声明 MCP 标准输入输出服务器，每个条目接受 `command`、`args`、`env`、`cwd`、`connect_timeout_seconds` 和 `call_timeout_seconds`。除 `PATH`、`HOME` 等基础进程变量外，服务器环境变量必须通过 `env` 显式指定。

`lsp_servers` 按扩展名声明语言服务器，每个条目接受 `command`、`args`、`extensions` 和 `language_id`。服务器连接、工具发现及调用行为见[工具规范](tools.md)。

## 扩展

```json
{
  "extensions": {
    "commands": { "explain": "解释 $ARGUMENTS" },
    "hooks": { "after_turn": ["uv run pytest -q"] },
    "skills": [".superagent/skills/reviewer"],
    "plugins": [".superagent/plugins/team"]
  }
}
```

扩展提供基于提示词的斜杠命令、生命周期钩子、`SKILL.md` 指令和本地插件清单。工具钩子必须使用不会递归触发自身的直接执行路径，避免重新进入调用它的观察者。钩子事件覆盖会话开始、轮次前后、工具调用前后、审批和错误。

应用还会从用户级和项目级 `.superagent/` 目录发现命令、技能和插件。

## 遥测

```json
{ "telemetry": { "log_path": "/absolute/or/workspace/relative.jsonl" } }
```

默认路径为 `~/.superagent/telemetry.jsonl`。记录及字段见 `runtime.md`。

## 交互式命令行

```json
{
  "tui": {
    "status_line": ["model", "approval", "context_usage"],
    "syntax_theme": "ansi_dark"
  }
}
```

`status_line` 当前仅为配置文件兼容性而保留，现有 `TerminalApplication` 不消费它，未知条目仍会使配置加载失败。这是当前实现状态，不约束 [UI 设计](../design/ui.md)要求的目标状态提示。对标界面的状态行与该配置如何衔接，应在实现时同步更新本规范，当前不能将该设置描述为已经生效。

`syntax_theme` 指定围栏代码块的语法高亮主题。`ansi_dark` 和 `ansi_light` 与界面其他部分一样使用终端自身调色板；其他命名主题自带颜色。该设置只影响代码块，界面颜色由 [UI 终端视觉规则](../design/ui.md#终端视觉规则) 规定，不可配置。

## 命令行参数与环境变量

`--cwd <directory>` 显式选择项目目录。相对值以进程 cwd 为基准解析。未指定时，从进程 cwd 向上查找 `.git`，找不到则回退到该 cwd。解析出的项目根目录成为初始工作区主根目录和 cwd。

| 开关 | 效果 |
|---|---|
| `--cwd <directory>` | 显式选择项目目录 |
| `--yolo` | 自动批准工具，映射为 `bypass` |
| `--no-tools` | 禁用工具调用 |
| `--approval-mode <ask\|accept-edits\|plan\|bypass>` | 设置权限模式 |
| `NO_TOOLS=true` | 通过环境变量禁用工具 |
| `YOLO=true` | 未显式传入参数时启用绕过审批 |

## 配置与存储路径

配置目录有三种拼写，不得统一：`~/.superagent/`（用户目录，无连字符）、`<cwd>/.superagent/`（项目扩展，无连字符），以及 `<workspace>/.super-agent/`（工作树和导出，**带连字符**）。

