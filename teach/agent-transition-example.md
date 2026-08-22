# 举例说明 Agent 状态转移的整个过程

状态转移 handler 函数在程序最开始初始化

看用户发送一条消息之后会发生什么？

```go
func handleUserMessageSubmitted(_ MachineSnapshot, event UserMessageSubmitted) (TransitionResult, error) {
	return TransitionResult{
		NextState:          StateWaitingLLM,
		RuntimeDataChanges: []RuntimeDataChange{AppendUserMessage{Content: event.Content}},
		ScheduledActions:   []ScheduledAction{CallModel{}},
	}, nil
}
```

该函数定义了，用户发送消息后
- 下一个状态是 `StateWaitingLLM`
- 
