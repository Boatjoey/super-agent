package session

type ApprovalDecision string

const (
	ApproveOnce   ApprovalDecision = "once"
	ApproveAlways ApprovalDecision = "always"
	DenyApproval  ApprovalDecision = "deny"
)

type SessionNotification interface{ isSessionNotification() }

type StateChanged struct{ State State }

func (StateChanged) isSessionNotification() {}

type ToolApprovalRequested struct {
	ToolCall   ToolCall
	Request    PermissionRequest
	BatchID    string
	BatchIndex int
	BatchTotal int
}

func (ToolApprovalRequested) isSessionNotification() {}

type ToolApprovalCleared struct{}

func (ToolApprovalCleared) isSessionNotification() {}

type StreamChunkReceived struct {
	Chunk   StreamChunk
	Message *Message
}

func (StreamChunkReceived) isSessionNotification() {}

type MessageAppended struct{ Message Message }

func (MessageAppended) isSessionNotification() {}

type SessionError struct{ Err error }

func (SessionError) isSessionNotification() {}
