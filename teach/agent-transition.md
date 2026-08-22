# Transition 状态转移机制

## 核心职责

`Transition` 是状态机的纯决策函数：输入当前状态的只读快照和一个事件，返回下一状态及后续操作。

```go
func Transition(
	snapshot MachineSnapshot,
	event Event,
) (TransitionResult, error)
```

可以把状态机看成有向图：`State` 是节点，`Event` 是触发条件，`(State, Event)` 是边的键，`NextState` 是目标节点。

`Transition` 不修改 `RuntimeData`，也不调用模型或工具。

## 输入与输出

`MachineSnapshot` 是从 `RuntimeData` 生成的只读投影，只保留转移判断需要的数据。`SnapshotFrom` 会先验证完整运行时数据。

`Event` 是状态机事件接口。包内方法 `isEvent` 封闭事件集合，`kind` 提供注册键。

返回值包含四部分：

```go
type TransitionResult struct {
	NextState          State
	StateChanges       []StateChange
	ActionQueueChanges []ActionQueueChange
	ScheduledActions   []ScheduledAction
}
```

`NextState` 是下一执行状态；`StateChanges` 构造下一份 `RuntimeData`；`ActionQueueChanges` 在提交时修改队列；`ScheduledActions` 在提交后执行外部工作。

例如：

```go
return TransitionResult{
	NextState:        StateWaitingLLM,
	StateChanges:     []StateChange{AppendUserMessage{Content: event.Content}},
	ScheduledActions: []ScheduledAction{CallModel{}},
}, nil
```

含义是：保存用户消息，进入 `WaitingLLM`，提交成功后调用模型。

## 静态注册器

每条转移规则由状态和事件类型共同定位：

```go
type transitionKey struct {
	state State
	event eventKind
}

type transitionHandler func(MachineSnapshot, Event) (TransitionResult, error)

var stateTransitions = newTransitionRegistry()
```

注册器是包级私有 map，在包初始化时创建，运行期间只读取。`registerTransition` 会检查重复键，防止新规则静默覆盖旧规则。

错误、取消和重置使用零状态键：

```go
{transitionKey{event: eventErrorOccurred}, adaptTransition(handleErrorOccurred)},
{transitionKey{event: eventCancelRequested}, adaptTransition(handleCancelRequested)},
{transitionKey{event: eventResetRequested}, adaptTransition(handleResetRequested)},
```

`State` 的零值 `""` 不是合法运行状态，因此这里表示“任意状态”，不需要为每个状态重复注册。

## 为什么需要 adaptTransition

各 handler 的事件参数不同，例如 `EngineReady` 和 `UserMessageSubmitted`。接收具体事件的函数不等于接收任意 `Event` 的函数，所以不能直接放入 `map[transitionKey]transitionHandler`。

`adaptTransition` 负责统一函数类型：

```go
func adaptTransition[E Event](
	handler func(MachineSnapshot, E) (TransitionResult, error),
) transitionHandler {
	return func(snapshot MachineSnapshot, event Event) (TransitionResult, error) {
		typed, ok := event.(E)
		if !ok {
			return protocolViolation(
				snapshot,
				event,
				"registered handler has incompatible event type",
			)
		}
		return handler(snapshot, typed)
	}
}
```

注册时：

```go
adaptTransition(handleUserMessageSubmitted)
```

编译器由 handler 的函数类型推导出 `E` 是 `UserMessageSubmitted`。执行时，`event.(E)` 再把统一的 `Event` 接口恢复为具体事件。

注册正确时断言应当成功；保留 `ok` 检查可以在注册错误时返回明确错误，而不是 panic。

## Transition 的查找过程

```go
handler, ok := stateTransitions[transitionKey{
	state: snapshot.state,
	event: event.kind(),
}]
if !ok {
	handler, ok = stateTransitions[transitionKey{event: event.kind()}]
	if !ok {
		return unexpectedEvent(snapshot, event)
	}
}
return handler(snapshot, event)
```

代码先查找精确规则，再查找任意状态规则；仍未找到则返回 `UnexpectedEventError`。map 查询中的 `ok` 表示键是否存在。

## handler 的校验

不需要快照时用 `_ MachineSnapshot` 明确忽略参数。需要判断调用关系时则读取快照，例如 `handleToolResultReceived` 会检查：

- 当前是否存在正在运行的工具。
- 返回结果的 call ID 是否与当前工具一致。

相关错误分为：

- `InvariantViolationError`：当前 `RuntimeData` 自身非法。
- `UnexpectedEventError`：当前状态不接受该事件。
- `ProtocolViolationError`：事件类型合法，但内容与当前数据不匹配。

完整状态转移表见 [agent-state.md](./agent-state.md)。

## 转移结果如何生效

```text
Event
  -> SnapshotFrom：验证当前 RuntimeData
  -> Transition：产生决策
  -> StateChangeApplier：克隆、修改、验证下一份 RuntimeData
  -> Engine：提交 RuntimeData 和 ActionQueueChanges
  -> ActionQueue：加入 ScheduledActions
  -> ScheduledActionRunner：执行动作
  -> ActionResultResolver：把结果转换成下一个 Event
```

外部动作只在下一状态验证并提交后执行。

## 新增转移

1. 在 `event.go` 定义事件和 `eventKind`。
2. 在 `transition.go` 编写 handler。
3. 在 `newTransitionRegistry` 注册规则。
4. 返回所需的状态变更、队列变更和计划动作。
5. 在 `tests/runtime/transition_test.go` 测试合法转移、拒绝路径和输出顺序。
