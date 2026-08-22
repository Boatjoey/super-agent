package machine

import "super-agent/runtime/protocol"

type ToolCallBatch struct {
	ID    string              `json:"id"`
	Calls []protocol.ToolCall `json:"calls"`
	Index int                 `json:"index"`
}
