package session

import (
	enginepkg "super-agent/runtime/engine"
	"super-agent/runtime/execution"
	"super-agent/runtime/machine"
	"super-agent/runtime/protocol"
)

type State = machine.State

type Message = protocol.Message
type Attachment = protocol.Attachment
type ToolCall = protocol.ToolCall
type PermissionRequest = machine.PermissionRequest
type ApprovalDecision = machine.ApprovalDecision
type ApprovalWaitFunc = execution.ApprovalWaitFunc
type PermissionMode = execution.PermissionMode
type PermissionRules = execution.PermissionRules
type StreamChunk = protocol.StreamChunk
type Engine = enginepkg.Engine
type EngineView = enginepkg.EngineView
type UserMessageSubmitted = machine.UserMessageSubmitted

const (
	ApproveOnce   = machine.ApproveOnce
	ApproveAlways = machine.ApproveAlways
	DenyApproval  = machine.DenyApproval

	PermissionModeAsk    = execution.PermissionModeAsk
	PermissionModeBypass = execution.PermissionModeBypass
)

var ValidPermissionMode = execution.ValidPermissionMode

const (
	RoleSystem = protocol.RoleSystem
	RoleTool   = protocol.RoleTool
)
