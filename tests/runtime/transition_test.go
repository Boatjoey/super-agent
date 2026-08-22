package runtime_test

import (
	"errors"
	"reflect"
	"testing"

	. "super-agent/runtime"
)

// transitionCase describes one (State, Event) -> TransitionResult expectation.
// Counts catch missing or extra outputs. Type lists assert exact order.
type transitionCase struct {
	name                   string
	state                  State
	event                  Event
	wantState              State
	wantErr                bool
	stateChangeCount       int
	actionQueueChangeCount int
	scheduledActionCount   int
	stateChangeTypes       []StateChange
	actionQueueChangeTypes []ActionQueueChange
	scheduledActionTypes   []ScheduledAction
}

func sampleToolCall() ToolCall {
	return ToolCall{ID: "call-1", Name: "bash", Input: "pwd"}
}

func sampleToolCalls() []ToolCall {
	return []ToolCall{
		{ID: "call-1", Name: "first", Input: "a"},
		{ID: "call-2", Name: "second", Input: "b"},
	}
}

func transitionSnapshot(state State, event Event) MachineSnapshot {
	engineState := RuntimeData{State: state}
	call := sampleToolCall()
	switch ev := event.(type) {
	case ApprovalGranted:
		call = ev.Call
	case ApprovalAlwaysGranted:
		call = ev.Call
	case ApprovalDenied:
		call = ev.Call
	case ToolResultReceived:
		call = ev.Call
	case ToolCallNeedsApproval:
		call = ev.Call
	case ToolCallReadyToRun:
		call = ev.Call
	}
	switch state {
	case StateAdvancingQueue:
		engineState.ToolBatch = &ToolCallBatch{Calls: []ToolCall{call}}
		if _, ok := event.(ToolBatchFinished); ok {
			engineState.ToolBatch.Index = 1
		}
	case StateWaitingApproval:
		request := PermissionRequest{}
		engineState.PendingTool = &call
		engineState.PendingPermission = &request
		engineState.ToolBatch = &ToolCallBatch{Calls: []ToolCall{call}, Index: 1}
	case StateRunningTool:
		engineState.CurrentTool = &call
		engineState.ToolBatch = &ToolCallBatch{Calls: []ToolCall{call}, Index: 1}
	}
	snapshot, err := SnapshotFrom(engineState)
	if err != nil {
		panic(err)
	}
	return snapshot
}

