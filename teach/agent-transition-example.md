# 用户消息如何触发状态转移

以用户在 `Idle` 状态发送消息为例。

## 1. 注册转移规则

程序初始化时，注册器建立以下规则：

```go
rules := []transitionRule{
	{
		transitionKey{StateIdle, eventUserMessageSubmitted},
		adaptTransition(handleUserMessageSubmitted),
	},
}
```

含义是：`Idle` 状态收到 `UserMessageSubmitted` 时，调用 `handleUserMessageSubmitted`。

## 2. handler 产生决策

```go
func handleUserMessageSubmitted(_ MachineSnapshot, event UserMessageSubmitted) (TransitionResult, error) {
	return TransitionResult{
		NextState:          StateWaitingLLM,
		RuntimeDataChanges: []RuntimeDataChange{AppendUserMessage{Content: event.Content}},
		ActionPlan:         ActionPlan{Schedule: []ScheduledAction{CallModel{}}},
	}, nil
}
```

该函数没有直接修改 Engine，而是返回三个决定：

- `NextState`：进入 `WaitingLLM`。
- `RuntimeDataChanges`：通过 `AppendUserMessage` 保存用户消息。
- `ActionPlan.Schedule`：状态提交后执行 `CallModel`。

此处 `ActionPlan.ClearExisting` 为 `false`，因为不需要清空已有动作。

## 3. Engine 应用决策

Engine 收到 `UserMessageSubmitted` 后执行：

```text
RuntimeData
  -> SnapshotFrom：验证当前数据并生成 MachineSnapshot
  -> Transition：找到 handleUserMessageSubmitted
  -> RuntimeDataChangeApplier：克隆并修改 RuntimeData
  -> ValidateRuntimeData：验证下一份数据
  -> Engine：提交下一份 RuntimeData
  -> ActionQueue：加入 CallModel
```

提交后的关键数据相当于：

```go
RuntimeData{
	State: StateWaitingLLM,
	Messages: []Message{
		{Role: RoleUser, Content: event.Content},
	},
}
```

实际消息列表还会保留之前的 system 和历史消息。

## 4. 提交后调用模型

`CallModel` 是 `ScheduledAction`，只在新状态验证并提交后执行：

```text
CallModel
  -> ScheduledActionRunner
  -> ScheduledActionExecutor
  -> Model.Next
```

此时 Engine 已处于 `WaitingLLM`，所以 TUI 可以显示模型正在处理。

## 5. 模型结果触发下一次转移

模型执行结果由 `ActionResultResolver` 转换成新的 `Event`：

```text
普通回复：AssistantMessageReceived
工具调用：ToolBatchReceived
```

普通回复的后续流程是：

```text
WaitingLLM + AssistantMessageReceived
  -> AppendAssistantMessage
  -> Idle
```

如果模型请求工具，则进入：

```text
WaitingLLM + ToolBatchReceived
  -> 保存 assistant 消息和工具批次
  -> AdvancingQueue
  -> CheckToolQueue
```

因此，一条用户消息不是只发生一次状态变化，而是启动了一个由事件不断驱动的循环：

```text
Event -> Transition -> 提交数据 -> ScheduledAction -> 新 Event
```
