# 会话与上下文

`runtime/session` 提供应用用例，负责运行时与界面的边界。它不包含终端行为，也不调度动作；它向 engine 提供的内容见 `runtime.md`。

本文件说明 Agent “记住”什么，以及上下文如何组装、持久化和修改。

## 上下文是什么

项目没有向量数据库，也没有人 embeddings 检索。Agent 能回忆的全部内容，就是传给模型、保存在 `runtime/machine.RuntimeData.messages` 中的 `list[Message]`。

唯一跨会话的部分是**记忆行**：用户明确写下的少量条目（`/remember`），由[记忆端口](#跨会话记忆)保管，在开关打开时作为一条 `system` 消息注入到上下文最前面。开关关闭时它们不进入上下文，但已存的行不会被删除，重新打开即可恢复。

`Message`（`runtime/protocol/types.py`）有四种角色：

| 角色 | 内容 |
|---|---|
| `system` | 内建提示词和项目指令 |
| `user` | 用户问题，可附带附件 |
| `assistant` | 模型输出，包括推理内容和工具调用 |
| `tool` | 工具结果，通过 `tool_call_id` 关联调用 |

每次模型调用都传入完整消息列表和当前工具定义：`messages + tool_specs -> Model.next -> ModelResponse`。因此，模型是否“记得”某件事，完全取决于它是否仍在 `messages` 中。

## 初始上下文

启动时按[项目目录参数与解析规则](config.md#命令行参数与环境变量)取得项目和初始工作区。

工作区访问根目录与指令/配置根目录是不同概念。增加可读或可写的工作区根目录只授予文件访问权限，不会导致从该目录加载 `AGENTS.md`、`CLAUDE.md`、钩子、技能、插件或配置。项目指令发现以选中的项目根目录作为配置根目录。

`WorkspaceSpec` 是工作区的持久化描述，包含主根目录、cwd，以及各根目录和访问模式，不包含授权行为。`workspace.Context` 根据该描述重建，负责规范化、符号链接校验、路径包含判断和读写决策。新会话元数据将 `project_id`、`config_root` 和 `workspace_spec` 分别持久化；回放时不从其中一个派生另一个。

`app.new_session` 将以下内容组装为一条 `system` 消息：

```text
app.SystemPrompt
  + 用户级 ~/.superagent/AGENTS.md
  + 从仓库根目录到工作目录的项目指令
```

`app/instructions.load` 应用以下规则：

1. 读取可选的用户级规范 `~/.superagent/AGENTS.md`。
2. 再按从根到叶的顺序读取项目指令，逐层合并。
3. 同一目录下，非空 `AGENTS.md` 优先；只有该目录不存在 `AGENTS.md` 时，才将 `CLAUDE.md` 作为低优先级兼容指引加载。
4. 每个指令文件上限为 128 KiB。文件过大时终止加载，并明确指出路径，不得悄悄截断。

所有来源合并为一条 `system` 消息，不会每轮重新扫描。会话元数据还记录指令来源路径和系统消息指纹，以便日后识别会话最初的环境。

## 上下文如何增长

普通回答追加两条消息：

```text
system + 历史消息
  -> 追加 user 消息
  -> CallModel
  -> 追加 assistant 消息
```

工具调用将其变为循环：

```text
assistant(tool_calls)
  -> 审批并执行工具
  -> tool(result)
  -> 将更新后的 Messages 交回模型
  -> 最终回答，或再次调用工具
```

工具结果作为普通 `tool` 消息进入上下文；拒绝与失败的结算规则见[状态机规范](machine.md#转移表)。审批决定持久化以供审计，但不发给模型。

流式输出期间，内容累积在 `streaming_content` 和 `streaming_reasoning` 中用于实时展示。只有提交后的最终响应才成为历史消息。

## 运行与轮次的记录

概念边界由[核心概念](../design/concepts.md)规定。当前 `store.TurnID` 用于持久化记录的轮次分组，`RunID` 用于 Engine 的运行有效性及过期结果过滤，`ActionID` 标识具体调度动作，三者不能互相替代。

持久化格式不包含 Step 字段或步骤边界记录：Step 只存在于运行数据，随 Turn 结束消失，恢复会话后新的 Turn 从 Step `1` 开始。将来若需要把步骤写入记录，须先在本规范定义字段与兼容语义。Step 的生命周期见[运行时规范](runtime.md#轮次与步骤边界)。

已受理但尚未接纳的中途引导同样只存在于运行数据：它在被接纳成 `user` 消息时进入会话记录并据此持久化，未被接纳则随 Turn 作废，恢复会话后不会重现。接纳规则见[状态机规范](machine.md#输入接纳)。

## 运行时与持久化数据

上下文存在于两个层次：

- `RuntimeData.messages` 是实际调用模型时使用的实时权威数据。
- `~/.superagent/sessions/<session-id>/events.jsonl` 是用于重建历史的持久化事件日志。

Session 对同一份已提交快照分别推进消息持久化和通知输出，两者不共享游标。消息保存先于任何可能等待通知消费者的操作；通知拥塞不阻止后续 Action 及其已提交消息的保存。通知按状态、审批、消息和输入回执的顺序缓存并独立投递，消息不因队列满而丢弃；轮次收尾等待已缓存通知送达，消费端持续停止时只会阻塞通知收尾。取消投递保留未送达项，关闭或重置会话时清理相应投递活动。

保存进度仅在 `Repository.save_message` 成功后前移。保存抛错视为结果不确定：下一次快照重试前通过 `Repository.load` 对账，以磁盘历史与当前快照的完整消息前缀确认保存位置；已经存在的追加不得重复写入，相邻相同内容的消息仍按位置分别保存。对账读取失败或历史不匹配时不盲目追加，错误继续向调用者报告。该保证针对现有 Repository 契约下的单会话追加与重试，不新增磁盘幂等键或承诺跨进程写入事务。

新建、恢复、分支、压缩、撤销和上下文替换以已保存历史重新建立持久化基线，不能将旧通知位置当作新历史的保存位置。保存失败与通知失败独立尝试并分别向调用者报告；两者同时失败时聚合错误，保留各自原因。

```text
~/.superagent/sessions/<session-id>/
  meta.json      # ID、标题、时间戳、服务商、模型、cwd、当前轮次 ID、
                 # 父会话 ID、指令指纹、指令来源
  events.jsonl   # 消息、工具结果、审批、取消、重置、压缩、
                 # 检查点、上下文替换
```

事件日志包含的内容多于模型上下文。回放时，`store.messages_from_records` 只将五类记录转换为 `messages`：追加消息、工具结果、重置、压缩和上下文替换。审批、错误和取消仅用于审计，不进入上下文。

创建会话时先写入对话记录，最后写入 `meta.json`，避免中断后留下看似完整的孤立会话。

## 跨会话记忆

记忆是用户主动写下、跨会话保留的少量条目。它不是检索结果，也不由模型自动写入：只有 `/remember` 会增加一行，`/forget` 清空全部。

记忆是一个独立的端口，不属于会话仓储。会话仓储负责一条对话的持久化记录；记忆放在哪里是应用的决定，运行时只知道端口。

| 名称 | 位置 | 说明 |
|---|---|---|
| `Memory` | `runtime/session/memory.py` | 端口：`name`、`enabled`、`load()`、`save(items)` |
| `Switch` | `runtime/session/memory.py` | 开关：包在任何后端前面，关闭时读不到、也写不进 |
| `OffMemory` | `runtime/session/memory.py` | 没有后端时的实现：读为空，写入报错 |
| `StoreMemory` | `store/memory.py` | 后端：会话存储自己的 `_memory.json` |
| `FileMemory` | `store/memory.py` | 后端：用户指定路径的 JSON 数组 |
| `openMemory` | `app/memory.py` | 按设置挑选后端，未知后端是启动失败 |
| `MemoryController` | `application/memory.py`（构造兼容入口见模块职责） | 开关的运行时一面：改状态、写入设置、重建上下文 |

设置在 `~/.superagent/settings.json` 的 `memory` 块：

| 字段 | 含义 |
|---|---|
| `enabled` | 开关。关闭时记忆不参与上下文，写入被拒绝，已存的行保留 |
| `backend` | 后端名：`store` 或 `file` |
| `path` | `file` 后端使用的路径，其他后端忽略 |

后端选择是应用的自由：换后端只换端口实现，会话、委派子会话与两个前端都不需要改动。

上下文中的记忆是一条 `system` 消息，前缀为 `Cross-session memory:`，每行一个条目。它放在最前面，并且**替换**而不是累加——否则每次 `/remember` 都会多出一条记忆消息。

开关有两种改法，作用相同：

- 启动时读 `settings.json` 的 `memory.enabled`；
- 运行时 `/memory on` 与 `/memory off`（终端）以及 `POST /api/memory`（Web）。运行时改开关会写回 `settings.json`——一个重启后就忘记自己的开关是陷阱——并立刻重建会话上下文：打开时补上记忆消息，关闭时移除。

委派的子会话继承同一个记忆端口，因此子 Agent 看到的是同一批记忆行与同一个开关状态。

记忆文件是 JSON 数组，权限 `0600`，原子写入：内容是用户写给自己的话，不该被同机其他用户读到。

## 切换会话：`/resume`

`Session.resume` 通过 `Repository.load` 加载事件日志和保存的工作区。在改变活跃会话之前，它会针对当前文件系统校验所有保存的工作区根目录和 cwd，并重建全新上下文。主根目录缺失、被移动或被替换为符号链接、附加根目录缺失，以及 cwd 不在恢复后的根目录内，都会直接失败并报告 `saved workspace is no longer valid`；恢复时绝不回退到进程 cwd 或当前 `--cwd`。只有完整校验成功后才激活整个工作区，使内建文件、命令和 LSP 工具共享恢复的上下文。

在 `WorkspaceSpec` 引入前写入的会话，仅保存元数据中的 `cwd`，从未保证其为规范路径。首次恢复时，session 仅升级一次该元数据：基于当前文件系统解析保存的 `cwd`，校验结果，并在任何状态修改前持久化规范描述。此后每次恢复都采用上述严格路径，宽松升级不会成为永久后备。没有保存 cwd 的旧会话不能恢复。升级只使用旧会话的数据，不使用当前进程状态，且不修改 `project_id`、`config_root` 或其他元数据。

已经携带 `WorkspaceSpec` 的会话不再升级。其保存的规范无法通过校验时，恢复直接失败，不回退到 `cwd`。规范化升级无法持久化时，恢复也必须失败，不能报告实际上未完成的迁移。

工作区校验后，`Session.resume` 重建 `messages` 并调用 `Engine.replace_messages`，该方法会：

- 取消当前运行，使迟到结果被丢弃。
- 清除待审批调用、当前工具、工具批次和流式缓冲。
- 将状态恢复为 `Idle`。
- 让后续轮次从恢复的历史继续。

`/resume` 恢复的是持久化的**消息**，不会继续执行到一半的工具调用。

恢复时 `config_root` 保持独立。恢复工作区访问权限不会扫描任何工作区根目录中的指令、钩子、技能、插件或项目配置。本阶段保留保存的配置根目录身份，但切换会话时不热加载扩展配置。

`~/.superagent/sessions`、日志、缓存，以及将来集中管理的工作树区域等应用存储不属于工作区根目录，不需要工作区授权。目前委派工作树路径建在用户工作区内，因此仍应检查写权限；若将其迁移到应用存储，需要独立的存储适配器，而不是增加工作区根目录。

## 压缩：`/compact [summary]`

`Session.compact` 将模型上下文缩减为“摘要加最近消息”：

1. 未提供摘要时，对完整历史额外调用一次模型生成摘要。
2. 保留所有 `system` 消息。
3. 将较早的非 `system` 消息替换为一条 `system` 消息：`Conversation summary:\n...`。
4. 默认保留最近 4 条非 `system` 消息。
5. 先持久化压缩记录，再替换 engine 消息，避免内存与磁盘状态不一致。

记录同时保存 `original_messages` 和 `kept_messages`；后续恢复使用 `kept_messages`。压缩是有损的，摘要未覆盖的细节不再发送给模型。

## 重置

`Session.reset` 在调用 `Engine.reset` 前写入 `reset` 事件。内存消息变更采用[状态机的 ResetConversation 语义](machine.md#runtimedatachange)，回放 `reset` 记录时采用同一语义。

## 撤销：`/undo`

`/undo` 不是“删除最后一条消息”。在可跟踪的写入（`write_file`、`apply_patch`）之前，session 通过 `Workspace` 捕获文件快照并保存检查点。

撤销流程如下：

1. 查找最近的**非空**检查点，跳过空检查点。
2. 先恢复文件系统。
3. 将 `events.jsonl` 原子截断到该检查点。
4. 使用检查点之前的消息替换 engine 上下文。

必须先恢复文件，再截断对话记录；如果恢复失败，历史仍然保留。最终工作区与模型上下文回到操作前的共同状态。

## 取消与迟到结果

会话保留取消前已产生的消息；执行收尾和迟到结果过滤遵循[运行生命周期](runtime.md#运行生命周期与过期结果)。

## 附件

`/attach <path>` 将工作区附件加入下一轮队列，`/attachments` 列出队列。附件大小上限为 10 MiB。图片作为原生多模态块发送；受支持的文档作为文件块或文档块发送。轮次开始时消费附件队列。

## 委派

`delegate` 工具创建持久化子会话，运行选中的 Agent 配置，并将子会话的最终回答作为父会话工具调用的结果返回。取消通过父上下文传播。设置 `worktree` 会在 `.super-agent/worktrees/` 下创建处于游离 HEAD 状态的 Git 工作树；返回的路径会保留用于检查——成功、失败与取消都不删除工作树，因为删除等于把证据一起抹掉，清理是用户的决定而不是委派的副作用。

子 Agent 使用以子 cwd 为根的独立默认工作区上下文。委派工作树创建在父工作区内，创建时通过父工作区绑定检查写权限。

`/fork [title]` 将当前对话记录分支为新的子会话，并切换到该会话。

## 限制

以下行为容易被误解，需要明确：

- 每次模型调用都发送全部 `messages`。项目不分词，也不会在达到上限前自动压缩。
- `/compact` 由用户触发，摘要质量取决于模型或用户提供的文本。
- 持久化以会话为单位，新会话不会检索其他会话的对话记录。唯一跨会话的是记忆行，且只在开关打开时注入。
- 指令在创建会话时加载。恢复旧会话使用当时持久化的 `system` 消息，不会悄悄采用磁盘上的新指令。
- 检查点仅覆盖路径可解析的已知写入工具，不是通用文件系统快照。

## 代码索引

| 主题 | 位置 |
|---|---|
| 消息与模型接口 | `runtime/protocol/types.py` |
| 初始系统消息 | `app/system_prompt.py`、`app/session.py` |
| 分层指令加载 | `app/instructions/__init__.py` |
| 消息变更与重置 | `runtime/machine/runtime_data_change_applier.py` |
| 对话与工具转移 | `runtime/machine/transition.py` |
| 模型与工具执行 | `runtime/execution/scheduled_action_executor.py` |
| 轮次与消息发送 | `runtime/session/turn.py`、`runtime/session/snapshot_emitter.py` |
| 恢复、压缩、撤销 | `runtime/session/history.py` |
| 跨会话记忆 | `runtime/session/memory.py`、`store/memory.py`、`app/memory.py` |
| 持久化适配器 | `store/repository.py`、`store/store.py` |
| 文件检查点 | `runtime/session/checkpoint.py`、`workspace/workspace.py` |

## 磁盘格式稳定性

会话、配置、记忆和遥测都是持久化产物，格式属于契约，不是实现细节。规则是**字段级稳定**：键名、枚举字符串、时间戳格式、文件权限模式和回放语义不得改变，一个版本写入的 JSON 必须能被其他版本解析。

时间戳采用纳秒精度的 RFC 3339。会话和轮次标识符由 `time.time_ns()` 手动格式化生成，因为 `strftime("%f")` 只支持微秒精度。

