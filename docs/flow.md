# 开发推进 Flow

本文件用邻接表描述通往产品目标的开发节点、当前状态和依赖关系。需要完成的工作及完成条件见 [gap](gap.md)，功能含义由设计与 Spec 定义。

这是项目开发工作的推进图，与 Agent 执行任务时的 Turn、Step 或运行时状态机不同，也不恢复按日期堆积的计划目录。

## 邻接表的含义

- 每一行是一个开发节点，ID 稳定；“后继节点”是该节点完成后可以参与解锁的直接下游。
- 边 `A → B` 表示 B 的完成依赖 A 的交付；B 有多个前驱时，必须全部验收完成才能进入正式实施。独立的调查和准备可以提前进行，但不算完成下游交付。
- 没有前驱的节点可以独立推进，当前入口是 D00、D01、D02、D30、D31。D00 的最终目标确认不阻止已明确的 Turn/Step 工作先推进。
- `—` 表示没有后继节点。依赖图不得出现环、未知节点或悬空引用；并行行进到汇合节点时采用“全部满足”的条件。
- 节点状态与验收证据在本文件维护。状态改变不等于自动满足后继节点条件。

## 开发节点邻接表

| ID | 开发节点 | 关联 Gap | 当前状态 | 后继节点 | 交付物引用 | 证据或阻塞 |
|---|---|---|---|---|---|---|
| D00 | 最终产品目标与验收场景收敛 | G00 | 待确认 | D90 | [产品定义](design/product.md) | 待确认目标场景 |
| D01 | 既有功能基线与验证环境 | G05 | 阻塞 | D90 | [验证方法](development.md#验收) | 见 E01 |
| D02 | 文档入口与差距推进机制整理 | G06 | 待验收 | D90 | [文档职责](../AGENTS.md#文档职责与决策权)、[完整开发工作流](development.md#完整开发工作流)、Gap 与本表 | 见 E02、E03、E04、E05、E06；文档审阅待完成 |
| D13 | 验证输入交互与轮次边界 | G02 | 阻塞 | D33 | 输入交互验证结果 | 等待 D14 完成：排队输入需与 steering 一并验证 |
| D14 | 实现下一 Turn 的排队输入 | G02、G08 | 待验收 | D13 | 输入接纳实现及行为测试、[应用接口](spec/application-interface.md#已有通知契约) | 见 E13、E15；终端与 Web 已提供入口，真实按键与竞态验证未执行 |
| D30 | UI 与 UX 设计基线 | G07 | 待验收 | D32 | [UI](design/ui.md)、[UX](design/ux.md) | 具体设计待验收 |
| D31 | 前端应用接口契约 | G08 | 待验收 | D32 | [应用接口](spec/application-interface.md) | 契约待验收 |
| D32 | 对齐前端与应用接口实现 | G07、G08 | 待验收 | D34 | 前端及应用适配器实现 | 见 E10、E14、E16；前驱 D30、D31 仍待验收 |
| D34 | 接入终端、Web 与 ACP 三个前端适配器 | G07、G08 | 待验收 | D33 | [前端契约](../super_agent/frontend/__init__.py)、[Web 适配器](../super_agent/web/__init__.py)、[ACP 适配器](../super_agent/acp/__init__.py)、[应用接口规范](spec/application-interface.md#三个前端与承载方式) | 见 E11、E12、E15；三个前端可由冒烟脚本自动驱动，Web 已能表达排队，浏览器界面与编辑器客户端的人工验收未执行 |
| D33 | 前端与 Agent 端到端验收 | G02、G07、G08 | 待验收 | D90 | [验收方法](development.md#验收)、[冒烟脚本](../scripts/smoke.py) | 见 E12、E13、E15；三个前端已可由冒烟脚本自动驱动，排队输入已贯通到运行时并在 Web 上可由脚本验证；浏览器与编辑器的人工验收、真实终端按键与竞态验证仍未执行 |
| D90 | 阶段产品验收 | G00、G05 | 待开始 | — | 确认场景的阶段验收记录 | — |

完成条件统一引用关联 Gap，具体行为由交付物所属 Spec 定义。当前没有已完成节点；D13 因 D14 未验收而阻塞。

## 节点状态转移邻接表

| 当前状态 | 允许进入的状态 | 条件 |
|---|---|---|
| 待确认 | 待开始、阻塞 | 需求或取舍明确后进入待开始；存在无法推进的依赖时记录阻塞 |
| 待开始 | 进行中、阻塞 | 正式实施前确认前驱已完成及本节点范围明确 |
| 进行中 | 待验收、阻塞 | 交付物可检查时进入待验收；不能直接跳到已完成 |
| 待验收 | 已完成、进行中、阻塞 | 验收通过并记录证据才能完成；失败返回进行中；无法验收记录阻塞 |
| 已完成 | 待开始 | 目标变化或发现回归时显式重开，并记录原验收失效原因 |
| 阻塞 | 待确认、待开始、进行中、待验收 | 写明阻塞解除的证据，返回适当状态；不得直接标记完成 |

“待确认”说明行为或验收还不明确；“阻塞”说明已知工作因为具体条件不能推进。缺少证据不能被当作成功，未开始不等于阻塞。

## 状态与证据更新

开始节点时记录范围和开始依据；暂停推进时记录阻塞条件；转入待验收时提供可检查的实现或文档；完成时附验证结果及对应 gap 的关闭核对。


发现新的独立工作时增加节点并关联 gap。节点拆分后保留其关系，验收与优先级发生变化时同步调整邻接表；不维护另一个没有状态的执行计划副本。

已完成的上游节点重开时，必须检查其下游验收依据是否失效；受影响的下游应重开或转为阻塞，并记录原因，不能继续以失效的前置证据宣称完成。

## 验证证据

| 证据 | 日期 | 关联节点 | 执行结果及限制 |
|---|---|---|---|
| E01 | 2026-10-27 | D01 | 当前环境未找到 uv；`python3 --version` 为 Python 3.12.3；`python3 -m pytest --version` 报告未安装 pytest。完整测试、覆盖率、平台隔离和终端冒烟尚未执行 |
| E02 | 2026-10-27 | D02 | 既有盘点记录：直接执行状态机规范中的三项断言并扫描 130 个源码文件的依赖规则通过；随后检查 3 份文档本地链接、9 项 Gap 的结构及 14 个 Flow 节点引用与无环性通过。仅为局部结构证据，文档职责调整后的检查需补充 |
| E03 | 2026-10-27 | D02 | 文档职责调整后检查通过：22 份文档、303 个本地链接（含锚点）、职责矩阵覆盖、9 项 Gap 到 14 个节点的关联及依赖图无环性；`git diff --check` 通过。本次仅调整文档，未运行产品回归，文档审阅仍待完成 |
| E04 | 2026-10-27 | D02 | 补充完整开发工作流并合并原进度同步步骤后，22 份文档的 312 个本地链接（含锚点）、职责矩阵覆盖、Gap/Flow 关联与依赖图无环检查通过；`git diff --check` 通过。本次为文档变更，未运行产品回归或 Mermaid 渲染检查 |
| E05 | 2026-10-27 | D02 | 按要求删除 docs 下的 README，将职责约束及导航合并到根 README，更新全部相关链接；21 份文档的 283 个本地链接（含锚点）、职责矩阵覆盖、Gap/Flow 关联及依赖图检查通过，旧路径引用扫描无匹配，`git diff --check` 通过。仅调整文档，未运行产品回归 |
| E06 | 2026-10-27 | D02 | 按用户要求区分使用说明与 Agent 工作规则：根 README 改为用户安装、配置、启动和使用教程，文档职责与决策权迁入 AGENTS.md；21 份文档的 276 个本地链接（含锚点）、职责矩阵覆盖、Gap/Flow 关联及依赖图检查通过，旧治理锚点引用扫描无匹配，`git diff --check` 通过。示例依据现有配置、脚本和规范核对，未执行安装或产品回归 |
| E10 | 2026-10-27 | D32 | 对齐中途引导的前端与应用接口：运行数据保留调用方输入标识（`SteeringInput.id`、`SteeringSubmitted.input_id`），`EngineView` 增加 `step_index` 与待接纳 `steering`，`Engine.submit_steering` 提交后通知观察者；快照发射器按队列中消失的标识与当前状态区分 `SteeringAccepted`（带步骤序号）与 `SteeringWithdrawn`，无标识的输入不报告；`TurnPort.steer` 返回 `SteeringReceipt`（`held`/`rejected`），适配器生成标识、在 `Idle`/`Initializing` 直接拒绝并把异常转成拒绝值；终端运行中 `Enter` 改为提交而非取消，拒绝时保留草稿。验证：`tests/runtime` + `tests/architecture` 303 通过、2 失败、1 跳过（改动前 298；2 项失败为既有 Windows 平台用例）；`tests/app/test_tui_adapter.py` 6 通过（含 3 条新增受理/拒绝/接纳用例）；新增 `tests/tui/test_steering_update.py` 4 通过；`ruff check` 与 `ruff format --check` 对改动文件通过（仓库内 3 条既有 RUF001 位于未改动的 `tests/tui/test_terminal.py`）。环境限制：`app`/`tui` 用例依赖 POSIX，本次在隔离虚拟环境安装 `rich` 等依赖并注入仅测试进程使用的 `termios`/`tty` 与缺失 signal 常量的临时插件后才可运行，仓库未增加平台支持；`tests/llm` 因缺 `httpx2` 无法收集；真实终端按键、审批交互与竞态验收未执行，D30、D31 仍待验收 |
| E11 | 2026-10-27 | D34 | 按六边形架构接入三个前端：新增前端契约包 `frontend`（展示值、封闭通知集合、五个驱动端端口、`Channel`/`Cancellation`、JSON 线格式），`tui` 改为按既有名称重新导出同一契约；运行时到展示值的唯一转换迁至 `app/conversation_adapter.py`，`app/tui_adapter.py` 仅保留历史名称导出；新增 `web` 适配器（事件中枢、单轮槽位、路由表、最小 asyncio HTTP/1.1 与服务器推送事件、随包静态界面，`super-agent --web`，默认 `127.0.0.1:8765`）与 `acp` 适配器（JSON-RPC 2.0 over stdio、`initialize`/`session/new`/`session/load`/`session/prompt`/`session/cancel`/`session/set_mode`、`session/update` 与 `session/request_permission`，`super-agent --acp`）。架构测试新增 R10（`web`/`acp` 只能依赖契约）与 R11（契约只能依赖自身），并有对应的正反用例。验证：新增用例 46 条（`tests/frontend` 9、`tests/web` 18、`tests/acp` 17，另有 2 条以真实适配器分别驱动 Web 与 ACP 各一轮）全部通过，`tests/architecture` 14 条通过；全仓（除 `tests/llm`）473 通过、29 失败、6 跳过、1 错误，失败与错误全部为既有 Windows 平台用例（缺少 API 凭证、POSIX 信号与符号链接语义、`pty` 与 `termios`），改动前基线为同一批失败；`ruff check` 对改动文件通过（仓库内 4 条既有 RUF001 位于未改动的 `scripts/smoke.py` 与 `tests/tui/test_terminal.py`），`ruff format` 通过。限制：真实终端按键、浏览器交互与编辑器客户端的端到端验收未执行；`tests/llm` 因缺 `httpx2` 未收集 |
| E12 | 2026-10-27 | D33 | 修复应用在本机的启动阻断并让三端可自动验收。`tools/commands.py` 原在模块级用 `signal.SIGKILL` 等名字建退出信号标签表，Windows 无该名字，`import super_agent.app` 直接抛 `AttributeError`，整个应用无法启动；现改按名取平台已定义的值，未列出的信号仍经 `signal.Signals` 回退命名，新增 3 条用例。`pyproject` 声明 `httpx`，而 `llm/openai.py` 与模型测试导入的是独立发布的 `httpx2`，已补声明；`tests/llm` 由此可收集，19 条通过。`scripts/smoke.py` 扩为三端验收：新增 `--front-end terminal|web|acp`，`pty` 改为按需导入、测试家目录同时设置 `HOME` 与 `USERPROFILE`，并新增 Web（首页、快照、流式回复以空错误结束、运行中再提交 409、取消后仍应答）与 ACP（`initialize`、`session/new`、`session/prompt` 增量与 `end_turn`、关闭标准输入后以 0 退出）检查。在本机（Windows）执行 `python scripts/smoke.py`：终端段跳过（无伪终端），Web 与 ACP 两段通过；另以 HTTP 与 JSON-RPC 客户端各手工跑通一轮含工具审批的真实会话（模型端点指向本地桩服务，其余组件均为真实实现）。全仓 495 通过、29 失败、6 跳过、1 错误，失败与错误仍为既有 Windows 平台用例（缺凭证、POSIX 信号与符号链接、`pty`/`termios`）。限制：真实终端按键、真实模型服务商、浏览器与编辑器的人工验收未执行 |
| E13 | 2026-10-27 | D14 | 让排队输入经过 Machine 并给出回执。状态机新增 `InputQueued` 事件与 `QueuedInput`，四个运行中状态各一条自环边只登记输入、不改状态；`OpenTurn`/`QueueInput`/`TakeQueued`/`ClearQueued` 与 `RuntimeData.turn`、`RuntimeData.queued` 一并加入，"排队输入不受状态限制"作为不变量。接纳点不是额外事件，而是 `UserMessageSubmitted.input_id` 携带的标识：`OpenTurn` + `TakeQueued` 与追加用户消息在同一次提交内完成，于是下一 Turn 的序号与队列同时推进；取消时 `ClearQueued` 丢弃排队输入，失败时保留。新增 `Engine.submit_queued`、`Session.submit_queued`；快照发射器按标识从队列中消失时的状态报告 `QueuedInputAccepted`（带 Turn 序号）与 `QueuedInputWithdrawn`；契约加入 `QueuedReceipt`（`queued`/`rejected`，原 `STEERING_REJECTED` 收敛为通用 `REJECTED`）、`TurnPort.queue` 与两种通知，通知集合扩到 11 种，`wire` 与新通知对应。应用适配器的 `run_turn` 改为泵：单次调用可连跑数轮，通知通道跨越所提交的全部轮次、只由泵关闭，Web 与 ACP 因此无需知道队列存在；终端 `Tab` 改为经 `TurnPort.queue` 提交，页脚条目由通知驱动增删，`finishSubmit` 不再自行启动下一轮。验证：新增 `tests/runtime/test_queued_input.py` 20 条、`tests/tui/test_queue_update.py` 6 条、`tests/app/test_frontend_ports.py` 2 条排队用例与 `tests/frontend` 1 条回执用例，`tests/runtime/test_transition.py` 补 5 条 `InputQueued` 并改 4 条取消与 1 条提交用例；`tests/runtime` + `tests/architecture` 328 通过、2 失败、1 跳过（改动前 303，2 项失败为同一批 Windows 平台用例）；`tests/frontend` 11 通过、`tests/app/test_frontend_ports.py` 4 通过、`tests/tui` 与 `tests/app/test_tui_adapter.py` 37 通过、5 失败（全部为 `tests/tui/test_terminal.py` 在非 POSIX 事件循环上的既有失败）；全仓 526 通过、32 失败、6 跳过、1 错误，失败与错误均为既有 Windows 平台用例（改动前 495 通过、29 失败）；`ruff check` 与 `ruff format --check` 通过，4 条既有 RUF001 位于未改动的 `scripts/smoke.py` 与 `tests/tui/test_terminal.py`；另按 `scripts/verify.sh` 的并发压测口径以 `python -X dev` 跑 `tests/runtime`：314 通过、2 失败、1 跳过，通道关闭权收归轮次泵后未出现未等待协程或未关闭资源告警。复跑 `scripts/smoke.py`（`PYTHONPATH` 指向工作区，其余为本机真实进程）：Web 段（首页、快照、流式一轮、单轮槽位、取消）与 ACP 段（`initialize`、`session/new`、`session/prompt` 流式、干净退出）通过，终端段因本机无伪终端跳过——轮次泵与通道关闭改动没有破坏两端的一轮执行与退出语义。限制：Web 与 ACP 尚未提供排队入口，真实终端按键、浏览器与编辑器的人工验收以及多轮续接的竞态验证未执行；本机未安装 `pyright`，`scripts/verify.sh` 的严格类型检查一道未跑 |
| E14 | 2026-10-27 | D32 | 补齐审批关联、统一失败结果与配置能力视图，并让委派工作树保留。审批：`request_id` 由应用适配器在通知桥铸造（`approval-` 加 12 位十六进制），因为运行时不给审批编号，而通知桥是唯一同时看到宣告与清除的地方；`ToolApprovalRequested`/`ToolApprovalCleared` 都带出该标识，`ConversationView` 新增 `pending_approval_id` 供重建或重连的界面直接回答；`TurnPort.approve(decision, request_id)` 返回 `ApprovalReceipt`（`accepted`/`rejected` 附原因），只接受当前待决标识，且在交给运行时之前就标记为已消费，因此重复提交必被拒绝；轮次结束清空标识，跨轮次与迟到的决定不会落到下一个工具调用；`run_turn` 去掉审批通道参数，前端不再持有它。失败：新增 `frontend/failure.py` 的 `Failure`（`message`、`code`、`operation`、`request_id`）与 `CANCELLED`/`FAILED` 常量，`ConversationError` 负载由异常对象改为该值，Web 的 `TurnFinished` 与 ACP 的 JSON-RPC 错误改用同一值，前端不再需要解析异常类型判断请求是否被受理。配置：新增 `ConfigPort.config_view()` 与 `ConfigView`（会话与工作区身份、Agent、服务商、模型、权限模式、自动审批、推理强度、可用 Agent、`capabilities`），全部从当前会话与控制器读回，`capabilities` 在当前实现上为 14 项、`agents` 与 `mcp` 仅对应控制器存在时出现，`reasoning_effort` 为空表示未提供；Web 快照与权限模式切换均返回它。委派：`Subagents.run` 在任何路径都不再删除工作树，结果给出精确路径供事后检查，清理交由用户，`removeWorktree` 与相关超时一并删除。三个前端随之调整：终端记住并回传 `approvalRequestID`，受理失败时显示原因而不当作已生效；Web 前端从 `snapshot.pending_approval_id` 取值并在 `/api/approvals` 带上 `request_id`；ACP 用 `notification.request_id` 应答并以失败值生成错误消息。同步更新应用接口规范的审批、失败、配置视图与通知负载章节。验证：新增 `tests/tui/test_approval_update.py` 5 条、`tests/app/test_frontend_ports.py` 6 条（标识铸造与快照、错标识拒绝、重复提交只生效一次、无轮次拒绝、失败值、配置视图）、`tests/app/test_subagents.py` 4 条（成功/失败/取消均保留工作树、未创建工作树时不留下目录）、`tests/web/test_routes.py` 3 条（错标识 409、二次应答 409、快照带 `pending_approval_id`），其余为签名与负载按新契约改写；全仓 545 通过、31 失败、6 跳过、2 错误，失败与错误全部为既有 Windows 平台用例（`test_config`、`test_instructions`、`test_lazy_imports`、`tools` 的符号链接与进程树语义、`tui/test_terminal` 的非 POSIX 事件循环），改动前基线为 526 通过、32 失败、6 跳过、1 错误；`ruff check` 与 `ruff format --check` 通过（4 条既有 RUF001 位于未改动的 `scripts/smoke.py` 与 `tests/tui/test_terminal.py`）；21 份文档 318 个本地链接（含锚点）可解析。限制：本机未安装 `pyright`，类型检查未跑；真实终端按键、浏览器与编辑器客户端的端到端验收未执行，端到端验证仍以自动用例与 `scripts/smoke.py` 为限；Web 与 ACP 仍无排队入口；退出阶段 pytest 在本机偶发 `PytestUnraisableExceptionWarning`（临时目录清理），与用例结果无关，本次计数改由 `--junitxml` 汇总取得 |
| E15 | 2026-10-27 | D34 | 给 Web 补上排队入口，并修掉冒烟脚本暴露的空失败值。`TurnRunner.queue` 转调 `TurnPort.queue`，新增 `POST /api/queue` 返回 `QueuedReceipt`；静态界面在轮次运行中把「排队」与「引导」并列为两个按钮，共用同一草稿但归属不同——引导属于本轮，排队属于下一轮；未受理时草稿回填并显示原因，空闲时不显示排队按钮，因为那必然被拒。复跑 `scripts/smoke.py` 时原有断言失败：`TurnFinished` 的成功事件带着 `{"message": "", "code": "", "operation": "", "request_id": ""}`，四个空字段的错误对象会被前端读成「失败了但消息丢了」。`wire.failure_to_json(None)` 改为返回 `null`，失败才是有内容的对象；界面侧本来就有空值判断，无需改动。冒烟脚本新增两项检查：运行中排队得到 `queued`，取消后同一入口得到 `rejected`。验证：`tests/web` 22 通过（新增 1 条排队回执用例，并把审批用例补上「成功不带失败值」的断言）、`tests/frontend` 新增 1 条 `failure_to_json(None) is None` 用例、`node --check` 通过；本机以真实进程复跑冒烟脚本，Web 段（页面、快照、流式一轮、单轮槽位、取消、排队受理、取消后拒绝）与 ACP 段（`initialize`、`session/new`、流式 `session/prompt`、干净退出）通过，终端段因无伪终端跳过；全仓 546 通过、31 失败、6 跳过、2 错误，失败与错误全部为既有 Windows 平台用例（`tests.tools.test_lsp` 本次收集 10 条、上次 11 条，该文件的收集数随环境变化，与本次改动无关）；`ruff check` 与 `ruff format --check` 通过（4 条既有 RUF001 位于未改动的文件）。限制：ACP 没有排队入口，协议不提供「在当前轮次后插入」的等价消息，未为此发明扩展字段；浏览器人工验收未执行；本机未安装 `pyright` |
| E16 | 2026-10-27 | D32 | 首次跑通严格类型检查，并修掉它查出的三处真实缺陷。此前各轮都记着「本机未安装 `pyright`」，于是这道门槛从未真正执行；本次把它装在工作区的隔离 node 目录（不全局安装、不进仓库），按 `pyproject` 的 strict 配置检查 `super_agent` 与 `tests`。首跑 116 条错误，其中四处不是噪音：一是 `to_frontend_message` 调用 `frontend.MessageAttachment`，而契约里没有这个名字（终端确实有自己的 `MessageAttachment`，但那是 `tui.attachments.Item`），带附件的消息一旦流经快照就会抛 `AttributeError`，改为 `frontend.Attachment` 并补用例；二是 `_next_queued` 的返回注解写成 `runtime.QueuedInput`，该名字不在 `runtime` 上（惰性注解让它从未爆炸，但仍是错的），改为直接导入 `runtime.machine.queued.QueuedInput`；三是配置视图通过会话的工作区对象调用 `get_cwd`/`get_primary_root`，这两个方法不在会话端口声明的 `Workspace` 协议里，改为读 `spec()`——那是会话自己持久化的形状，也是端口唯一承诺的形状；四是测试替身与契约已漂移：`tests/tui/fakes.py` 的 `FakeConversation` 缺 `config_view`、`tests/fakes/frontend.py` 缺 `use_agent`，补上后替身与真实适配器面对同一组方法。修完 116 → 80 条，剩下的绝大多数是 `Any` 型 JSON 负载与未注解的运行时 API 带来的 "partially unknown"（`tui/terminal.py` 20、`tests/runtime/test_steering.py` 14、`acp/agent.py` 12、`tools/nofollow_unix.py` 7、`tests/runtime/test_queued_input.py` 7、`acp/connection.py` 6、`tools/proc_unix.py` 5，其余零散），要逐处补注解，属于独立工作，未在本次一并处理。验证：新增 2 条用例（配置视图读回会话自己的工作区、带附件的消息能转成展示值）；全仓 548 通过、31 失败、6 跳过、2 错误，失败与错误仍是既有的 Windows 平台用例；`ruff check` 与 `ruff format --check` 通过（4 条既有 RUF001）。限制：`scripts/verify.sh` 里的 `uv run pyright` 在本机仍跑不了（无 `uv`），本次是手工以同一配置调用；剩余 80 条未修，严格类型检查尚未通过，因此 G05 的自动检查一项仍不能算完成 |
