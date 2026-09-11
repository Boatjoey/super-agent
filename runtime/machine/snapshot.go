package machine

import "fmt"

type queueView struct {
	hasBatch bool
	next     *ToolCall
	// remaining holds the batch calls from the current index onward, i.e. every
	// call that has not been dispatched yet. Error handling needs the full list
	// to answer each tool call the model asked for.
	remaining []ToolCall
}

func (q queueView) empty() bool { return q.hasBatch && q.next == nil }

type MachineSnapshot struct {
	state       State
	pendingTool *ToolCall
	currentTool *ToolCall
	queue       queueView
}

func SnapshotFrom(runtimeData RuntimeData) (MachineSnapshot, error) {
	if err := ValidateRuntimeData(runtimeData); err != nil {
		return MachineSnapshot{}, err
	}
	snapshot := MachineSnapshot{
		state:       runtimeData.State,
		pendingTool: cloneToolCall(runtimeData.PendingTool),
		currentTool: cloneToolCall(runtimeData.CurrentTool),
		queue:       queueView{hasBatch: runtimeData.ToolBatch != nil},
	}
	if batch := runtimeData.ToolBatch; batch != nil && batch.Index < len(batch.Calls) {
		call := batch.Calls[batch.Index]
		snapshot.queue.next = &call
		snapshot.queue.remaining = append([]ToolCall(nil), batch.Calls[batch.Index:]...)
	}
	return snapshot, nil
}

func ValidateRuntimeData(runtimeData RuntimeData) error {
	invalid := func(reason string) error { return InvariantViolationError{Reason: reason} }
	if runtimeData.ToolBatch != nil && (runtimeData.ToolBatch.Index < 0 || runtimeData.ToolBatch.Index > len(runtimeData.ToolBatch.Calls)) {
		return invalid("tool batch index is out of range")
	}
	if runtimeData.PendingTool == nil && runtimeData.PendingPermission != nil {
		return invalid("pending permission has no pending tool")
	}
	if runtimeData.StreamingContent != "" || runtimeData.StreamingReasoning != "" {
		if runtimeData.State != StateWaitingLLM {
			return invalid("streaming content exists outside WaitingLLM")
		}
	}

	switch runtimeData.State {
	case StateInitializing, StateIdle, StateWaitingLLM:
		if runtimeData.PendingTool != nil || runtimeData.PendingPermission != nil || runtimeData.CurrentTool != nil || runtimeData.ToolBatch != nil {
			return invalid(fmt.Sprintf("%s contains tool execution context", runtimeData.State))
		}
	case StateAdvancingQueue:
		if runtimeData.ToolBatch == nil {
			return invalid("AdvancingQueue has no tool batch")
		}
		if runtimeData.PendingTool != nil || runtimeData.PendingPermission != nil || runtimeData.CurrentTool != nil {
			return invalid("AdvancingQueue contains a pending or current tool")
		}
	case StateWaitingApproval:
		if runtimeData.ToolBatch == nil || runtimeData.PendingTool == nil || runtimeData.PendingPermission == nil {
			return invalid("WaitingApproval requires a batch, pending tool, and permission")
		}
		if runtimeData.CurrentTool != nil {
			return invalid("WaitingApproval contains a current tool")
		}
		if !batchPreviousCallMatches(runtimeData.ToolBatch, runtimeData.PendingTool) {
			return invalid("pending tool does not match the advanced batch call")
		}
	case StateRunningTool:
		if runtimeData.ToolBatch == nil || runtimeData.CurrentTool == nil {
			return invalid("RunningTool requires a batch and current tool")
		}
		if runtimeData.PendingTool != nil || runtimeData.PendingPermission != nil {
			return invalid("RunningTool contains pending approval context")
		}
		if !batchPreviousCallMatches(runtimeData.ToolBatch, runtimeData.CurrentTool) {
			return invalid("current tool does not match the advanced batch call")
		}
	default:
		return invalid("unknown state " + string(runtimeData.State))
	}
	return nil
}

func batchPreviousCallMatches(batch *ToolCallBatch, call *ToolCall) bool {
	return batch != nil && call != nil && batch.Index > 0 && batch.Index <= len(batch.Calls) && sameToolCall(batch.Calls[batch.Index-1], *call)
}

func sameToolCall(left, right ToolCall) bool {
	if left.ID != "" || right.ID != "" {
		return left.ID != "" && left.ID == right.ID
	}
	return left.Name == right.Name && left.Input == right.Input
}

func cloneToolCall(call *ToolCall) *ToolCall {
	if call == nil {
		return nil
	}
	cloned := *call
	return &cloned
}
