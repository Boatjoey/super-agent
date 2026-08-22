package machine

type StateChange interface {
	isStateChange()
}

type AppendUserMessage struct {
	Content string
}

func (AppendUserMessage) isStateChange() {}

type AppendAssistantMessage struct {
	Message Message
}

func (AppendAssistantMessage) isStateChange() {}

type AppendToolResult struct {
	Call   ToolCall
	Result string
}

func (AppendToolResult) isStateChange() {}

type AppendStreamingAssistant struct {
	Chunk StreamChunk
}

func (AppendStreamingAssistant) isStateChange() {}

type FlushStreamingAssistant struct {
	Interrupted bool
}

func (FlushStreamingAssistant) isStateChange() {}

type SetPendingTool struct {
	Call    ToolCall
	Request PermissionRequest
}

func (SetPendingTool) isStateChange() {}

type SetToolCallBatch struct {
	ID    string
	Calls []ToolCall
}

func (SetToolCallBatch) isStateChange() {}

type AdvanceToolCallBatch struct{}

func (AdvanceToolCallBatch) isStateChange() {}

type ClearPendingTool struct{}

func (ClearPendingTool) isStateChange() {}

type SetCurrentTool struct {
	Call ToolCall
}

func (SetCurrentTool) isStateChange() {}

type ClearCurrentTool struct{}

func (ClearCurrentTool) isStateChange() {}

type ClearScheduledActions struct{}

func (ClearScheduledActions) isStateChange() {}

type ClearToolCallBatch struct{}

func (ClearToolCallBatch) isStateChange() {}

type ResetContext struct{}

func (ResetContext) isStateChange() {}

// AllStateChanges lists every StateChange type for registration, serialization, and testing.
var AllStateChanges = []StateChange{
	AppendUserMessage{},
	AppendAssistantMessage{},
	AppendToolResult{},
	AppendStreamingAssistant{},
	FlushStreamingAssistant{},
	SetPendingTool{},
	SetToolCallBatch{},
	AdvanceToolCallBatch{},
	ClearPendingTool{},
	SetCurrentTool{},
	ClearCurrentTool{},
	ClearScheduledActions{},
	ClearToolCallBatch{},
	ResetContext{},
}
