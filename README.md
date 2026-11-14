# Super Agent

Super Agent 是在本地项目中使用的 Agent，可通过终端或本机浏览器界面驱动。你可以让它解释代码、修改文件、排查问题和运行检查，并在执行过程中审批操作或取消任务。

## 快速开始

按下面四步，从零开始在自己的项目里运行 Super Agent。参与本仓库开发见[参与开发](#参与开发)。

### 环境准备

| 依赖 | 要求 | 安装方式 |
|---|---|---|
| uv | 最新版 | `curl -LsSf https://astral.sh/uv/install.sh \| sh`；macOS 也可用 `brew install uv` |
| Python | 3.12 及以上 | `uv sync` 会按需自动下载，也可使用系统已安装的 Python |
| bubblewrap、util-linux | 仅 Linux 需要，严格沙箱依赖 `bwrap` 和 `prlimit` | 见下方命令 |

```bash
sudo apt install bubblewrap util-linux   # Debian/Ubuntu
sudo dnf install bubblewrap util-linux   # Fedora
```

缺少 `bwrap` 或 `prlimit` 时，应用按[沙箱要求](docs/spec/tools.md#沙箱)拒绝启动。非 Linux 平台目前没有命令隔离：未显式配置沙箱时会自动降级为 `off`，命令以当前用户的完整权限运行，详见[沙箱配置](docs/spec/config.md#沙箱)。

### 安装与启动

在本仓库根目录执行：

```bash
uv sync
uv run super-agent
```

首次启动会生成 `~/.superagent/settings.json`。按下一步配置模型后重新启动。

如需安装为可直接调用的命令，在仓库根目录执行：

```bash
./scripts/build-local.sh
super-agent
```

安装位置及自定义方式见[构建说明](docs/development.md#构建)。

### 配置模型

打开生成的 `~/.superagent/settings.json`，选择 `provider`，并在对应的 `providers` 条目里填写模型及 API 密钥。也可以不把密钥写进文件，改为设置 `<PROVIDER>_API_KEY` 环境变量（例如 `DEEPSEEK_API_KEY`）。配置示例与凭据规则见[模型服务商配置](docs/spec/config.md#模型服务商)。

### 在项目中运行

配置完成后，从目标项目目录运行已安装的 `super-agent`；从源码启动时，可用 `--cwd` 指定项目：

```bash
uv run super-agent --cwd /path/to/project
```

### 参与开发

开发本仓库还需要安装 Web 前端的开发依赖并运行检查，命令见[开发命令](docs/development.md#开发命令)；工作约定从 [AGENTS.md](AGENTS.md) 开始阅读。

## 两个前端

同一套会话有两种用法，界面不同，能力与授权范围相同：

| 用法 | 命令 | 说明 |
|---|---|---|
| 终端 | `super-agent` | Linux/macOS 无标志时的默认入口，交互式命令行 |
| Web | `super-agent --web` | 本机浏览器界面，默认 `http://127.0.0.1:8765/`；用 `--host`、`--port` 改变监听地址与端口 |

Windows 不提供终端界面：无标志启动默认打开 Web 界面，`-web` 可用。平台范围见[产品定义](docs/design/product.md#前端与平台)。

Web 界面提供会话侧栏、移动抽屉、流式对话、工具活动、审批、引导/排队、权限与模型配置，以及 MCP 管理、附件、仓库/诊断查询、记忆条目、会话压缩/分支/导出等与终端相同的操作。它的布局与状态反馈见[界面设计](docs/design/ui.md#web-信息架构)，操作流程见[使用体验设计](docs/design/ux.md#web-任务流程)。

Web 默认只监听回环地址，且没有认证：界面能触发工具执行，不要把端口暴露到网络。

## 开始使用

进入命令行后直接输入任务，例如：

```text
解释这个项目的入口和主要模块。
修复登录校验失败的问题，并运行相关测试。
检查当前变更，指出可能引入的缺陷。
```

执行时可以查看回复、工具活动和审批请求。需要授权时，根据提示选择允许或拒绝。停止当前任务和退出的操作见[审批与退出](docs/spec/terminal.md#审批与退出)。

输入 `/` 查看命令。会话管理、附件、压缩和撤销等操作的完整命令入口见[终端命令参考](docs/spec/terminal.md#命令)，恢复与撤销的作用范围见[会话说明](docs/spec/session.md)。

## 使用参考

- [命令行参数与环境变量](docs/spec/config.md#命令行参数与环境变量)
- [权限模式](docs/spec/config.md#权限)
- [工具与执行隔离](docs/spec/tools.md)
- [MCP 和语言服务器配置](docs/spec/config.md#服务器)

