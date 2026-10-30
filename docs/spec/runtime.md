# 运行时

`runtime/engine` 驱动状态机，负责唯一的 Agent 循环、状态锁、运行生命周期、调度动作的队列排空和过期结果丢弃。`runtime/execution` 调用循环所需的出站模型和工具端口，并承载审批等待。

状态定义与转移图见 `machine.md`；本文件说明如何应用转移，以及如何持续驱动循环。

## 轮次与步骤边界

Turn、Step 和输入归属的定义以[核心概念](../design/concepts.md)为准。本节规定执行边界，不新增另一套 Agent 循环。

1. Engine 开始一次逻辑模型调用前打开一个 Step，并使用此前已接纳的输入构造请求。
2. 请求失败后重试时保持当前 Step；一次实际请求尝试的结束不等于 Step 结束。
3. 模型响应没有工具调用时，提交助手消息后结束该 Step。
4. 模型响应包含工具调用时，等待整个批次的审批、执行或拒绝结果写回后，才结束该 Step。单个调用被拒绝不会单独结束 Turn。
5. 批次处理后的下一次逻辑模型调用打开下一个 Step。下一 Step 输入必须在该请求构造前接纳；已经发出的请求不被原地改写。
6. 正常收尾前检查是否还有当前 Turn 待接纳的输入；有则继续后续 Step，没有则结束 Turn。下一 Turn 的排队输入不参与这个继续判断。
7. 取消或失败时结算当前处理，并沿状态机的取消或错误路径收尾；不得留下没有结果的已分发工具调用。具体补齐规则见[状态机规范](machine.md#转移表)。

步骤边界和守卫属于 Machine，Engine 负责统一调度并执行决策；Session 只连接输入、通知，以及持久化端口。

### 步骤数据与不变式

Step 由运行数据显式记录，不靠动作次数或消息条数推断：接受新的用户输入时打开 Step `1`，工具批次结算后继续下一次模型调用时序号加一，Turn 结束时移除。`Idle` 与 `Initializing` 没有当前 Step，其余状态必须存在当前 Step；字段、变更与转移见[状态机规范](machine.md#runtimedata)。

请求重试不改变步骤数据：重试发生在模型适配器内部，不经过转移。

Step 只存在于运行数据，不写入会话记录，因此恢复会话后新的 Turn 仍从 Step `1` 开始；持久化边界见[会话规范](session.md#运行与轮次的记录)。步骤序号同时是应用报告中途引导归属的依据，接口契约见[应用接口规范](application-interface.md#目标输入契约)。

### 输入接纳

- 中途引导属于当前 Turn，进入待接纳队列；它不改变当前 Step，也不打断正在执行的工具。接纳发生在其后第一个 Step 的模型请求构造之前，未被接纳的输入不参与该请求。
- 排队输入属于下一个 Turn：它在当前 Turn 结束之后、以自身的正文与标识开始一个新 Turn 时接纳，因此不参与第 6 条的继续判断（第 6 条只看中途引导）。

中途引导的端口是 `Engine.submit_steering`（会话层对应 `Session.submit_steering`）。它只提交一次转移，不排空动作队列：动作队列属于正在另一个任务里运行的那一轮，排空会重复执行该轮的动作，或者在队列已空时把运行状态判成不变量违规。因此它复用状态机守卫而不是复用 `dispatch_event` 的分发流程。

受理与接纳是两个时点，由 Machine 决定：输入到达时只进入待接纳队列，Step 开始时才作为 `user` 消息写入会话；Turn 结束时仍未接纳的输入随 Turn 作废。状态、队列与转移规则见[状态机规范](machine.md#输入接纳)。

接纳是外部可观察的事件，不是提交返回的隐含结论：提交方给出输入标识，运行数据保留它，接纳时的通知带上该标识与它被接纳到哪里的序号——中途引导带 Step 序号，排队的输入带 Turn 序号——作废时的通知只带标识。因此调用方可以区分“已受理等待”“已接纳”“已撤销”，不依赖推断。标识是调用方的不透明值，Machine 只搬运不解释；没有标识的输入照常接纳，但不产生通知。

排队输入的端口是 `Engine.submit_queued`（会话层对应 `Session.submit_queued`），与中途引导同样只提交一次转移、不排空动作队列，理由相同。二者的差别在归属守卫的两端：中途引导在没有 Turn 运行时被拒绝，排队输入也被拒绝——没有正在进行的 Turn 时，提交方应当直接开始一轮，而不是把输入挂在一轮谁也不打算开始的对话上。

排队的输入跨过 Turn 边界存活，因此接纳点是新 Turn 的开始，而不是 Step 边界：`Session.run_turn` 接收 `input_id`，由 `UserMessageSubmitted` 在同一提交里执行 `TakeQueued` 移除该输入，并回报所属轮次（`QueuedInputAccepted`）。启动下一 Turn 是应用的职责：会话不调度动作，也不会自己开一轮，接口契约见[应用接口规范](application-interface.md#目标输入契约)。

取消（`CancelRequested`）丢弃排队的输入——用户正在停止这项工作，排在其后的输入属于用户刚刚停下的内容；失败（`ErrorOccurred`）保留它们，因为错误没有改变用户要什么。两者都由 Machine 决定，不由前端清理。

### 工作追踪

Step 边界已实现并关闭；输入归属的实现、自动用例以及真实终端按键与竞态验收均已完成，推进节点见 [flow](../flow.md#开发节点邻接表)。实现应按本节和[终端输入规范](terminal.md#运行期间的输入)对齐，不能将现有行为视为架构定义。

## 运行时循环

```text
QueuedAction { run_id, action_id, action }
  -> ScheduledActionRunner.run -> ActionCompletion
  -> RunID 过期检查
  -> ActionResultResolver.resolve -> 转移事件 Event
  -> snapshot_from(runtime_data) -> 已校验的 MachineSnapshot
  -> transition(snapshot, event)
  -> TransitionResult { next_state, runtime_data_changes, action_plan }
  -> 在克隆的 RuntimeData 上执行 RuntimeDataChangeApplier.apply_runtime_data_changes -> validate_runtime_data
  -> 原子提交 RuntimeData + ActionPlan
  -> 执行 ScheduledAction
```

这是一个循环：动作产生结果，结果被解析为事件，事件驱动转移，转移再调度下一个动作。

其中四个阶段决定了关键语义：

- `snapshot_from` 校验完整运行数据，只公开转移需要的守卫信息。
- `transition` 决定下一状态、运行数据变更和动作计划，是纯函数。
- `RuntimeDataChangeApplier` 克隆运行数据、应用变更并校验结果。校验失败的候选数据永不提交，因此不会出现已提交的非法中间状态。
- engine 在同一把锁内提交运行数据**和**动作计划，然后才执行计划。`ActionPlan.clear_existing` 在安排替代动作的同一个原子步骤内撤回过期队列任务，不会出现队列仍属于已失效状态的时间窗口。

不经状态机事件的管理写入同样遵守候选校验与提交约束。替换会话历史时，先使旧 Run 失效，再在锁内克隆运行数据、修改候选并校验；校验失败时保留已提交的运行数据与动作队列，旧 Run 仍保持失效。校验成功后，在同一临界区替换运行数据并清空动作队列，期间不让出执行权。历史替换的用例语义见[会话规范](session.md#切换会话resume)。

调度动作只在提交后执行，不会有动作基于尚未提交的运行数据开始执行。

## 唯一的循环

`runtime/engine/action_loop.py` 包含唯一的 Agent 循环 `_run_scheduled_actions`。它持续弹出动作，直到队列为空；仅当队列为空**且**状态为 `Idle` 时，运行才结束：

```python
run_id = self._runs.current_run_id()
while True:
    async with self.lock:
        action = self._action_queue.pop()
        if action is None:
            if self._runtime_data.state == STATE_IDLE:
                self._runs.finish_run(run_id)
                return
            state: State = self._runtime_data.state
            raise InvariantViolationError(f"action queue is empty in state {state}")
    # 执行动作、解析结果、计算转移、提交，然后重复
```

活跃状态下队列为空是不变量违规，不能直接停止：每个非 `Idle` 状态都必须存在待处理或执行中的任务。实际循环还负责加锁、结束和取消运行、`RunID` 过滤、错误转移及状态通知。

`_execute_scheduled_action` 封装每次迭代：执行动作、将结果解析为事件、计算转移、原子提交，并让新动作进入队列。

## 调度动作

共有四种动作，由 `machine.ALL_SCHEDULED_ACTIONS` 枚举，并在 `machine.md` 中定义：`CallModel`、`RunTool`、`CheckToolPermission` 和 `AwaitApproval`。

模型调用、工具执行和人工审批都经过同一条“动作 → 结果 → 事件”路径。因此审批不需要第二个循环：`AwaitApproval` 等待 Session 注入的审批决定，但调度权仍属于 engine。

## 动作结果

`ActionResultResolver` 将模型与工具结果直接映射为转移表接受的事件。它将模型请求映射为工具批次事件，将 `PermissionChecked(call, decision, request)` 机械映射为 `ToolCallNeedsApproval`、`ToolCallReadyToRun` 或 `ToolCallDenied`。

Machine 选择批次中的具体调用并调度 `CheckToolPermission(call)`。Executor 使用执行输入中的权限策略与审批记录完成检查，返回携带原调用、决定和请求说明的 `PermissionChecked`；始终允许记录仍优先于策略分类。Resolver 不读取批次或索引，不调用权限策略。策略热更新由执行侧 Runner 接收并用于后续动作。批次耗尽时 Machine 直接形成下一模型动作，见[状态机调度动作](machine.md#调度动作)。

Executor 将普通工具异常作为 `ToolFinished.error` 返回，Resolver 原样搬运为 `ToolResultReceived.error`；结果结算与续调规则见[执行流程决策](machine.md#执行流程决策)。取消继续沿取消通道传播。Resolver 只映射事实，包括工具能力是否启用，不对模型回复作执行流程判断。

批次是上下文单位，单个调用是审批和执行单位。无论用户还是策略拒绝调用，拒绝信息都会作为该调用的工具结果追加，随后继续处理队列，让模型可以选择其他动作而不丢失整轮对话。两条拒绝路径及其结果文本见 `machine.md`。

权限参数及默认值见[配置规范](config.md#权限)，命令执行的隔离保证见[工具沙箱](tools.md#沙箱)。

## Session 的职责

`runtime/session` 开始轮次并提供端口，从不调度动作。`runtime/session/turn.py` 向 engine 提供四项内容：

- `ApprovalWaiter`：读取审批通道，并持久化每个决定。
- `onStreamChunk` 回调：将流式输出转发为通知。
- 按轮次注册的状态观察者：将 engine 快照转换为 `SessionNotification`。
- 按轮次注册的用量观察者：以 `UsageReported` 通知报告当前运行中每次已完成模型调用的用量。适配器无法测量的响应不报告用量。

状态观察者让交互式命令行跟踪快照时点**之间**经过的状态，例如工具执行期间的 `RunningTool`。它在 engine 锁之外运行，以便安全读取快照。

用量观察者携带服务商返回的 token 计数，界面无需自行对对话分词即可显示上下文用量。两个观察者都只为一轮安装，并在结束时清除。

由此保持依赖方向：Session 启动用例，Engine 拥有循环，Execution 执行任务，Machine 决定转移。

## 运行生命周期与过期结果

`Engine.run_turn` 开始一次运行，是唯一接受 `UserMessageSubmitted` 的入口。其他外部状态机事件都经过 `Engine.dispatch_event`，该方法直接拒绝用户消息，避免意外开始轮次。

每次运行都有 `RunID`。`RunController` 拥有该 ID、取消函数和存活检查。动作完成时，若其 `RunID` 已不是当前运行，engine 就丢弃结果。模型或工具调用尚未结束时发生取消、重置或替换，就可能产生过期结果；丢弃它们可以防止已取消轮次写入下一轮。

循环有五种处理情况：

| 情况 | 结果 |
|---|---|
| 状态为 `Idle` 且队列为空 | 正常完成，结束运行 |
| 动作返回错误 | 提交 `ErrorOccurred`，随后返回错误 |
| 上下文被取消，或审批输入中断 | 提交 `CancelRequested`，随后返回 |
| `RunID` 已过期 | 丢弃迟到结果，继续循环 |
| 非 `Idle` 状态下队列为空 | 抛出 `InvariantViolationError` |

## 遥测

运行时通过遥测出站契约以同步方式记录转移、动作和运行的 JSON Lines 记录。记录携带运行与动作的关联 ID、工具组件名、耗时、错误及估算的模型 token 数。具体文件后端与路由的映射见[模块职责](packages.md#端口与适配器映射)，输出位置配置见[配置规范](config.md)。token 数只是估算值，项目不执行分词；限制见 `session.md`。

## 术语

- `Engine`：统一外部事件分发、唯一 Agent 循环、动作队列、状态锁、运行生命周期、调度动作的队列排空，以及过期结果丢弃。
- `ActionQueue`：存放提交后的调度动作。
- `ActionResultResolver`：将调度动作结果转换为可供转移处理的事件，不选择工具或应用权限策略。
- `ScheduledActionRunner`：执行调度动作并返回 `ActionCompletion`。
- `RunController`：负责运行 ID、取消函数和过期结果检查。
- `ApprovalStore`：保存始终允许和自动审批状态。
- `Policy`：权限模式、允许与拒绝规则、命令分类及审批决策。
- `Session`：通道边界，提供审批输入、流式输出、通知与持久化，不调度动作。

状态机侧术语 `State`、`Event`、`RuntimeData`、`RuntimeDataChange`、`ActionPlan`、`ScheduledAction`、`MachineSnapshot` 和 `transition` 在 `machine.md` 中定义。

## 阅读顺序

要完整追踪一轮对话，按以下顺序阅读：

```text
runtime/session/turn.py
  -> runtime/engine/action_loop.py
  -> runtime/execution/scheduled_action_runner.py
  -> runtime/execution/scheduled_action_executor.py
  -> runtime/execution/action_result_resolver.py
  -> runtime/machine/transition.py
```

`transition` 决定后续动作，engine 的唯一动作循环驱动执行，Session 只负责连接用户输入与通知。
