package engine

import (
	"context"
	"errors"

	"super-agent/runtime/execution"
	"super-agent/runtime/machine"
	"super-agent/runtime/protocol"
)

func (e *Engine) DispatchEventThenRunActions(ctx context.Context, event machine.Event, chunks func(protocol.StreamChunk), afterDispatch func()) error {
	e.mu.Lock()
	snapshot, err := machine.SnapshotFrom(e.runtimeData)
	if err != nil {
		e.mu.Unlock()
		return err
	}
	decision, err := machine.Transition(snapshot, event)
	if err != nil {
		e.mu.Unlock()
		return err
	}
	_, runCtx := e.runs.StartRun(ctx)
	if err := e.applyTransitionLocked(decision); err != nil {
		e.runs.CancelRun()
		e.mu.Unlock()
		return err
	}
	e.mu.Unlock()
	afterDispatch()
	return e.runScheduledActions(runCtx, chunks)
}

func (e *Engine) dispatch(event machine.Event) error {
	e.mu.Lock()
	defer e.mu.Unlock()
	return e.dispatchLocked(event)
}
func (e *Engine) dispatchLocked(event machine.Event) error {
	snapshot, err := machine.SnapshotFrom(e.runtimeData)
	if err != nil {
		return err
	}
	decision, err := machine.Transition(snapshot, event)
	if err != nil {
		return err
	}
	return e.applyTransitionLocked(decision)
}
func (e *Engine) applyTransitionLocked(decision machine.TransitionResult) error {
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

func (e *Engine) runScheduledActions(ctx context.Context, chunks func(protocol.StreamChunk)) error {
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
		if err := e.executeScheduledAction(ctx, action, chunks); err != nil {
			if errors.Is(err, context.Canceled) {
				e.runs.CancelRun()
				_ = e.dispatch(machine.CancelRequested{})
			} else {
				_ = e.dispatch(machine.ErrorOccurred{Err: err})
			}
			return err
		}
		// The action may have dispatched a transition event; notify so
		// observers see states that pass between snapshot points, such as
		// RunningTool while a tool executes.
		e.notifyStateObserver()
	}
}

func (e *Engine) executeScheduledAction(ctx context.Context, action execution.QueuedAction, chunks func(protocol.StreamChunk)) error {
	stream := chunks
	if chunks != nil {
		stream = func(chunk protocol.StreamChunk) { e.recordStreamChunk(action.RunID, chunk); chunks(chunk) }
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
	err = e.dispatchLocked(event)
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
	_ = e.applyTransitionLocked(machine.TransitionResult{
		NextState:          e.runtimeData.State,
		RuntimeDataChanges: []machine.RuntimeDataChange{machine.AppendStreamingAssistant{Chunk: chunk}},
	})
}
