# Super Agent

Super Agent 是在本地项目中使用的交互式命令行 Agent。你可以让它解释代码、修改文件、排查问题和运行检查，并在执行过程中审批操作或取消任务。

## 安装与启动

需要 Python 3.12 及 uv。在本仓库根目录执行：

```bash
uv sync
uv run super-agent
```

首次启动会生成 `~/.superagent/settings.json`。按下一节配置模型后重新启动。

如需安装为可直接调用的命令，在仓库根目录执行：

```bash
./scripts/build-local.sh
super-agent
```

安装位置及自定义方式见[构建说明](docs/development.md#构建)。Linux 命令执行所需的隔离组件见[沙箱要求](docs/spec/tools.md#沙箱)。

## 三个前端

同一套会话有三种用法，界面不同，能力与授权范围相同：

| 用法 | 命令 | 说明 |
|---|---|---|
| 终端 | `super-agent` | 默认入口，交互式命令行 |
| Web | `super-agent --web` | 本机浏览器界面，默认 `http://127.0.0.1:8765/`；用 `--host`、`--port` 改变监听地址与端口 |
| ACP | `super-agent --acp` | 编辑器通过 Agent Client Protocol 驱动，JSON-RPC 走标准输入输出 |

Web 界面提供会话侧栏、移动抽屉、流式对话、工具活动、审批、引导/排队、权限与模型配置。它的布局与状态反馈见[界面设计](docs/design/ui.md#web-信息架构)，操作流程见[使用体验设计](docs/design/ux.md#web-任务流程)。

Web 默认只监听回环地址，且没有认证：界面能触发工具执行，不要把端口暴露到网络。

编辑器接入（以 Zed 的 `settings.json` 为例）：

```json
{
  "agent_servers": {
    "Super Agent": {
      "command": "super-agent",
      "args": ["--acp", "--cwd", "/path/to/project"]
    }
  }
}
```

## 配置模型

打开生成的 `~/.superagent/settings.json`，选择 `provider`，并在对应的 `providers` 条目填写模型及 API 密钥。配置示例与凭据环境变量见[模型服务商配置](docs/spec/config.md#模型服务商)。

配置完成后，从目标项目目录运行已安装的 `super-agent`；从源码启动时，可使用下面的示例指定项目：

```bash
uv run super-agent --cwd /path/to/project
```

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

参与本仓库开发时，请从 [AGENTS.md](AGENTS.md) 阅读工作约定。