func TestTransitionTable(t *testing.T) {
	cases := []transitionCase{
		// --- EngineReady ---
		{
			name: "EngineReady/Initializing->Idle", state: StateInitializing,
			event: EngineReady{}, wantState: StateIdle,
		},

		// --- UserMessageSubmitted ---
		{
			name: "UserMessageSubmitted/Idle->WaitingLLM", state: StateIdle,
			event: UserMessageSubmitted{Content: "hi"}, wantState: StateWaitingLLM,
			stateChangeCount: 1, scheduledActionCount: 1,
			stateChangeTypes:     []StateChange{AppendUserMessage{}},
			scheduledActionTypes: []ScheduledAction{CallModel{}},
		},
		{
			name: "UserMessageSubmitted/rejects_when_not_idle", state: StateWaitingLLM,
			event: UserMessageSubmitted{Content: "hi"}, wantErr: true,
		},

		// --- AssistantMessageReceived ---
		{
			name: "AssistantMessageReceived/WaitingLLM->Idle", state: StateWaitingLLM,
			event:            AssistantMessageReceived{Response: ModelResponse{Content: "hi"}},
			wantState:        StateIdle,
			stateChangeCount: 1,
			stateChangeTypes: []StateChange{AppendAssistantMessage{}},
		},
		{
			name: "AssistantMessageReceived/rejects_when_not_WaitingLLM", state: StateIdle,
			event:   AssistantMessageReceived{Response: ModelResponse{Content: "hi"}},
			wantErr: true,
		},

		// --- ToolBatchReceived ---
		{
			name: "ToolBatchReceived/WaitingLLM->AdvancingQueue", state: StateWaitingLLM,
			event: ToolBatchReceived{
				Content: "thinking", Calls: sampleToolCalls(), ReasoningContent: "reasoning",
			},
			wantState:            StateAdvancingQueue,
			stateChangeCount:     2, // AppendAssistantMessage + SetToolCallBatch
			scheduledActionCount: 1,
			stateChangeTypes:     []StateChange{AppendAssistantMessage{}, SetToolCallBatch{}},
			scheduledActionTypes: []ScheduledAction{CheckToolQueue{}},
		},
		{
			name: "ToolBatchReceived/rejects_when_not_WaitingLLM", state: StateIdle,
			event:   ToolBatchReceived{Calls: sampleToolCalls()},
			wantErr: true,
		},

		// --- ToolBatchFinished ---
		{
			name: "ToolBatchFinished/AdvancingQueue->WaitingLLM", state: StateAdvancingQueue,
			event:                ToolBatchFinished{},
			wantState:            StateWaitingLLM,
			stateChangeCount:     1,
			scheduledActionCount: 1,
			stateChangeTypes:     []StateChange{ClearToolCallBatch{}},
			scheduledActionTypes: []ScheduledAction{CallModel{}},
		},
		{
			name: "ToolBatchFinished/rejects_when_not_AdvancingQueue", state: StateIdle,
			event:   ToolBatchFinished{},
			wantErr: true,
		},

		// --- ApprovalGranted ---
		{
			name: "ApprovalGranted/WaitingApproval->RunningTool", state: StateWaitingApproval,
			event:                ApprovalGranted{Call: sampleToolCall()},
			wantState:            StateRunningTool,
			stateChangeCount:     2,
			scheduledActionCount: 1,
			stateChangeTypes:     []StateChange{SetCurrentTool{}, ClearPendingTool{}},
			scheduledActionTypes: []ScheduledAction{RunTool{}},
		},
		{
			name: "ApprovalGranted/rejects_when_not_WaitingApproval", state: StateIdle,
			event:   ApprovalGranted{Call: sampleToolCall()},
			wantErr: true,
		},

		// --- ApprovalAlwaysGranted ---
		{
			name: "ApprovalAlwaysGranted/WaitingApproval->RunningTool", state: StateWaitingApproval,
			event:                ApprovalAlwaysGranted{Call: sampleToolCall()},
			wantState:            StateRunningTool,
			stateChangeCount:     2,
			scheduledActionCount: 1,
			stateChangeTypes:     []StateChange{SetCurrentTool{}, ClearPendingTool{}},
			scheduledActionTypes: []ScheduledAction{RunTool{}},
		},
		{
			name: "ApprovalAlwaysGranted/rejects_when_not_WaitingApproval", state: StateIdle,
			event:   ApprovalAlwaysGranted{Call: sampleToolCall()},
			wantErr: true,
		},

		// --- ApprovalDenied ---
		{
			name: "ApprovalDenied/WaitingApproval->AdvancingQueue", state: StateWaitingApproval,
			event:                ApprovalDenied{Call: sampleToolCall()},
			wantState:            StateAdvancingQueue,
			stateChangeCount:     2, // ClearPendingTool + AppendToolResult
			scheduledActionCount: 1,
			stateChangeTypes:     []StateChange{ClearPendingTool{}, AppendToolResult{}},
			scheduledActionTypes: []ScheduledAction{CheckToolQueue{}},
		},
		{
			name: "ApprovalDenied/rejects_when_not_WaitingApproval", state: StateIdle,
			event:   ApprovalDenied{Call: sampleToolCall()},
			wantErr: true,
		},

		// --- ToolResultReceived ---
		{
			name: "ToolResultReceived/RunningTool->AdvancingQueue", state: StateRunningTool,
			event:                ToolResultReceived{Call: sampleToolCall(), Result: "ok"},
			wantState:            StateAdvancingQueue,
			stateChangeCount:     2,
			scheduledActionCount: 1,
			stateChangeTypes:     []StateChange{AppendToolResult{}, ClearCurrentTool{}},
			scheduledActionTypes: []ScheduledAction{CheckToolQueue{}},
		},
		{
			name: "ToolResultReceived/rejects_when_not_RunningTool", state: StateIdle,
			event:   ToolResultReceived{Call: sampleToolCall(), Result: "ok"},
			wantErr: true,
		},

		// --- ToolCallNeedsApproval ---
		{
			name: "ToolCallNeedsApproval/AdvancingQueue->WaitingApproval", state: StateAdvancingQueue,
			event:            ToolCallNeedsApproval{Call: sampleToolCall()},
			wantState:        StateWaitingApproval,
			stateChangeCount: 2, // SetPendingTool + AdvanceToolCallBatch
			stateChangeTypes: []StateChange{SetPendingTool{}, AdvanceToolCallBatch{}},
		},
		{
			name: "ToolCallNeedsApproval/rejects_when_not_AdvancingQueue", state: StateIdle,
			event:   ToolCallNeedsApproval{Call: sampleToolCall()},
			wantErr: true,
		},

		// --- ToolCallReadyToRun ---
		{
			name: "ToolCallReadyToRun/AdvancingQueue->RunningTool", state: StateAdvancingQueue,
			event:                ToolCallReadyToRun{Call: sampleToolCall()},
			wantState:            StateRunningTool,
			stateChangeCount:     2,
			scheduledActionCount: 1,
			stateChangeTypes:     []StateChange{AdvanceToolCallBatch{}, SetCurrentTool{}},
			scheduledActionTypes: []ScheduledAction{RunTool{}},
		},
		{
			name: "ToolCallReadyToRun/rejects_when_not_AdvancingQueue", state: StateIdle,
			event:   ToolCallReadyToRun{Call: sampleToolCall()},
			wantErr: true,
		},

		// --- ErrorOccurred ---
		{
			name: "ErrorOccurred/WaitingLLM->Idle", state: StateWaitingLLM,
			event:            ErrorOccurred{Err: errors.New("boom")},
			wantState:        StateIdle,
			stateChangeCount: 5, actionQueueChangeCount: 1,
			stateChangeTypes:       []StateChange{FlushStreamingAssistant{}, AppendToolResult{}, ClearPendingTool{}, ClearCurrentTool{}, ClearToolCallBatch{}},
			actionQueueChangeTypes: []ActionQueueChange{ClearActionQueue{}},
		},
		{
			name: "ErrorOccurred/RunningTool->Idle", state: StateRunningTool,
			event:            ErrorOccurred{Err: errors.New("boom")},
			wantState:        StateIdle,
			stateChangeCount: 5, actionQueueChangeCount: 1,
			stateChangeTypes:       []StateChange{FlushStreamingAssistant{}, AppendToolResult{}, ClearPendingTool{}, ClearCurrentTool{}, ClearToolCallBatch{}},
			actionQueueChangeTypes: []ActionQueueChange{ClearActionQueue{}},
		},
		{
			name: "ErrorOccurred/AdvancingQueue->Idle", state: StateAdvancingQueue,
			event:            ErrorOccurred{Err: errors.New("boom")},
			wantState:        StateIdle,
			stateChangeCount: 5, actionQueueChangeCount: 1,
			stateChangeTypes:       []StateChange{FlushStreamingAssistant{}, AppendToolResult{}, ClearPendingTool{}, ClearCurrentTool{}, ClearToolCallBatch{}},
			actionQueueChangeTypes: []ActionQueueChange{ClearActionQueue{}},
		},

		// --- CancelRequested ---
		{
			name: "CancelRequested/WaitingLLM->Idle", state: StateWaitingLLM,
			event: CancelRequested{}, wantState: StateIdle,
			stateChangeCount: 4, actionQueueChangeCount: 1,
			stateChangeTypes:       []StateChange{FlushStreamingAssistant{}, ClearPendingTool{}, ClearCurrentTool{}, ClearToolCallBatch{}},
			actionQueueChangeTypes: []ActionQueueChange{ClearActionQueue{}},
		},
		{
			name: "CancelRequested/WaitingApproval->Idle", state: StateWaitingApproval,
			event: CancelRequested{}, wantState: StateIdle,
			stateChangeCount: 4, actionQueueChangeCount: 1,
			stateChangeTypes:       []StateChange{FlushStreamingAssistant{}, ClearPendingTool{}, ClearCurrentTool{}, ClearToolCallBatch{}},
			actionQueueChangeTypes: []ActionQueueChange{ClearActionQueue{}},
		},
		{
			name: "CancelRequested/RunningTool->Idle", state: StateRunningTool,
			event: CancelRequested{}, wantState: StateIdle,
			stateChangeCount: 4, actionQueueChangeCount: 1,
			stateChangeTypes:       []StateChange{FlushStreamingAssistant{}, ClearPendingTool{}, ClearCurrentTool{}, ClearToolCallBatch{}},
			actionQueueChangeTypes: []ActionQueueChange{ClearActionQueue{}},
		},
		{
			name: "CancelRequested/AdvancingQueue->Idle", state: StateAdvancingQueue,
			event: CancelRequested{}, wantState: StateIdle,
			stateChangeCount: 4, actionQueueChangeCount: 1,
			stateChangeTypes:       []StateChange{FlushStreamingAssistant{}, ClearPendingTool{}, ClearCurrentTool{}, ClearToolCallBatch{}},
			actionQueueChangeTypes: []ActionQueueChange{ClearActionQueue{}},
		},

		// --- ResetRequested ---
		{
			name: "ResetRequested/Idle->Idle", state: StateIdle,
			event: ResetRequested{}, wantState: StateIdle,
			stateChangeCount: 1, actionQueueChangeCount: 1,
			stateChangeTypes:       []StateChange{ResetConversation{}},
			actionQueueChangeTypes: []ActionQueueChange{ClearActionQueue{}},
		},
		{
			name: "ResetRequested/WaitingLLM->Idle", state: StateWaitingLLM,
			event: ResetRequested{}, wantState: StateIdle,
			stateChangeCount: 1, actionQueueChangeCount: 1,
			stateChangeTypes:       []StateChange{ResetConversation{}},
			actionQueueChangeTypes: []ActionQueueChange{ClearActionQueue{}},
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			result, err := Transition(transitionSnapshot(tc.state, tc.event), tc.event)
			if tc.wantErr {
				if err == nil {
					t.Fatalf("expected error, got nil")
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if result.NextState != tc.wantState {
				t.Fatalf("nextState = %s, want %s", result.NextState, tc.wantState)
			}
			if len(result.StateChanges) != tc.stateChangeCount {
				t.Fatalf("state changes = %d (%+v), want %d", len(result.StateChanges), result.StateChanges, tc.stateChangeCount)
			}
			if len(result.ActionQueueChanges) != tc.actionQueueChangeCount {
				t.Fatalf("action queue changes = %d (%+v), want %d", len(result.ActionQueueChanges), result.ActionQueueChanges, tc.actionQueueChangeCount)
			}
			if len(result.ScheduledActions) != tc.scheduledActionCount {
				t.Fatalf("scheduled actions = %d (%+v), want %d", len(result.ScheduledActions), result.ScheduledActions, tc.scheduledActionCount)
			}
			for i, want := range tc.stateChangeTypes {
				if reflect.TypeOf(result.StateChanges[i]) != reflect.TypeOf(want) {
					t.Fatalf("state change[%d] = %T, want %T", i, result.StateChanges[i], want)
				}
			}
			for i, want := range tc.actionQueueChangeTypes {
				if reflect.TypeOf(result.ActionQueueChanges[i]) != reflect.TypeOf(want) {
					t.Fatalf("action queue change[%d] = %T, want %T", i, result.ActionQueueChanges[i], want)
				}
			}
			for i, want := range tc.scheduledActionTypes {
				if reflect.TypeOf(result.ScheduledActions[i]) != reflect.TypeOf(want) {
					t.Fatalf("scheduled action[%d] = %T, want %T", i, result.ScheduledActions[i], want)
				}
			}
		})
	}
}
