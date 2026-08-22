package machine

type RuntimeData struct {
	State              State
	Messages           []Message
	PendingTool        *ToolCall
	PendingPermission  *PermissionRequest
	CurrentTool        *ToolCall
	ToolBatch          *ToolCallBatch
	StreamingContent   string
	StreamingReasoning string
}
