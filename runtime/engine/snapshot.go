package engine

import (
	"super-agent/runtime/machine"
	"super-agent/runtime/protocol"
)

type EngineView struct {
	State                 machine.State
	Messages              []protocol.Message
	PendingTool           *protocol.ToolCall
	PendingPermission     *machine.PermissionRequest
	PendingToolBatchID    string
	PendingToolBatchIndex int
	PendingToolBatchTotal int
	StreamingMessage      *protocol.Message
	IsBusy                bool
	NeedsInput            bool
}
