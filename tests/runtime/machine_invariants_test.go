package runtime_test

import (
	"context"
	"errors"
	"testing"

	. "super-agent/runtime"
)

func TestSnapshotFromRejectsInvalidRuntimeData(t *testing.T) {
	cases := []RuntimeData{
		{State: StateAdvancingQueue},
		{State: StateWaitingApproval},
		{State: StateRunningTool},
		{State: StateIdle, ToolBatch: &ToolCallBatch{}},
	}
	for _, state := range cases {
		_, err := SnapshotFrom(state)
		var invariant InvariantViolationError
		if !errors.As(err, &invariant) {
			t.Fatalf("SnapshotFrom(%s) error = %v, want InvariantViolationError", state.State, err)
		}
	}
}

func TestTransitionClassifiesStateMismatchAsUnexpectedEvent(t *testing.T) {
	event := ToolResultReceived{Call: ToolCall{ID: "call-1"}, Result: "ok"}
	_, err := Transition(transitionSnapshot(StateIdle, event), event)
	var unexpected UnexpectedEventError
	if !errors.As(err, &unexpected) {
		t.Fatalf("error = %v, want UnexpectedEventError", err)
	}
}

func TestTransitionRejectsApprovalForDifferentCall(t *testing.T) {
	pending := ToolCall{ID: "call-1", Name: "bash", Input: "pwd"}
	request := PermissionRequest{}
	state := RuntimeData{
		State:             StateWaitingApproval,
		PendingTool:       &pending,
		PendingPermission: &request,
		ToolBatch:         &ToolCallBatch{Calls: []ToolCall{pending}, Index: 1},
	}
	snapshot, err := SnapshotFrom(state)
	if err != nil {
		t.Fatal(err)
	}
	_, err = Transition(snapshot, ApprovalGranted{Call: ToolCall{ID: "call-2", Name: "bash", Input: "pwd"}})
	var protocol ProtocolViolationError
	if !errors.As(err, &protocol) {
		t.Fatalf("error = %v, want ProtocolViolationError", err)
	}
}

func TestTransitionRejectsResultForDifferentCurrentCall(t *testing.T) {
	current := ToolCall{ID: "call-1", Name: "bash", Input: "pwd"}
	state := RuntimeData{
		State:       StateRunningTool,
		CurrentTool: &current,
		ToolBatch:   &ToolCallBatch{Calls: []ToolCall{current}, Index: 1},
	}
	snapshot, err := SnapshotFrom(state)
	if err != nil {
		t.Fatal(err)
	}
	_, err = Transition(snapshot, ToolResultReceived{Call: ToolCall{ID: "call-2"}, Result: "ok"})
	var protocol ProtocolViolationError
	if !errors.As(err, &protocol) {
		t.Fatalf("error = %v, want ProtocolViolationError", err)
	}
}

func TestTransitionRejectsBatchFinishedBeforeQueueEmpty(t *testing.T) {
	call := ToolCall{ID: "call-1"}
	state := RuntimeData{State: StateAdvancingQueue, ToolBatch: &ToolCallBatch{Calls: []ToolCall{call}}}
	snapshot, err := SnapshotFrom(state)
	if err != nil {
		t.Fatal(err)
	}
	_, err = Transition(snapshot, ToolBatchFinished{})
	var protocol ProtocolViolationError
	if !errors.As(err, &protocol) {
		t.Fatalf("error = %v, want ProtocolViolationError", err)
	}
}

func TestRuntimeDataChangeApplierDoesNotMutateOriginalStateWhenValidationFails(t *testing.T) {
	call := ToolCall{ID: "call-1"}
	original := RuntimeData{
		State:     StateAdvancingQueue,
		ToolBatch: &ToolCallBatch{Calls: []ToolCall{call}},
	}
	_, err := (DefaultRuntimeDataChangeApplier{}).ApplyRuntimeDataChanges(original, TransitionResult{
		NextState: StateRunningTool,
		RuntimeDataChanges: []RuntimeDataChange{
			AdvanceToolCallBatch{},
		},
	})
	var invariant InvariantViolationError
	if !errors.As(err, &invariant) {
		t.Fatalf("error = %v, want InvariantViolationError", err)
	}
	if original.State != StateAdvancingQueue || original.ToolBatch.Index != 0 || original.CurrentTool != nil {
		t.Fatalf("original state mutated after failed changeResult: %+v", original)
	}
}

type invalidRuntimeDataChangeApplier struct{}

func (invalidRuntimeDataChangeApplier) ApplyRuntimeDataChanges(state RuntimeData, result TransitionResult) (RuntimeDataChangeResult, error) {
	if state.State == StateInitializing {
		return (DefaultRuntimeDataChangeApplier{}).ApplyRuntimeDataChanges(state, result)
	}
	return RuntimeDataChangeResult{RuntimeData: RuntimeData{
		State:     StateIdle,
		ToolBatch: &ToolCallBatch{},
	}}, nil
}

func TestEngineDoesNotCommitInvalidCustomRuntimeDataChangeResult(t *testing.T) {
	approvals := NewMemoryApprovalStore()
	runs := NewDefaultRunController()
	engine := NewEngineWithComponents(
		NewDefaultScheduledActionRunner(NewDefaultScheduledActionExecutor(nil, nil)),
		NewDefaultActionResultResolver(NewDefaultPolicy(), approvals),
		invalidRuntimeDataChangeApplier{},
		runs,
		approvals,
		nil,
	)
	if err := engine.Ready(); err != nil {
		t.Fatal(err)
	}
	err := engine.RunTurn(context.Background(), UserMessageSubmitted{Content: "hi"}, nil, nil)
	var invariant InvariantViolationError
	if !errors.As(err, &invariant) {
		t.Fatalf("error = %v, want InvariantViolationError", err)
	}
	if engine.State() != StateIdle {
		t.Fatalf("state = %s, want unchanged Idle", engine.State())
	}
	if _, ok := runs.CurrentContext(); ok {
		t.Fatal("failed changeResult left an active run context")
	}
}

func TestToolFlowPreservesMachineInvariants(t *testing.T) {
	call := ToolCall{ID: "call-1", Name: "bash", Input: "pwd"}
	state := RuntimeData{State: StateWaitingLLM}
	events := []Event{
		ToolBatchReceived{Calls: []ToolCall{call}},
		ToolCallNeedsApproval{Call: call, Request: PermissionRequest{ToolName: "bash"}},
		ApprovalGranted{Call: call},
		ToolResultReceived{Call: call, Result: "ok"},
		ToolBatchFinished{},
	}
	wantStates := []State{
		StateAdvancingQueue,
		StateWaitingApproval,
		StateRunningTool,
		StateAdvancingQueue,
		StateWaitingLLM,
	}
	for i, event := range events {
		snapshot, err := SnapshotFrom(state)
		if err != nil {
			t.Fatalf("step %d snapshot: %v", i, err)
		}
		result, err := Transition(snapshot, event)
		if err != nil {
			t.Fatalf("step %d transition: %v", i, err)
		}
		changeResult, err := (DefaultRuntimeDataChangeApplier{}).ApplyRuntimeDataChanges(state, result)
		if err != nil {
			t.Fatalf("step %d changeResult: %v", i, err)
		}
		state = changeResult.RuntimeData
		if state.State != wantStates[i] {
			t.Fatalf("step %d state = %s, want %s", i, state.State, wantStates[i])
		}
	}
}
