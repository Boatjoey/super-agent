package machine

import "fmt"

type RuntimeDataChangeResult struct {
	RuntimeData RuntimeData
}

type RuntimeDataChangeApplier interface {
	ApplyRuntimeDataChanges(runtimeData RuntimeData, result TransitionResult) (RuntimeDataChangeResult, error)
}

type DefaultRuntimeDataChangeApplier struct{}

func (DefaultRuntimeDataChangeApplier) ApplyRuntimeDataChanges(runtimeData RuntimeData, result TransitionResult) (RuntimeDataChangeResult, error) {
	next := cloneRuntimeData(runtimeData)
	next.State = result.NextState
	changeResult := RuntimeDataChangeResult{RuntimeData: next}
	for _, runtimeDataChange := range result.RuntimeDataChanges {
		if err := applyRuntimeDataChange(&changeResult, runtimeDataChange); err != nil {
			return RuntimeDataChangeResult{}, err
		}
	}
	if err := ValidateRuntimeData(changeResult.RuntimeData); err != nil {
		return RuntimeDataChangeResult{}, err
	}
	return changeResult, nil
}

func applyRuntimeDataChange(changeResult *RuntimeDataChangeResult, runtimeDataChange RuntimeDataChange) error {
	state := &changeResult.RuntimeData
	switch m := runtimeDataChange.(type) {
	case AppendUserMessage:
		state.StreamingContent = ""
		state.StreamingReasoning = ""
		state.Messages = append(state.Messages, Message{Role: RoleUser, Content: m.Content, Attachments: append([]Attachment(nil), m.Attachments...)})
	case AppendAssistantMessage:
		state.StreamingContent = ""
		state.StreamingReasoning = ""
		state.Messages = append(state.Messages, cloneMessage(m.Message))
	case AppendToolResult:
		state.StreamingContent = ""
		state.StreamingReasoning = ""
		state.Messages = append(state.Messages, Message{Role: RoleTool, Content: m.Result, ToolCallID: m.Call.ID, ToolName: m.Call.Name})
	case AppendStreamingAssistant:
		state.StreamingContent += m.Chunk.ContentDelta
		state.StreamingReasoning += m.Chunk.ReasoningContentDelta
	case FlushStreamingAssistant:
		if state.StreamingContent != "" || state.StreamingReasoning != "" {
			state.Messages = append(state.Messages, Message{
				Role:             RoleAssistant,
				Content:          state.StreamingContent,
				ReasoningContent: state.StreamingReasoning,
				Interrupted:      m.Interrupted,
			})
		}
		state.StreamingContent = ""
		state.StreamingReasoning = ""
	case SetPendingTool:
		call := m.Call
		request := clonePermissionRequest(m.Request)
		state.PendingTool = &call
		state.PendingPermission = &request
	case SetCurrentTool:
		call := m.Call
		state.CurrentTool = &call
	case SetToolCallBatch:
		state.ToolBatch = &ToolCallBatch{ID: m.ID, Calls: append([]ToolCall(nil), m.Calls...)}
	case AdvanceToolCallBatch:
		if state.ToolBatch == nil || state.ToolBatch.Index >= len(state.ToolBatch.Calls) {
			return InvariantViolationError{Reason: "cannot advance an empty tool batch"}
		}
		state.ToolBatch.Index++
	case ClearPendingTool:
		state.PendingTool = nil
		state.PendingPermission = nil
	case ClearCurrentTool:
		state.CurrentTool = nil
	case ClearToolCallBatch:
		state.ToolBatch = nil
	case ResetConversation:
		state.Messages = systemMessages(state.Messages)
		state.PendingTool = nil
		state.PendingPermission = nil
		state.CurrentTool = nil
		state.ToolBatch = nil
		state.StreamingContent = ""
		state.StreamingReasoning = ""
	default:
		return InvariantViolationError{Reason: fmt.Sprintf("unknown runtime data change %T", m)}
	}
	return nil
}

func cloneRuntimeData(runtimeData RuntimeData) RuntimeData {
	cloned := runtimeData
	cloned.Messages = make([]Message, len(runtimeData.Messages))
	for i, message := range runtimeData.Messages {
		cloned.Messages[i] = cloneMessage(message)
	}
	cloned.PendingTool = cloneToolCall(runtimeData.PendingTool)
	if runtimeData.PendingPermission != nil {
		request := clonePermissionRequest(*runtimeData.PendingPermission)
		cloned.PendingPermission = &request
	}
	cloned.CurrentTool = cloneToolCall(runtimeData.CurrentTool)
	if runtimeData.ToolBatch != nil {
		cloned.ToolBatch = &ToolCallBatch{
			ID:    runtimeData.ToolBatch.ID,
			Calls: append([]ToolCall(nil), runtimeData.ToolBatch.Calls...),
			Index: runtimeData.ToolBatch.Index,
		}
	}
	return cloned
}

func cloneMessage(message Message) Message {
	cloned := message
	cloned.Attachments = append([]Attachment(nil), message.Attachments...)
	if message.ToolCalls != nil {
		cloned.ToolCalls = make([]*ToolCall, len(message.ToolCalls))
		for i, call := range message.ToolCalls {
			cloned.ToolCalls[i] = cloneToolCall(call)
		}
	}
	return cloned
}

func clonePermissionRequest(request PermissionRequest) PermissionRequest {
	request.TouchedPaths = append([]string(nil), request.TouchedPaths...)
	request.EnvVars = append([]string(nil), request.EnvVars...)
	return request
}

func systemMessages(messages []Message) []Message {
	var kept []Message
	for _, message := range messages {
		if message.Role == RoleSystem {
			kept = append(kept, cloneMessage(message))
		}
	}
	return kept
}
