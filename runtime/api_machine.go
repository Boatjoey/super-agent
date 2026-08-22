package runtime

import "super-agent/runtime/machine"

type Event = machine.Event

var AllEvents = machine.AllEvents

type UserMessageSubmitted = machine.UserMessageSubmitted
type AssistantMessageReceived = machine.AssistantMessageReceived
type ToolBatchReceived = machine.ToolBatchReceived
type ToolCallNeedsApproval = machine.ToolCallNeedsApproval
type ToolCallReadyToRun = machine.ToolCallReadyToRun
type ToolBatchFinished = machine.ToolBatchFinished
type ToolResultReceived = machine.ToolResultReceived
type ApprovalGranted = machine.ApprovalGranted
type ApprovalAlwaysGranted = machine.ApprovalAlwaysGranted
type ApprovalDenied = machine.ApprovalDenied
type ErrorOccurred = machine.ErrorOccurred
type CancelRequested = machine.CancelRequested
type ResetRequested = machine.ResetRequested
type EngineReady = machine.EngineReady

type StateChange = machine.StateChange

var AllStateChanges = machine.AllStateChanges

type AppendUserMessage = machine.AppendUserMessage
type AppendAssistantMessage = machine.AppendAssistantMessage
type AppendToolResult = machine.AppendToolResult
type AppendStreamingAssistant = machine.AppendStreamingAssistant
type FlushStreamingAssistant = machine.FlushStreamingAssistant
type SetPendingTool = machine.SetPendingTool
type SetToolCallBatch = machine.SetToolCallBatch
type AdvanceToolCallBatch = machine.AdvanceToolCallBatch
type ClearPendingTool = machine.ClearPendingTool
type SetCurrentTool = machine.SetCurrentTool
type ClearCurrentTool = machine.ClearCurrentTool
type ClearScheduledActions = machine.ClearScheduledActions
type ClearToolCallBatch = machine.ClearToolCallBatch
type ResetContext = machine.ResetContext

type ScheduledAction = machine.ScheduledAction

var AllScheduledActions = machine.AllScheduledActions

type CallModel = machine.CallModel
type RunTool = machine.RunTool
type ProcessNextToolCall = machine.ProcessNextToolCall
type TransitionResult = machine.TransitionResult
type EngineState = machine.EngineState
type MachineSnapshot = machine.MachineSnapshot
type UnexpectedEventError = machine.UnexpectedEventError
type ProtocolViolationError = machine.ProtocolViolationError
type InvariantViolationError = machine.InvariantViolationError
type SchedulerOp = machine.SchedulerOp
type ClearScheduledActionsOp = machine.ClearScheduledActionsOp
type StateChangeResult = machine.StateChangeResult
type StateChangeApplier = machine.StateChangeApplier
type DefaultStateChangeApplier = machine.DefaultStateChangeApplier

func SnapshotFrom(state EngineState) (MachineSnapshot, error) {
	return machine.SnapshotFrom(state)
}

func ValidateState(state EngineState) error {
	return machine.ValidateState(state)
}

func Transition(snapshot MachineSnapshot, event Event) (TransitionResult, error) {
	return machine.Transition(snapshot, event)
}
