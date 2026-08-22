package engine

import (
	"super-agent/runtime/machine"
	"super-agent/runtime/protocol"
)

func (e *Engine) State() machine.State {
	e.mu.Lock()
	defer e.mu.Unlock()
	return e.runtimeData.State
}

func (e *Engine) Messages() []protocol.Message {
	e.mu.Lock()
	defer e.mu.Unlock()
	return append([]protocol.Message(nil), e.runtimeData.Messages...)
}

func (e *Engine) PendingTool() (protocol.ToolCall, bool) {
	e.mu.Lock()
	defer e.mu.Unlock()
	if e.runtimeData.PendingTool == nil {
		return protocol.ToolCall{}, false
	}
	return *e.runtimeData.PendingTool, true
}

func (e *Engine) Snapshot() EngineView {
	e.mu.Lock()
	defer e.mu.Unlock()
	snapshot := EngineView{State: e.runtimeData.State, Messages: append([]protocol.Message(nil), e.runtimeData.Messages...), IsBusy: e.runtimeData.State == machine.StateWaitingLLM || e.runtimeData.State == machine.StateRunningTool || e.runtimeData.State == machine.StateAdvancingQueue, NeedsInput: e.runtimeData.State == machine.StateWaitingApproval}
	if e.runtimeData.PendingTool != nil {
		call := *e.runtimeData.PendingTool
		snapshot.PendingTool = &call
		if e.runtimeData.PendingPermission != nil {
			request := *e.runtimeData.PendingPermission
			snapshot.PendingPermission = &request
		}
		if e.runtimeData.ToolBatch != nil {
			snapshot.PendingToolBatchID = e.runtimeData.ToolBatch.ID
			snapshot.PendingToolBatchIndex = e.runtimeData.ToolBatch.Index
			snapshot.PendingToolBatchTotal = len(e.runtimeData.ToolBatch.Calls)
		}
	}
	if e.runtimeData.StreamingContent != "" || e.runtimeData.StreamingReasoning != "" {
		snapshot.StreamingMessage = &protocol.Message{Role: protocol.RoleAssistant, Content: e.runtimeData.StreamingContent, ReasoningContent: e.runtimeData.StreamingReasoning}
	}
	return snapshot
}
