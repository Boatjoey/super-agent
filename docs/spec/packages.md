# 模块与文件职责

本规范将[软件架构](../design/software-architecture.md)规定的业务职责与交互边界映射到具体包和文件。调整文件分工不得改变上层的业务规则、边界和依赖方向。

## 项目技术标识

项目使用 Python 3.12，发行包名为 `super-agent-py`，导入根包为 `super_agent`，命令行程序为 `super-agent`。进程入口为 `super_agent/__main__.py`。

## 代码依赖与接口约束

依赖向内指向 `runtime/machine`。这不只是文档约定：`tests/architecture/test_dependencies.py` 解析各包的导入，一旦违规就使构建失败。

端口与适配器的方向定义见[软件架构](../design/software-architecture.md#端口与适配器)；本节只维护代码落点与导入约束。

- `runtime/machine` 是领域核心，负责状态、事件、运行数据变更、动作计划、调度动作和转移，见 [状态机规范](machine.md)。
- `runtime/protocol` 负责模型与工具适配器契约（`Message`、`ToolCall`、`Model`、`ToolRunner`），不包含状态机策略。
- `runtime/permission` 负责权限请求与命令分类的值类型。
- `runtime/engine` 驱动状态机，负责唯一的 Agent 循环、同步、调度动作的队列排空，以及运行身份，见 [运行时规范](runtime.md)。
- `runtime/execution` 调用出站的模型和工具端口，并承载审批等待。
- `runtime/session` 提供应用用例，不得包含终端行为，也不得导入 `os` 或 `pathlib`；文件系统访问必须经过端口。
- `frontend` 是前端契约：驱动端端口（含 MCP、附件、工作区查询、扩展、记忆）、展示 DTO、通知集合、通道与取消值，以及契约的 JSON 投影。两个前端使用同一份契约；它不导入运行时、不导入任何适配器，只依赖自身。
- `tui` 负责 `TerminalApplication` 及其不依赖框架的交互模型。Rich 仅限于此适配器；视图保持纯函数；它只通过 `Conversation` 端口和展示 DTO 依赖应用，并按终端既有名称重新导出契约中的展示值。
- `web` 是另一个前端适配器，只依赖 `frontend`，把端口承载为本机 HTTP 与服务器推送事件；不得导入运行时、`tui` 或组合根。
- `app` 是组合根，负责创建依赖，并在唯一一处把运行时值转换为前端契约的值。
- `llm`、`tools`、`store`、`project` 和 `workspace` 是顶层适配器。`llm` 和 `tools` 可以导入 `runtime/protocol`，不得导入根 `runtime` 门面；`store` 和 `workspace` 还可以导入声明其端口的 `runtime/session`。

适配器在边界将第三方 SDK 值转换为 `runtime/protocol` 类型，SDK 对象不得进入状态机。

导入 `llm` 或构造内建模型时，不得导入模型服务商 SDK。选中的服务商适配器及 SDK 在首次模型请求时加载，避免无关服务商拖慢终端启动。

`tui` 不得导入 `runtime`，运行时也不得导入 `tui`。在 app 边界的 `app/conversation_adapter.py` 中，运行时状态被转换为仅用于展示的 `frontend.AgentStatus`；两个前端都不拥有运行时状态枚举。`app/tui_adapter.py` 只保留历史名称的重新导出，不含实现。

根 `runtime` 包是兼容门面，按 `api_model.py`、`api_machine.py`、`api_execution.py`、`api_engine.py` 和 `api_session.py` 组织。它公开会话持久化端口和元数据，不导入具体适配器。内部包必须依赖拥有该类型的窄接口包，而不是这个门面。

`ToolBatchReceived`、`ToolCallNeedsApproval` 和 `ActionResultResolver` 分别是工具批次接收、审批请求和结果映射的规范名称；运行时不得为它们重新导出其他名称。

`TerminalApplication` 与 `web.Server` 是[系统范围](../design/software-architecture.md#系统范围)规定的两个用户交互入口。它们共享同一应用接口，暴露同一组操作，只有承载方式不同；因此新增前端只需新增一个承载层，不需要复制业务规则。

## 端口与适配器映射

本节把[软件架构](../design/software-architecture.md#端口与适配器)定义的端口映射到包与文件。内侧是应用侧：实现入站端口、调用出站端口；外侧是边界外的适配器：调用入站端口、实现出站端口。

| 方向 | 端口 | 契约位置 | 内侧 | 外侧 |
|---|---|---|---|---|
| 入站 | 快照、配置、轮次、会话、权限、Agent、记忆、服务商、MCP、附件、工作区查询、扩展 | `frontend/ports.py` | `app/conversation_adapter.py` | `tui`、`web` |
| 出站 | 模型 | `runtime/protocol/types.py` | `runtime/execution` | `llm` |
| 出站 | 工具 | `runtime/protocol/types.py` | `runtime/execution` | `tools` |
| 出站 | 会话持久化 | `runtime/session/repository.py` | `runtime/session` | `store` |
| 出站 | 工作区 | `runtime/session/repository.py` | `runtime/session` | `workspace` |
| 出站 | 跨会话记忆 | `runtime/session/memory.py` | `runtime/session` | `store/memory.py` |
| 出站 | 附件读取与导出（可选） | `runtime/session/attachments.py`、`export.py` | `runtime/session` | `workspace` |

终端不再单独声明 `MemoryPort`；两个前端使用前端契约里的同一个端口。

人工审批不在此表：请求由应用发起，回答经 `TurnPort.approve` 入站，因此横跨两侧。`ApprovalWaiter`、`Closer`、`WorkspaceContext` 与适配器内部的 `Tool`、`command_sandbox`、`KeyReader` 等接口不满足边界判据，不算端口。

## 文件分工

`runtime/machine` 是纯领域核心，不执行 I/O、不加锁，也不调用模型或工具。文件职责如下：

- `state.py`：运行时状态类型及其常量。
- `event.py`：事件接口、事件种类和 `ALL_EVENTS`。
- `runtime_data.py`：完整的可变状态机数据。
- `runtime_data_change.py`：运行数据变更类型及 `ALL_RUNTIME_DATA_CHANGES`。
- `runtime_data_change_applier.py`：事务式克隆、应用和校验。
- `action_plan.py`：转移后的动作队列计划。
- `scheduled_action.py`：提交后执行的调度动作类型及 `ALL_SCHEDULED_ACTIONS`。
- `step.py`：轮次内的步骤标识值类型。
- `steering.py`：已受理但未纳入请求的中途引导值类型。
- `tool_batch.py`：排队的工具批次状态。
- `snapshot.py`：快照构造与状态不变量。
- `transition.py`：静态转移注册表及处理函数。

`runtime/engine` 按职责拆分：

- `engine.py`：依赖和构造。
- `commands.py`：生命周期、审批、策略和上下文命令。
- `action_loop.py`：转移分发与调度动作的队列排空。
- `query.py`：状态查询与不可变快照。

Engine 文件显式指明 `machine`、`execution` 和 `protocol` 中的类型归属；包内不设别名门面。

`runtime/execution` 负责出站调用与结果解析：

- `scheduled_action_runner.py`：执行调度动作，返回 `ActionCompletion`。
- `scheduled_action_executor.py`：调用模型或工具执行器。
- `scheduled_action_result.py`：结果类型。
- `action_queue.py`：提交后的调度动作队列。
- `action_result_resolver.py`：将结果映射为可供转移处理的事件，并对工具调用分类。
- `policy.py`：权限决策。`command_analyzer.py`：shell 检查与分类。
- `approval_store.py`：始终允许与自动审批状态。`run_controller.py`：运行 ID、取消函数和过期结果检查。

`runtime/session` 按意图划分用例：

- `session.py`：构造、配置、重置和快照。
- `turn.py`：单轮对话与审批流程。
- `history.py`：已保存会话、压缩和撤销。
- `memory.py`：跨会话记忆的端口、开关，以及把记忆放进上下文的规则。
- `persistence.py`：持久化通知。
- `notifications.py`：会话到 UI 的通知协议。
- `repository.py`：持久化和工作区端口，包括检查点创建、`load_undo_point`、`truncate_after`，以及一次性的 `save_workspace_description` 升级。

交互式命令行的行为由[终端规范](terminal.md)规定。契约内容由[应用接口规范](application-interface.md)统一定义，声明位置与文件分工如下：

- `frontend/view.py`：展示值（消息、工具调用、状态、权限请求、用量、视图、受理回执、配置视图）与角色、状态常量。
- `frontend/notifications.py`：封闭的通知集合与 `NOTIFICATION_KINDS`。
- `frontend/ports.py`：快照、配置、轮次、会话、权限、Agent、记忆、服务商、MCP、附件、工作区查询与扩展端口，能力清单 `CAPABILITIES`，以及会话与 Agent 摘要。
- `frontend/workflows.py`：终端与 Web 共用的工作流提示词（Review、Fix CI、Commit message）。
- `frontend/transport.py`：`Channel` 与 `Cancellation`；`frontend/approval.py`：审批决定值。
- `frontend/failure.py`：可展示的失败值 `Failure` 与 `CANCELLED`/`FAILED` 分类，含从异常转换的入口。
- `frontend/wire.py`：契约的 JSON 投影，供 Web 事件使用。
- `app/conversation_adapter.py`：唯一实现，负责运行时到展示值的映射与一轮的通道桥接。
- `web/hub.py` 事件分发、`web/turns.py` 单轮槽位、`web/routes.py` 路由表、`web/server.py` HTTP 与事件流、`web/assets.py` 随包静态文件。
- `web/static/index.html` 页面语义结构与可访问性容器、`web/static/style.css` 设计令牌、组件和响应式布局、`web/static/favicon.svg` 站点图标、`web/static/app.ts` 快照重建、事件消费、视图渲染与用户操作的 TypeScript 源码；`web/static/app.js` 是其随包发布的浏览器构建产物。静态前端不拥有业务规则，也不引入运行时或模型依赖。

`project` 解析选中的项目，与文件系统访问策略相互独立。`workspace.Context` 是工作区根目录和 cwd 的、独立于进程的唯一权威来源；`workspace.Workspace` 将其适配到会话检查点、附件、导出和工作区恢复端口，包括对旧版保存路径的一次性规范化升级。`store/store.py` 写入和回放持久化会话记录；其保证的持久化顺序见 `session.md`。`store/memory.py` 提供跨会话记忆的两个文件后端（会话存储自己的文件、用户指定路径的文件），实现 `runtime/session/memory.py` 声明的端口。`app/mcp.py` 协调 MCP 生命周期、动态工具注册、回滚和配置的原子持久化。`app/memory.py` 按设置挑选记忆后端，并把开关的变化写回设置。


## 工作区类型映射

| 类型 | 回答的问题 | 权威出处 |
|---|---|---|---|
| Project 项目 | `project.Project` | “这是哪个代码项目？” | [命令行参数](config.md#命令行参数与环境变量)、[初始上下文](session.md#初始上下文) |
| Workspace 工作区 | `workspace.Context` | “Agent 可以读写哪些根目录，相对路径在哪里解析？” | `session.md`、`tools.md` |

二者刻意保持独立。增加一个可读或可写的工作区根目录只授予文件访问权限；它**不会**让该根目录下的 `AGENTS.md`、`CLAUDE.md`、钩子、技能、插件或配置被加载。指令与配置发现使用选中的项目/配置根目录，而不是访问根目录 —— 见 `session.md`。

### 四个类型

| 类型 | 文件 | 角色 |
|---|---|---|
| `project.Project` | `project/project.py` | 身份：解析出的根目录及其稳定 ID。由 `project.resolve` 产生。 |
| `workspace.Context` | `workspace/context.py` | 访问策略对象，也是**进程无关的运行时唯一真相来源**。持有一个主根目录、一个 cwd，以及若干带 `read` / `read_write` 标记的根目录。 |
| `workspace.Workspace` | `workspace/workspace.py` | 一个由互斥锁保护的、**可切换**的 `Context` 绑定，同时是会话文件系统适配器（检查点、附件、导出）。通过 `spec`/`validate`/`canonicalize`/`activate` 实现 `runtime/session.Workspace` 端口。 |
| `session.WorkspaceSpec` | `runtime/session/repository.py` | 可持久化的 JSON 描述：主根目录、cwd、带访问模式的根目录。它**不携带授权语义** —— 校验与访问决策属于具体的 `workspace` 实现。 |


路径访问算法见[工具规范](tools.md#内建工具)，保存格式及恢复行为见[会话规范](session.md)。
