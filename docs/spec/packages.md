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
- `tui` 负责 `TerminalApplication` 及其不依赖框架的交互模型。Rich 仅限于此适配器；视图保持纯函数；它只通过前端端口和展示 DTO 依赖应用，并按终端既有名称重新导出契约中的展示值。
- `web` 是另一个前端适配器，只依赖 `frontend`，把端口承载为本机 HTTP 与服务器推送事件；不得导入运行时、`tui` 或组合根。
- `application` 承载跨运行用例的应用控制器及前端契约实现；具体落点见[六边形边界的代码约束](#六边形边界的代码约束)。
- `app` 包含组合根、启动配置适配与设施桥接；不能把整个包都视作组合根，逐文件归属见下表。
- `llm`、`tools`、`store`、`project` 和 `workspace` 是顶层适配器。`llm` 和 `tools` 可以导入 `runtime/protocol`，不得导入根 `runtime` 门面；`store` 和 `workspace` 还可以导入声明其端口的 `runtime/session`。

适配器在边界将第三方 SDK 值转换为 `runtime/protocol` 类型，SDK 对象不得进入状态机。

导入 `llm` 或构造内建模型时，不得导入模型服务商 SDK。选中的服务商适配器及 SDK 在首次模型请求时加载，避免无关服务商拖慢终端启动。

`tui` 不得导入 `runtime`，运行时也不得导入 `tui`。在应用边界的 `application/presentation.py` 中，运行时状态被转换为仅用于展示的 `frontend.AgentStatus`；两个前端都不拥有运行时状态枚举。`app/tui_adapter.py` 只保留历史名称的重新导出，不含实现。

根 `runtime` 包是兼容门面，按 `api_model.py`、`api_machine.py`、`api_execution.py`、`api_engine.py` 和 `api_session.py` 组织。它公开会话持久化端口和元数据，不导入具体适配器。内部包必须依赖拥有该类型的窄接口包，而不是这个门面。

`ToolBatchReceived`、`ToolCallNeedsApproval` 和 `ActionResultResolver` 分别是工具批次接收、审批请求和结果映射的规范名称；运行时不得为它们重新导出其他名称。

`TerminalApplication` 与 `web.Server` 是[系统范围](../design/software-architecture.md#系统范围)规定的两个用户交互入口。它们共享同一应用接口，暴露同一组操作，只有承载方式不同；因此新增前端只需新增一个承载层，不需要复制业务规则。

## 端口与适配器映射

本节把[软件架构](../design/software-architecture.md#端口与适配器)定义的端口映射到包与文件。内侧是应用侧：实现入站端口、调用出站端口；外侧是边界外的适配器：调用入站端口、实现出站端口。

| 方向 | 端口 | 契约位置 | 内侧 | 外侧 |
|---|---|---|---|---|
| 入站 | 快照、配置、轮次、会话、权限、Agent、记忆、服务商、MCP、附件、工作区查询、扩展 | `frontend/ports.py` | `application/agent_application.py` | `tui`、`web` |
| 出站 | 模型 | `runtime/protocol/types.py` | `runtime/execution` | `llm` |
| 出站 | 工具 | `runtime/protocol/types.py` | `runtime/execution` | `tools` |
| 出站 | 会话持久化 | `runtime/session/repository.py` | `runtime/session` | `store` |
| 出站 | 工作区 | `runtime/session/repository.py` | `runtime/session` | `workspace` |
| 出站 | 跨会话记忆 | `runtime/session/memory.py` | `runtime/session` | `store/memory.py` |
| 出站 | 附件读取与导出（可选） | `runtime/session/attachments.py`、`export.py` | `runtime/session` | `workspace` |

应用设施的端口映射如下；方法组可共用一个设施对象，不要求每行单独创建服务。

| 方向 | 契约 | 调用侧 | 适配器实现 |
|---|---|---|---|
| 出站 | `application/ports.ModelResolver` | `application/agents.py` | `app/agents.AgentResourcesAdapter` |
| 出站 | `application/ports.InstructionSource` | `application/agents.py` | 同上 |
| 出站 | `application/ports.ProviderPreferences` | `application/agents.py` | 同上 |
| 出站 | `application/ports.MemoryPreferences` | `application/memory.py` | `app/memory.MemoryPreferencesAdapter` |
| 出站 | `application/ports.MCPBackend` | `application/mcp.py` | `app/mcp.MCPBackendAdapter` |
| 出站 | `application/ports.DelegationEnvironment` | `application/delegation.py` | `app/subagents.subagentTool`，同时将 `delegate` 工具调用转交应用用例 |
| 出站 | `application/workflows.Runner`（工具端口的扩展：支持绕过钩子的直接调用） | `application/workflows.py` | 工具注册表与钩子包装 |
| 出站 | `runtime/protocol/telemetry.Recorder` | `runtime/engine` 经遥测路由 | `store/telemetry.py` 的 JSONL 后端 |

`ModelResolver`、`InstructionSource` 和 `ProviderPreferences` 是三个独立契约，由同一个设施对象实现；模型与指令返回内侧值，不返回服务商 SDK 或磁盘文件对象。档案提示词的上下文组装由 `application/agents.withAgentProfile` 拥有；指令适配器返回基础指令消息。MCP 事务编排归 `application/mcp.py`，连接、目录更新与配置文件 I/O 归其后端。`DelegationEnvironment.child` 是可在运行期间调用的组合工厂，返回已构造的内侧会话服务；委派执行规则归应用层。遥测使用进程级路由，组合根安装后端。

业务行为分别见[运行时配置](config.md#运行时配置)、[MCP](tools.md#mcp)、[委派](session.md#委派)与[遥测](runtime.md#遥测)。

终端不再单独声明 `MemoryPort`；两个前端使用前端契约里的同一个端口。

人工审批不在此表：请求由应用发起，回答经 `TurnPort.approve` 入站，因此横跨两侧。`ApprovalWaiter`、`Closer`、`WorkspaceContext` 与适配器内部的 `Tool`、`command_sandbox`、`KeyReader` 等接口不满足边界判据，不算端口。

## 前端端口的组合与使用

`frontend/ports.py` 保留细粒度端口，以 `typing.Protocol` 声明组合接口；公开端口由 `frontend/__init__.py` 重新导出，不另建平行契约。

前端能力按用户意图分为两组，组合接口只继承细粒度端口，不重新声明方法：

| 组合端口 | 用户意图 | 细粒度端口 |
|---|---|---|
| `AgentInteractionPort` | 查看会话、发送消息与附件、干预执行、审批和取消 | `SnapshotPort`、`TurnPort`、`AttachmentsPort` |
| `AgentManagementPort` | 管理会话、Agent 配置与工作环境 | `SessionPort`、`ConfigPort`、`PermissionPort`、`AgentPort`、`ProviderPort`、`MemoryPort`、`MCPPort`、`ExtensionPort`、`WorkspacePort` |

`FrontendPorts` 仅组合 `AgentInteractionPort` 与 `AgentManagementPort`，作为完整前端入口。所有细粒度端口保持公开，功能模块仍可单独依赖实际需要的能力；两组接口不要求独立实现类。TUI 直接重新导出同一个 `FrontendPorts` 类型，不声明同义组合协议。

`web/turns.py` 的 `TurnRunner` 仅依赖 `AgentInteractionPort`，参数及成员命名为 `interaction`、`_interaction`，表达其交互能力范围。完整前端组合入口仍可持有 `FrontendPorts`，参数及成员使用 `frontend_ports`／`_frontend_ports`。`tui/app.py` 的 `App` 分别持有 `snapshot_port` 与 `turn_port`，区别端口对象和读取的快照值；终端构造入口中的完整契约对象命名为 `frontend_ports`，避免与核心 Session 混淆。

`application/agent_application.py` 的 `AgentApplication` 是应用服务，通过结构化类型实现这些端口；Web 与 TUI 是调用端口的入站适配器，该应用服务不属于前端适配器。无须显式继承，也不为组合端口拆分实现。应用职责仍按[六边形边界的代码约束](#六边形边界的代码约束)维护；构造入口命名为 `new_agent_application`。该实现持有的控制器命名为 `agent_controller`、`mcp_controller` 和 `memory_controller`；审批队列与待决标识分别命名为 `_approval_queue`、`_pending_approval_id`，局部名称区分运行时队列和前端通知通道。相关标识符使用 `snake_case`，测试中的完整契约替身使用 `FakeFrontendPorts`，审批等待替身名称明确表示其场景。历史终端入口仍只重新导出同一个实现。兼容要求见[交互端口兼容性](application-interface.md#交互端口兼容性)。

## 六边形边界的代码约束

职责判据与拆分原则由[软件架构](../design/software-architecture.md#职责的严格判据)定义。本节规定实现落点：

| 层次 | 代码落点 | 允许的依赖 |
|---|---|---|
| 领域与运行用例 | `runtime/machine`、`runtime/execution`、`runtime/engine`、`runtime/session` | 内侧运行模块、端口与纯值辅助模块 |
| 应用控制器 | `application` | 本包、`runtime` 的窄接口、`frontend` 契约与纯值辅助模块 |
| 入站契约 | `frontend` | 本包 |
| 出站契约 | `runtime/protocol`、`runtime/session` 的端口声明、`application/ports.py` | 内侧值类型与标准库 |
| 前端适配器 | `tui`、`web` | `frontend` 与各自包内模块；终端还可使用纯值辅助模块 |
| 基础设施适配器 | `llm`、`tools`、`store`、`workspace`、`project`，以及 `app` 中的配置与设施桥接模块 | 所实现的内侧契约与值、必要的其他基础设施 |
| 组合根与兼容入口 | `app/session.py`、`app/__init__.py`、`__main__.py` 及 `app` 的控制器构造入口 | 应用控制器与具体适配器 |

`application` 和整个 `runtime` 不得导入 `app`、`llm`、`tools`、`store`、`workspace`、`project`、`tui` 或 `web`。应用控制器不得直接导入文件系统、网络或进程模块；资源通过构造参数注入。适配器的运行时依赖限制递归覆盖子目录；终端所有目录均不得回调组合根。

`application/agent_application.py` 实现前端入站契约，拥有流生命周期、排队轮次推进及审批关联；`application/presentation.py` 只执行运行值到展示值的转换。`app/agent_application.py` 只保留历史导入名，不承载用例实现。

`application/agents.py`、`memory.py`、`mcp.py`、`workflows.py`、`delegation.py` 分别拥有档案切换、记忆开关、MCP 变更补偿、扩展工作流和委派用例。模型创建、指令读取、设置写入、MCP 连接与工具安装、子会话和工作树构造位于 `app` 的对应设施实现；这些设施通过 `application/ports.py` 契约注入。

`application/values.py` 拥有应用档案、有效扩展集合和 MCP 配置值；`runtime/protocol/provider.py` 拥有服务商配置值。原位置可重新导出同一个类型，不能再声明副本。遥测记录由内侧记录契约接收，JSONL 文件 I/O 位于 `store` 适配器。

`app` 中保留代码的归属如下：

| 文件 | 角色 | 允许保留的职责 |
|---|---|---|
| `session.py`、`__init__.py` | 组合根与公共启动入口 | 创建并注入模型、工具、存储、控制器与关闭函数；转发公共构造函数 |
| `config.py`、`extensions.py`、`instructions/` | 启动配置与文件适配器 | 加载、解析、校验与保存本地配置、指令及扩展，把结果转换成内侧值 |
| `agents.py`、`memory.py`、`mcp.py` | 出站设施及兼容构造入口 | 实现上表出站端口；历史控制器构造函数只注入设施，不复制用例 |
| `subagents.py` | 委派设施与工具接入 | 将工具调用交给委派用例，构造子会话依赖、工作树与工具目录 |
| `workflows.py`、`agent_application.py`、`tui_adapter.py` | 兼容导出 | 重新导出同一个实现，不另设业务流程 |
| `system_prompt.py` | 启动上下文素材 | 内置提示词常量 |

`application/agents.py` 的模型路由与工具筛选、`application/workflows.py` 的钩子包装，是内部业务协作对象，不能仅因实现了 `Model` 或 `ToolRunner` 就认定为外侧适配器；具体模型和工具 I/O 仍由注入的出站实现承担。`runtime/execution/policy.py` 中的 `os.path` 只用于路径字符串计算，不读取文件；它不代表核心可以访问工作环境。

依赖检查同时保留合法依赖的正例和越界导入的反例，覆盖嵌套适配器、应用层与整个运行时，防止检查只扫描到顶层文件。

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

- `scheduled_action_runner.py`：提供当前权限策略与审批记录，支持策略热更新；执行调度动作，返回 `ActionCompletion`。
- `scheduled_action_executor.py`：执行明确动作，调用模型、权限策略、工具执行器或审批等待器。
- `scheduled_action_result.py`：结果类型。
- `action_queue.py`：提交后的调度动作队列。
- `action_result_resolver.py`：将结果映射为可供转移处理的事件，不读取工具队列或调用权限策略。
- `policy.py`：权限决策。`command_analyzer.py`：shell 检查与分类。
- `approval_store.py`：始终允许与自动审批状态。`run_controller.py`：运行 ID、取消函数和过期结果检查。

`runtime/session` 按意图划分用例：

- `session.py`：构造、配置、重置和快照。
- `turn.py`：单轮对话与审批流程。
- `history.py`：已保存会话、压缩和撤销。
- `memory.py`：跨会话记忆的端口、开关，以及把记忆放进上下文的规则。
- `persistence.py`：消息保存进度、异常写入对账及审计写入。
- `snapshot_emitter.py`：通知去重、待投递通知和投递生命周期，不承担持久化。
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
- 前端入站契约的应用实现和展示转换见[六边形边界的代码约束](#六边形边界的代码约束)；`app/agent_application.py` 和 `app/tui_adapter.py` 仅重新导出兼容名称。
- `web/hub.py` 事件分发、`web/turns.py` 单轮槽位、`web/routes.py` 路由表、`web/server.py` HTTP 与事件流、`web/assets.py` 随包静态文件。
- `web/static/index.html` 页面语义结构与可访问性容器、`web/static/style.css` 设计令牌、组件和响应式布局、`web/static/favicon.svg` 站点图标、`web/static/app.ts` 快照重建、事件消费、视图渲染与用户操作的 TypeScript 源码；`web/static/app.js` 是其随包发布的浏览器构建产物。静态前端不拥有业务规则，也不引入运行时或模型依赖。

`project` 解析选中的项目，与文件系统访问策略相互独立。`workspace.Context` 是工作区根目录和 cwd 的、独立于进程的唯一权威来源；`workspace.Workspace` 将其适配到会话检查点、附件、导出和工作区恢复端口，包括对旧版保存路径的一次性规范化升级。`store/store.py` 写入和回放持久化会话记录；其保证的持久化顺序见 `session.md`。`store/memory.py` 提供跨会话记忆的两个文件后端（会话存储自己的文件、用户指定路径的文件），实现 `runtime/session/memory.py` 声明的端口。`app/mcp.py` 连接 MCP 管理器、工具注册表与设置文件；`app/memory.py` 挑选记忆后端并写入记忆设置。事务补偿和开关用例位于应用层，见[六边形边界的代码约束](#六边形边界的代码约束)。


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
