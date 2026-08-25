package engine

import (
	"context"
	"errors"

	"super-agent/runtime/execution"
	"super-agent/runtime/machine"
	"super-agent/runtime/protocol"
)

func (e *Engine) DispatchEvent(ctx context.Context, event machine.Event, onStreamChunk func(protocol.StreamChunk)) error {
	return e.dispatchEvent(ctx, event, onStreamChunk, nil)
}

func (e *Engine) dispatchEvent(ctx context.Context, event machine.Event, onStreamChunk func(protocol.StreamChunk), beforeActions func()) error {
	e.mu.Lock()
	decision, err := e.calculateTransitionLocked(event) // transition 函数执行
	if err != nil {
		e.mu.Unlock()
		return err
	}
	runCtx := ctx
	startedRun := false
	if _, startsRun := event.(machine.UserMessageSubmitted); startsRun {
		_, runCtx = e.runs.StartRun(ctx)
		startedRun = true
	} else if len(decision.ScheduledActions) > 0 {
		currentCtx, ok := e.runs.CurrentContext()
		if !ok {
			e.mu.Unlock()
			return errors.New("event scheduled actions without an active run")
		}
		runCtx = currentCtx
	}
	if err := e.commitTransitionLocked(decision); err != nil {
		if startedRun {
			e.runs.CancelRun()
		}
		e.mu.Unlock()
		return err
	}
	e.mu.Unlock()
	if beforeActions != nil {
		beforeActions()
	}
	e.notifyStateObserver()
	return e.runScheduledActions(runCtx, onStreamChunk)
}

func (e *Engine) calculateTransitionLocked(event machine.Event) (machine.TransitionResult, error) {
	snapshot, err := machine.SnapshotFrom(e.runtimeData)
	if err != nil {
		return machine.TransitionResult{}, err
	}
	return machine.Transition(snapshot, event)
}

func (e *Engine) commitTransitionLocked(decision machine.TransitionResult) error {
	changeResult, err := e.runtimeDataChangeApplier.ApplyRuntimeDataChanges(e.runtimeData, decision)
	if err != nil {
		return err
	}
	if err := machine.ValidateRuntimeData(changeResult.RuntimeData); err != nil {
		return err
	}
	for _, change := range decision.ActionQueueChanges {
		if _, ok := change.(machine.ClearActionQueue); !ok {
			return machine.InvariantViolationError{Reason: "unknown action queue change"}
		}
	}
	e.runtimeData = changeResult.RuntimeData
	for range decision.ActionQueueChanges {
		e.actionQueue.Clear()
	}
	for _, action := range decision.ScheduledActions {
		e.actionQueue.Queue(e.runs.CurrentRunID(), action)
	}
	return nil
}

func (e *Engine) runScheduledActions(ctx context.Context, onStreamChunk func(protocol.StreamChunk)) error {
	runID := e.runs.CurrentRunID()
	for {
		e.mu.Lock()
		action, ok := e.actionQueue.Pop()
		if !ok {
			if e.runtimeData.State == machine.StateIdle {
				e.runs.FinishRun(runID)
			}
			e.mu.Unlock()
			return nil
		}
		e.mu.Unlock()
		if err := e.executeScheduledAction(ctx, action, onStreamChunk); err != nil {
			if errors.Is(err, context.Canceled) {
				e.runs.CancelRun()
				_ = e.DispatchEvent(ctx, machine.CancelRequested{}, nil)
			} else {
				_ = e.DispatchEvent(ctx, machine.ErrorOccurred{Err: err}, nil)
			}
			return err
		}
		// The action may have dispatched a transition event; notify so
		// observers see states that pass between snapshot points, such as
		// RunningTool while a tool executes.
		e.notifyStateObserver()
	}
}

func (e *Engine) executeScheduledAction(ctx context.Context, action execution.QueuedAction, onStreamChunk func(protocol.StreamChunk)) error {
	stream := onStreamChunk
	if onStreamChunk != nil {
		stream = func(chunk protocol.StreamChunk) { e.recordStreamChunk(action.RunID, chunk); onStreamChunk(chunk) }
	}
	completion, err := e.runner.Run(ctx, action, execution.ScheduledActionInput{Messages: e.Messages(), ToolSpecs: e.toolSpecs()}, stream)
	if err != nil {
		return err
	}
	if !e.runs.IsCurrent(completion.RunID) {
		return nil
	}
	toolSpecs := e.toolSpecs()
	e.mu.Lock()
	batch := cloneToolBatch(e.runtimeData.ToolBatch)
	event, err := e.resolver.Resolve(completion.Result, execution.ActionResultInput{ToolBatch: batch, ToolSpecs: toolSpecs})
	if err != nil {
		// runScheduledActions dispatches ErrorOccurred once for the returned
		// error; dispatching here too would append the runtime-error tool
		// message twice.
		e.mu.Unlock()
		return err
	}
	decision, err := e.calculateTransitionLocked(event)
	if err == nil {
		err = e.commitTransitionLocked(decision)
	}
	e.mu.Unlock()
	return err
}

func cloneToolBatch(batch *machine.ToolCallBatch) *machine.ToolCallBatch {
	if batch == nil {
		return nil
	}
	return &machine.ToolCallBatch{ID: batch.ID, Calls: append([]protocol.ToolCall(nil), batch.Calls...), Index: batch.Index}
}

func (e *Engine) toolSpecs() []protocol.ToolSpec { return e.runner.ToolSpecs() }

func (e *Engine) recordStreamChunk(runID execution.RunID, chunk protocol.StreamChunk) {
	if !e.runs.IsCurrent(runID) {
		return
	}
	e.mu.Lock()
	defer e.mu.Unlock()
	_ = e.commitTransitionLocked(machine.TransitionResult{
		NextState:          e.runtimeData.State,
		RuntimeDataChanges: []machine.RuntimeDataChange{machine.AppendStreamingAssistant{Chunk: chunk}},
	})
}
