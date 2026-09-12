package machine

type RuntimeDataChange interface {
	isRuntimeDataChange()
}

type AppendUserMessage struct {
	Content     string
	Attachments []Attachment
}

func (AppendUserMessage) isRuntimeDataChange() {}

type AppendAssistantMessage struct {
	Message Message
}

func (AppendAssistantMessage) isRuntimeDataChange() {}

type AppendToolResult struct {
	Call   ToolCall
	Result string
}

func (AppendToolResult) isRuntimeDataChange() {}

type AppendStreamingAssistant struct {
	Chunk StreamChunk
}

func (AppendStreamingAssistant) isRuntimeDataChange() {}

type FlushStreamingAssistant struct {
	Interrupted bool
}

func (FlushStreamingAssistant) isRuntimeDataChange() {}

type SetPendingTool struct {
	Call    ToolCall
	Request PermissionRequest
}

func (SetPendingTool) isRuntimeDataChange() {}

type SetToolCallBatch struct {
	ID    string
	Calls []ToolCall
}

func (SetToolCallBatch) isRuntimeDataChange() {}

type AdvanceToolCallBatch struct{}

func (AdvanceToolCallBatch) isRuntimeDataChange() {}

type ClearPendingTool struct{}

func (ClearPendingTool) isRuntimeDataChange() {}

type SetCurrentTool struct {
	Call ToolCall
}

func (SetCurrentTool) isRuntimeDataChange() {}

type ClearCurrentTool struct{}

func (ClearCurrentTool) isRuntimeDataChange() {}

type ClearToolCallBatch struct{}

func (ClearToolCallBatch) isRuntimeDataChange() {}

type ResetConversation struct{}

func (ResetConversation) isRuntimeDataChange() {}

// AllRuntimeDataChanges lists every RuntimeDataChange type for registration, serialization, and testing.
var AllRuntimeDataChanges = []RuntimeDataChange{
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
	ClearToolCallBatch{},
	ResetConversation{},
}
