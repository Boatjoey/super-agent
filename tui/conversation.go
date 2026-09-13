package tui

import (
	"context"

	"super-agent/tui/approval"
	"super-agent/tui/attachments"
	"super-agent/tui/commands"
	"super-agent/tui/transcript"
)

type AgentStatus struct {
	Label            string
	Busy             bool
	AwaitingApproval bool
}

type Role = transcript.Role

const RoleAssistant = transcript.RoleAssistant

type ToolCall = transcript.ToolCall
type Message = transcript.Message
type MessageAttachment = transcript.Attachment

// Display DTOs stay aliased at the root so the composition boundary keeps
// addressing one package while the owning feature holds the definition.
type SessionSummary = commands.SessionSummary
type MCPServerSummary = commands.MCPServerSummary
type AgentSummary = commands.AgentSummary
type AttachmentSummary = attachments.Item

type ApprovalDecision = approval.Decision

const (
	ApproveOnce   = approval.ApproveOnce
	ApproveAlways = approval.ApproveAlways
	DenyApproval  = approval.Deny
)

type PermissionRequest struct {
	ToolName     string
	Command      string
	CommandClass string
	CWD          string
	TouchedPaths []string
	EnvVars      []string
	Reason       string
}

type ConversationView struct {
	AgentStatus           AgentStatus
	Messages              []Message
	PendingTool           *ToolCall
	PendingPermission     *PermissionRequest
	PendingToolBatchIndex int
	PendingToolBatchTotal int
	StreamingMessage      *Message
}

type ConversationNotification interface{ isConversationNotification() }
type AgentStatusChanged struct{ Status AgentStatus }

func (AgentStatusChanged) isConversationNotification() {}

type ToolApprovalRequested struct {
	ToolCall               ToolCall
	Request                PermissionRequest
	BatchIndex, BatchTotal int
}

func (ToolApprovalRequested) isConversationNotification() {}

type ToolApprovalCleared struct{}

func (ToolApprovalCleared) isConversationNotification() {}

type StreamChunkReceived struct{ Message *Message }

func (StreamChunkReceived) isConversationNotification() {}

type MessageAppended struct{ Message Message }

func (MessageAppended) isConversationNotification() {}

type ConversationError struct{ Err error }

func (ConversationError) isConversationNotification() {}

type SnapshotPort interface {
	Snapshot() ConversationView
}

type TurnPort interface {
	RunTurn(context.Context, string, chan<- ConversationNotification, <-chan ApprovalDecision) error
	Cancel() error
}

// Conversation remains the composition-boundary bundle accepted by New. App
// keeps only the ports the turn lifecycle needs and routes every other
// capability to the feature that owns it.
type Conversation interface {
	SnapshotPort
	TurnPort
	commands.SessionPort
	commands.PermissionPort
	commands.MCPPort
	commands.AgentPort
	commands.MemoryPort
	commands.WorkspacePort
	commands.ExtensionPort
	attachments.Port
}
