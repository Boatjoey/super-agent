# 前端与 Agent 的应用接口

本规范定义两个前端与 Agent 应用服务之间的契约。架构边界见[软件架构](../design/software-architecture.md#前端与-agent-应用服务的边界)，体验要求见 [UI](../design/ui.md) 和 [UX](../design/ux.md)。

接口本身是进程内的异步端口；承载它的前端有两个——终端（进程内直连）和本机 Web 界面（HTTP 与服务器推送事件），见[两个前端与承载方式](#两个前端与承载方式)。本文件区分兼容接口与目标扩展；实现缺口及验收状态见 [Gap](../gap.md#已知待完成工作)和 [Flow](../flow.md#开发节点邻接表)。

## 职责与交互方向

- 前端提交用户意图，消费视图、通知和操作结果；不驱动 Agent 的状态机或调度队列。
- 应用服务提供会话和执行用例，调用领域规则，并协调模型、工具、存储和工作环境。
- 应用实现在边界转换运行时类型与展示类型。外部模型和工具 SDK 对象不进入前端。
- 依赖与代码归属由[模块职责规范](packages.md#代码依赖与接口约束)规定。

接口由四类交互组成：命令调用与受理回执、只读快照、单轮通知流，以及审批和取消输入。异步调用返回前可能持续产生通知；通知流不是另一个 Agent 调度循环。

## 两个前端与承载方式

端口、展示值与通知集合由前端契约包[`super_agent/frontend`](../../super_agent/frontend/__init__.py)定义，运行时到展示值的唯一转换在[`application/presentation.py`](../../super_agent/application/presentation.py)。两个前端都只依赖契约，不互相依赖：

| 前端 | 包 | 承载 | 启动方式 | 说明 |
|---|---|---|---|---|
| 终端 | [`super_agent/tui`](../../super_agent/tui/__init__.py) | 进程内直连 | `super-agent`（Linux/macOS 无标志） | 交互式命令行；命令面板、附件、MCP 管理等操作与 Web 相同，只有呈现方式不同；Windows 不提供该前端 |
| Web | [`super_agent/web`](../../super_agent/web/__init__.py) | 本机 HTTP，事件流用服务器推送事件 | `super-agent --web` | 会话侧栏、流式回复、工具卡片、审批、引导、排队、取消，以及命令面板、附件、MCP 管理等与终端相同的操作 |

无标志启动的默认前端随平台而定：Windows 打开本机 Web 界面，Linux/macOS 打开终端。平台范围见[产品定义](../design/product.md#前端与平台)。

承载方式不改变语义：

- Web 每次交互是一条 HTTP 请求，通知转为同名事件；`GET /api/events` 在订阅时先发送一份完整快照，重连后的界面据此重建，不依赖补发增量。接口清单见[Web 接口](#web-接口)。
- Web 默认只监听 `127.0.0.1`：界面能触发工具执行，把它暴露到网络等于把执行权交给网络。当前不提供认证，也不支持多用户。

## Web 接口

| 方法与路径 | 请求 | 结果 |
|---|---|---|
| `GET /api/snapshot` | — | 当前视图、配置视图与是否有轮次在运行；视图含 `pending_approval_id` |
| `GET /api/config` | — | 当前配置视图；与快照中的配置同源 |
| `GET /api/instructions` | — | 载入上下文的指令文件路径 |
| `GET /api/health` | — | 本机服务、单轮运行状态与事件订阅者数量 |
| `GET /api/events` | — | 事件流：先发 `Snapshot`，随后是通知同名事件与 `TurnStarted`/`TurnFinished` |
| `POST /api/turns` | `{"text"}` | 受理开始轮次；已有轮次在跑时返回 409 |
| `POST /api/steering` | `{"text"}` | `SteeringReceipt`：`held` 或 `rejected` |
| `POST /api/queue` | `{"text"}` | `QueuedReceipt`：`queued` 或 `rejected`（无轮次在跑时拒绝） |
| `POST /api/cancel` | — | 请求取消当前轮次 |
| `POST /api/approvals` | `{"decision": "once", "request_id": "approval-…"}`（也接受 `always`、`deny`） | 提交审批；`request_id` 不是当前待决请求时返回 409，未知决定返回 400 |
| `POST /api/permission-mode` | `{"mode"}` | 切换权限模式并返回新的配置视图 |
| `GET /api/providers` | — | 已配置服务商列表，凭据以 `has_key` 标记、绝不回显密钥 |
| `POST /api/providers/{name}` | `{"api_key": "…", "model": "…"}` | 设置服务商凭据与模型，写回 `settings.json` 并返回新配置视图；`api_key` 为空返回 400 |
| `GET /api/memory` | — | 跨会话记忆的状态与内容：`enabled`、`backend`、`items` |
| `POST /api/memory` | `{"enabled": true}` | 切换记忆开关并返回新的状态；`enabled` 不是布尔值时返回 400 |
| `GET /api/sessions` | — | 已保存会话列表 |
| `POST /api/sessions/{id}/resume` | — | 恢复会话，并向所有连接推送新快照 |
| `POST /api/sessions/{id}/rename` | `{"title"}` | 重命名 |
| `DELETE /api/sessions/{id}` | — | 删除 |
| `POST /api/reset`、`POST /api/undo` | — | 重置或撤销，并推送新快照 |
| `POST /api/workflows/{name}` | — | 以共享工作流提示开始一轮；名称 `review`、`fix-ci`、`commit-message` |

### 工具与会话接口

下列接口与终端的命令面板、附件、MCP 管理等操作对应，使用同一组应用端口；Web 的“工具”面板提供这些入口。

| 方法与路径 | 请求 | 结果 |
|---|---|---|
| `GET /api/mcp` | — | `{"servers": [{"name", "tools": [...]}]}` |
| `POST /api/mcp` | `{"name", "command", "args"}` | 添加并启动服务器 |
| `DELETE /api/mcp/{name}` | — | 删除服务器 |
| `POST /api/mcp/{name}/restart` | — | 重启服务器 |
| `GET /api/attachments` | — | `{"items": [{"name", "mime"}]}` |
| `POST /api/attachments` | `{"path"}` | 暂存工作区文件到下一轮 |
| `GET /api/workspace/diff`、`GET /api/workspace/status` | — | 只读仓库查询 |
| `GET /api/workspace/diagnostics?path=…` | — | 语言服务诊断 |
| `GET /api/extensions` | — | `{"commands": [...], "skills": [...], "plugins": [...]}` |
| `POST /api/extensions/expand` | `{"name", "arguments"}` | 展开自定义命令为提示词 |
| `POST /api/memory/items` | `{"text"}` | 增加一行记忆 |
| `DELETE /api/memory/items` | — | 清空全部记忆行 |
| `GET /api/agents`、`POST /api/agents/{name}` | — | 列出、切换 Agent |
| `POST /api/sessions/{id}/compact` | `{"summary"}` | 压缩上下文 |
| `POST /api/sessions/{id}/fork` | `{"title"}` | 分支会话 |
| `POST /api/sessions/{id}/export` | `{"format"}` | 导出会话，返回写入路径 |

## 已有操作与代码映射

| 能力 | 当前端口或操作 | 结果与约束 |
|---|---|---|
| 读取当前视图 | `SnapshotPort.snapshot()` | 返回 `ConversationView`，用于初始或重建展示；`pending_approval_id` 非空表示有一个待决审批 |
| 读取配置视图 | `ConfigPort.config_view()` | 返回 `ConfigView`：会话与工作区身份、当前 Agent 与服务商、模型、权限模式、自动审批、推理强度，以及本应用实际具备的 `capabilities` |
| 执行新轮次 | `TurnPort.run_turn(text, notifications, cancellation)` | 执行到本次调用结束（可能续接多个轮次）；失败以 `Failure` 值返回，成功返回 `None` |
| 提交中途引导 | `TurnPort.steer(text)` | 立即返回 `SteeringReceipt`：`held`（已受理等待）或 `rejected`（未接受，附原因）；接纳与撤销走通知 |
| 提交排队输入 | `TurnPort.queue(text)` | 立即返回 `QueuedReceipt`：`queued` 或 `rejected`；接纳与撤销走通知 |
| 取消当前轮次 | `TurnPort.cancel()` 或本轮 `Cancellation` | 表达取消，不以取消请求发出作为业务已停止的证明；被取消的轮次以 `code` 为 `cancelled` 的 `Failure` 收尾 |
| 提交审批 | `TurnPort.approve(decision, request_id)` | 立即返回 `ApprovalReceipt`：`accepted` 或 `rejected`（附原因）。`request_id` 必须是 `snapshot().pending_approval_id` 或 `ToolApprovalRequested.request_id` 给出的那一个；应用在交接前就把它标记为已消费，因此重复提交第二次必被拒绝 |
| 会话管理 | `SessionPort` | 重置、列表、恢复、重命名、删除、压缩、撤销、分支和导出 |
| 权限与 Agent 配置 | `PermissionPort`、`AgentPort` | 读取、选择当前策略及配置，结果由应用负责生效 |
| 服务商配置 | `ProviderPort` | 列出服务商（凭据以 `has_key` 标记、绝不回显密钥）、设置某服务商的凭据与模型；写回 `settings.json` 并重建当前模型 |
| 附件与工作区查询 | `AttachmentsPort`、`WorkspacePort` | 附件验证、待提交附件及只读仓库、诊断查询 |
| 记忆与扩展管理 | `MemoryPort`、`ExtensionPort`、`MCPPort` | 记忆读写与开关见[跨会话记忆](#跨会话记忆)；扩展与 MCP 按各自契约处理 |

端口集合声明于[前端契约](../../super_agent/frontend/ports.py)及各功能端口；`tui` 只按终端既有名称重新导出契约，不再拥有独立的应用端口。应用实现为 [ConversationAdapter](../../super_agent/application/conversation.py)，`TerminalConversation` 是其历史名称。

该集合按用例拆分，前端功能只使用自己需要的窄端口。不能因存在统一组合入口，就让每个界面模块直接调用整个运行时。

## 交互端口兼容性

交互组合端口的声明与使用见[端口组合](packages.md#前端端口的组合与使用)。组合只收窄调用方依赖，保持本规范定义的已有操作、通知、审批关联及流结束协议，包括 `run_turn` 的执行和收尾、`steer`／`queue`／`cancel` 的受理规则，以及审批 `request_id` 的关联和重复提交保护。

Web 的现有 HTTP 路由、请求与响应 JSON、SSE 事件协议均保持兼容；[会话规范](session.md)的持久化格式和[运行时规范](runtime.md)的核心运行规则不变。两个前端仍可通过应用接口提交消息、接收通知、审批和取消；轮次执行及审批语义由应用侧统一实现。

## 已有视图数据

`ConversationView` 定义前端读取的展示快照：

| 字段 | 含义 |
|---|---|
| `agent_status` | 展示状态，包含 `label`、`busy`、`awaiting_approval`，不暴露运行时状态枚举 |
| `messages` | 已提交的会话消息 |
| `pending_tool`、`pending_permission` | 当前审批所需的工具与权限信息 |
| `pending_tool_batch_index`、`pending_tool_batch_total` | 审批相关的批次位置与总数 |
| `pending_approval_id` | 待决审批的请求标识；为空表示当前没有待决请求。重建界面据此回答，不必等待下一条 `ToolApprovalRequested` |
| `streaming_message` | 尚未提交的累积流式消息 |

`PermissionRequest` 提供 `tool_name`、`command`、`command_class`、`cwd`、`touched_paths`、`env_vars` 和 `reason`。为空的字段不能由前端推测补齐。

`ContextUsage` 仅提供服务商报告的 `input_tokens`、`output_tokens` 和 `total_tokens`。没有上下文窗口容量时，前端不能由这些计数自行计算占用百分比。

## 已有配置视图

`ConfigView` 由应用实现从当前会话、Agent 与权限控制器读回，不是前端自己缓存或推测的状态：

| 字段 | 含义 |
|---|---|
| `session_id`、`session_title` | 当前会话身份与标题 |
| `workspace`、`roots` | 工作目录与允许的根目录 |
| `instruction_sources` | 载入上下文的指令文件路径 |
| `agent`、`provider`、`model` | 当前 Agent 名称、服务商与模型标识，都是展示值，不含 SDK 对象 |
| `permission_mode`、`auto_approve` | 当前权限模式与是否自动批准 |
| `reasoning_effort`、`reasoning_efforts` | 当前推理强度与可选值；`reasoning_effort` 为空表示“未提供”，界面应隐藏该项，不能自拟一个默认值展示 |
| `agents` | 可切换的 Agent 列表 |
| `memory_enabled`、`memory_backend` | 跨会话记忆是否在用，以及记忆放在哪个后端（`store`、`file`）；后端名为空表示本应用没有记忆 |
| `credential_missing`、`sandbox_downgraded` | 启动状态：当前服务商是否仍无凭据、严格沙箱是否已降级为 `off`；为真时界面应提示（引导填写凭据 / 告知命令将以完整权限运行），不能静默 |
| `capabilities` | 本应用实际具备的能力名，取自 `CAPABILITIES`；未列出的能力对应控件不得展示，因为调用必然失败 |

能力名目前为 `turn`、`steer`、`queue`、`approve`、`cancel`、`resume`、`rename`、`delete`、`compact`、`undo`、`fork`、`export`，另有 `agents` 与 `mcp` 仅在对应控制器存在时出现，`memory` 在应用持有记忆端口或记忆控制器时出现。界面据此决定是否渲染按钮，而不是按前端自己的版本假设。

上下文百分比需要应用明确提供容量和口径；当前只有服务商 token 计数，不具备此条件。界面按现有数据展示计数或隐藏该比例，不能照抄参照界面的百分比。

## 已有通知契约

| 通知 | 负载 | 用途 |
|---|---|---|
| `AgentStatusChanged` | 展示状态 | 更新当前活动展示 |
| `StreamChunkReceived` | 累积的流式消息 | 更新同一条尚未提交的回复，不作为新消息追加 |
| `MessageAppended` | 已提交消息 | 更新正式历史，与流式展示结算 |
| `ToolApprovalRequested` | 工具、权限请求、批次位置及 `request_id` | 展示待决操作；`request_id` 是回答时必须回传的标识 |
| `ToolApprovalCleared` | `request_id` | 清除待决审批状态；携带的标识可与请求配对，便于界面丢弃迟到回应 |
| `UsageReported` | 服务商 token 用量 | 更新用量展示 |
| `SteeringAccepted` | 输入标识与所属步骤序号 | 报告中途引导已被某个步骤接纳，此后不再是“等待” |
| `SteeringWithdrawn` | 输入标识 | 报告等待中的输入随 Turn 结束作废，不能再显示为等待接纳 |
| `QueuedInputAccepted` | 输入标识与所属轮次序号 | 报告排队的输入已经成为某一轮，此后不再显示为“排队中” |
| `QueuedInputWithdrawn` | 输入标识 | 报告排队的输入随取消作废，不能继续显示为等待 |
| `ConversationError` | `Failure` | 呈现失败信息（`message`、`code`、`operation`、`request_id`），不自行将其转换为正常完成 |

未知的运行时通知由应用实现转换为可见错误，不得静默丢弃。

当前每次 `run_turn` 调用使用一条通知通道和一个取消句柄，通道在整次调用结束时关闭；审批不再由调用方持有通道，改由 `TurnPort.approve` 按请求标识提交。一次调用可能续接多个轮次（该调用期间排队的输入由应用续接），因此前端不能把通道等同于单个轮次：轮次的边界由通知本身表达——`QueuedInputAccepted.turn` 命名新轮次，`MessageAppended` 的 `user` 消息是这一轮的开头。前端按调用上下文区分通知，不将上一次调用的通知作用到新视图。运行活动的过期结果过滤仍由[运行时规范](runtime.md#运行生命周期与过期结果)负责。

## 已有流结束与失败处理

- 当前通知 `Channel` 关闭后，消费者仍需读完缓冲区；关闭并排空后读取返回 `None`。
- 通知通道关闭只表示不会再收到该流的数据，不等于本轮成功。以 `run_turn` 调用结束及其错误结果进行收尾，避免遗漏通知流关闭后才报告的失败。
- 取消信号、通知监听和审批应答槽由应用实现连接到同一轮次；轮次结束时一并释放，此后到达的任何审批应答都会被告知“没有轮次在运行”。
- 单次工具失败或拒绝按照状态机规则成为工具结果，不能一律由界面升级为整轮失败。
- 轮次失败以 `Failure` 值返回并带 `code`：`failed` 表示执行出错，`cancelled` 表示被取消。前端据 `code` 区分“出错了”与“我按了取消”，不需要解析异常类型，也不需要靠异常对象是否存在来判断请求是否被受理。
- 会话、配置等其他用例仍可能抛出异常（例如存储不可写）；前端必须显示失败，成功后才采用新的快照。这类失败不承担“输入是否被受理”的语义，受理问题一律由回执值回答。

## 目标输入契约

目标接口区分下列意图，其业务含义以[核心概念](../design/concepts.md#输入归属)为准：

| 意图 | 输入必须关联的上下文 | 应用负责确认的结果 | 当前状态 |
|---|---|---|---|
| 开始轮次 | 当前会话、输入标识、正文及已验证附件 | 是否接受开始请求，以及所属轮次 | `TurnPort.run_turn` 可用；内部已按轮次编号并接受排队输入的标识，但调用方仍不传开始轮次的标识，也没有开始轮次的回执 |
| 中途引导 | 当前会话、当前轮次、输入标识及正文 | 是否受理等待，并在实际接纳时报告所属步骤 | `TurnPort.steer` 已实现受理与接纳回执；附件仍随下一轮提交 |
| 排队输入 | 当前会话、输入标识及正文 | 是否进入后续输入队列，并在实际接纳时报告所属新轮次 | `TurnPort.queue` 已实现受理回执与接纳/撤销通知，后续轮次由应用在 `run_turn` 内续接；终端与 Web 均已提供入口（Web 在轮次运行中显示“排队”，与“引导”并列） |

中途引导的接口扩展与 Step 生命周期同步：会话不调度动作，Machine 负责输入归属守卫，接口只搬运标识与结果。排队输入同理，接纳点是下一个轮次的开始：应用在一次 `run_turn` 调用里把排队的输入续接为后续轮次，前端只消费同一条通知通道，不自行排序。

### 接纳反馈

新增输入交互至少需要区分：

| 输入状态 | 含义 | 中途引导的载体 | 排队输入的载体 |
|---|---|---|---|
| 已受理等待 | 应用接受了提交，但尚未进入某次模型请求的上下文 | `SteeringReceipt(status="held")` | `QueuedReceipt(status="queued")` |
| 已接纳 | 输入已经纳入对应轮次和步骤，后续请求将按该上下文继续 | `SteeringAccepted(input_id, step)` 通知 | `QueuedInputAccepted(input_id, turn)` 通知 |
| 已拒绝 | 应用未接受该输入，附带可展示原因 | `SteeringReceipt(status="rejected", reason=...)` | `QueuedReceipt(status="rejected", reason=...)` |
| 已撤销 | 原先等待的输入已失效，不能再显示为等待接纳 | `SteeringWithdrawn(input_id)` 通知 | `QueuedInputWithdrawn(input_id)` 通知 |

每项反馈应关联会话、输入及适用的轮次/步骤标识。同一输入不能重复接纳；前端不能仅因用户已按提交键就显示“已接纳”。中途引导的标识由前端生成并随提交传入，应用在接纳时原样回报；轮次由本轮通知通道隐含，不在负载里重复。排队输入的标识同样由提交方生成，但它的接纳可能落在另一轮的通知通道上，因此 `QueuedInputAccepted` 显式携带 `turn`。服务端或跨进程传输协议不在本次范围内。

输入回执的持久化和恢复重放规则由[会话规范](session.md)定义；接口接纳不隐含持久化投递保证。

## 已有审批与错误关联

审批请求与回应用同一个请求标识关联。标识由应用实现在通知桥里生成（`approval-` 加 12 位十六进制），因为运行时本身不给审批编号，而通知桥是唯一同时看到“宣告”和“清除”的地方：

- 应用只记住一个待决标识。`ToolApprovalRequested` 到来时铸造并记下，`ToolApprovalCleared` 到来时取出并清空，两者都把标识写进通知负载。
- `TurnPort.approve(decision, request_id)` 只接受与当前待决标识相同的请求，并且在把决定交给运行时就把它标记为已消费——因此同一标识的第二次提交必被拒绝，双击不会让同一工具执行两次。
- 拒绝以值返回，原因有三种且不合并：没有轮次在运行、决定没有指明请求、该请求已不再待决。前端可以据此区分“我晚了一步”与“我拿错了标识”。
- 轮次结束时待决标识一并清空，所以跨轮次或迟到的决定不会落到下一个工具调用上。
- `ConversationView.pending_approval_id` 让重建或重连的界面仍能回答，不必等下一条通知；进程重启后没有待决审批，这与审批不持久化的取舍一致。

输入受理失败、会话操作失败与执行中失败统一用 `Failure` 表达：`message` 是可展示文本，`code` 区分 `failed` 与 `cancelled`，`operation` 说明是哪个操作失败的，`request_id` 在失败可归因到某个待决请求时填写。前端不需要解析内部异常类型就能判断该请求是否已经受理——受理问题由各回执（`SteeringReceipt`、`QueuedReceipt`、`ApprovalReceipt`）回答，失败值只回答“执行有没有成功”。

未完成的部分：审批标识是进程内的，不随会话持久化，因此不承担跨进程恢复语义。其余工作见 [Gap](../gap.md#已知待完成工作)。

## 跨会话记忆

记忆是跨会话保留的少量用户条目，由[会话规范](session.md#跨会话记忆)定义。应用接口把它暴露成一组窄操作：

| 操作 | 结果与约束 |
|---|---|
| `MemoryPort.memories()` | 已存的行；记忆关闭时为空 |
| `MemoryPort.remember(text)` | 增加一行；记忆关闭时失败，不静默丢弃 |
| `MemoryPort.forget_memories()` | 清空全部行 |
| `MemoryPort.memory_enabled()` | 开关当前的状态 |
| `MemoryPort.memory_backend()` | 后端名（`store`、`file`），用于告诉用户记忆放在哪里 |
| `MemoryPort.set_memory_enabled(enabled)` | 切换开关：写回 `settings.json`，并立刻重建会话上下文 |

开关关闭时记忆不参与上下文，但已存的行保留；重新打开即可恢复——因此“关闭”不是“删除”，两者在接口上是不同的操作。

记忆由终端与 Web 共同表达，两端使用同一组操作。

## 验收条件

1. 前端可以仅通过应用接口完成读取视图、提交任务、审批、取消和会话操作，不直接操作领域状态或基础设施。两个前端共用同一端口与展示值，任一新前端不得引入第二份运行时转换。
2. 通道关闭及调用结果分别处理，缓冲通知完整消费；终端输出去重按[终端规范](terminal.md#流式输出与历史)验收。
3. 界面重建读取快照，不重新提交任务或重放外部操作。
4. 目标输入交互能验证中途引导与排队归属，回执与实际接纳时机一致。中途引导与排队输入均已有自动用例覆盖受理、接纳、拒绝与撤销；真实终端按键与并发竞态验收已通过。
5. 审批关联能拒绝迟到、重复与跨轮次的应答，失败与取消后监听和等待正确结束。自动用例覆盖标识铸造、快照带出、错标识拒绝、重复提交只生效一次、无轮次时拒绝，以及两个前端的对应路径；真实浏览器与真实终端的端到端验收已通过。
6. 记忆由一个端口保管，开关可见且可切换：关闭时上下文里没有记忆行且写入被拒绝，打开时记忆行回到上下文，关闭再打开后已存的行仍在。自动用例覆盖端口、开关、两个后端、设置写回、终端命令与 Web 路由；真实浏览器里的手动验收已通过。
