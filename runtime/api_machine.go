package runtime

import "super-agent/runtime/machine"

type Event = machine.Event

var AllEvents = machine.AllEvents

type UserMessageSubmitted = machine.UserMessageSubmitted
type AssistantMessageReceived = machine.AssistantMessageReceived
type ToolBatchReceived = machine.ToolBatchReceived
type ToolCallNeedsApproval = machine.ToolCallNeedsApproval
type ToolCallReadyToRun = machine.ToolCallReadyToRun
type ToolCallDenied = machine.ToolCallDenied
type ToolBatchFinished = machine.ToolBatchFinished
type ToolResultReceived = machine.ToolResultReceived
type ApprovalGranted = machine.ApprovalGranted
type ApprovalAlwaysGranted = machine.ApprovalAlwaysGranted
type ApprovalDenied = machine.ApprovalDenied
type ErrorOccurred = machine.ErrorOccurred
type CancelRequested = machine.CancelRequested
type ResetRequested = machine.ResetRequested
type EngineReady = machine.EngineReady

type RuntimeDataChange = machine.RuntimeDataChange

var AllRuntimeDataChanges = machine.AllRuntimeDataChanges

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
type ClearToolCallBatch = machine.ClearToolCallBatch
type ResetConversation = machine.ResetConversation

type ActionPlan = machine.ActionPlan

type ScheduledAction = machine.ScheduledAction

var AllScheduledActions = machine.AllScheduledActions

type CallModel = machine.CallModel
type RunTool = machine.RunTool
type CheckToolQueue = machine.CheckToolQueue
type AwaitApproval = machine.AwaitApproval
type TransitionResult = machine.TransitionResult
type RuntimeData = machine.RuntimeData
type MachineSnapshot = machine.MachineSnapshot
type UnexpectedEventError = machine.UnexpectedEventError
type ProtocolViolationError = machine.ProtocolViolationError
type InvariantViolationError = machine.InvariantViolationError
type RuntimeDataChangeResult = machine.RuntimeDataChangeResult
type RuntimeDataChangeApplier = machine.RuntimeDataChangeApplier
type DefaultRuntimeDataChangeApplier = machine.DefaultRuntimeDataChangeApplier

func SnapshotFrom(runtimeData RuntimeData) (MachineSnapshot, error) {
	return machine.SnapshotFrom(runtimeData)
}

func ValidateRuntimeData(runtimeData RuntimeData) error {
	return machine.ValidateRuntimeData(runtimeData)
}

func Transition(snapshot MachineSnapshot, event Event) (TransitionResult, error) {
	return machine.Transition(snapshot, event)
}
