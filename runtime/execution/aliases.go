package execution

import (
	"super-agent/runtime/machine"
	"super-agent/runtime/protocol"
)

type Message = protocol.Message
type ToolCall = protocol.ToolCall
type ToolCallBatch = machine.ToolCallBatch
type CommandClass = machine.CommandClass
type PermissionRequest = machine.PermissionRequest
type ApprovalDecision = machine.ApprovalDecision

const (
	ApproveOnce   = machine.ApproveOnce
	ApproveAlways = machine.ApproveAlways
	DenyApproval  = machine.DenyApproval
)

const (
	CommandClassReadOnly    = machine.CommandClassReadOnly
	CommandClassWrite       = machine.CommandClassWrite
	CommandClassNetwork     = machine.CommandClassNetwork
	CommandClassDestructive = machine.CommandClassDestructive
	CommandClassUnknown     = machine.CommandClassUnknown
)

type ToolSpec = protocol.ToolSpec
type ModelResponse = protocol.ModelResponse
type StreamChunk = protocol.StreamChunk
type Model = protocol.Model
type ToolRunner = protocol.ToolRunner

type Event = machine.Event
type AssistantMessageReceived = machine.AssistantMessageReceived
type ToolBatchReceived = machine.ToolBatchReceived
type ToolBatchFinished = machine.ToolBatchFinished
type ToolCallNeedsApproval = machine.ToolCallNeedsApproval
type ToolCallReadyToRun = machine.ToolCallReadyToRun
type ToolResultReceived = machine.ToolResultReceived
type ApprovalGranted = machine.ApprovalGranted
type ApprovalAlwaysGranted = machine.ApprovalAlwaysGranted
type ApprovalDenied = machine.ApprovalDenied

type ScheduledAction = machine.ScheduledAction
type CallModel = machine.CallModel
type RunTool = machine.RunTool
type CheckToolQueue = machine.CheckToolQueue
type AwaitApproval = machine.AwaitApproval
type AppendStreamingAssistant = machine.AppendStreamingAssistant
