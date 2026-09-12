package tui

import "context"

type AgentStatus struct {
	Label            string
	Busy             bool
	AwaitingApproval bool
}

type Role string

const RoleAssistant Role = "assistant"

type ToolCall struct{ ID, Name, Input string }

type Message struct {
	Role             Role
	Content          string
	ReasoningContent string
	ToolCallID       string
	ToolName         string
	ToolCalls        []*ToolCall
	Interrupted      bool
	Attachments      []AttachmentSummary
}

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

type SessionSummary struct{ ID, Title, Provider, Model, CWD, ParentID string }
type MCPServerSummary struct {
	Name  string
	Tools []string
}
type AgentSummary struct{ Name, Provider, Model, PermissionMode string }
type AttachmentSummary struct{ Name, MIME string }

type ApprovalDecision string

const (
	ApproveOnce   ApprovalDecision = "once"
	ApproveAlways ApprovalDecision = "always"
	DenyApproval  ApprovalDecision = "deny"
)

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

// Conversation is the TUI input port. Its DTOs contain no runtime or storage types.
type Conversation interface {
	Snapshot() ConversationView
	RunTurn(context.Context, string, chan<- ConversationNotification, <-chan ApprovalDecision) error
	Cancel() error
	Reset() error
	ListSessions() ([]SessionSummary, error)
	Resume(string) error
	RenameSession(string, string) error
	DeleteSession(string) error
	Compact(context.Context, string) error
	Undo() error
	SetPermissionMode(string) error
	// PermissionMode and AutoApproveTools report the runtime policy so the
	// TUI never derives behavior locally.
	PermissionMode() string
	AutoApproveTools() bool
	ListMCPServers() []MCPServerSummary
	AddMCPServer(context.Context, string, string, []string) error
	RemoveMCPServer(string) error
	RestartMCPServer(context.Context, string) error
	ListAgents() []AgentSummary
	CurrentAgent() AgentSummary
	UseAgent(string) error
	Fork(string) (string, error)
	Memories() ([]string, error)
	Remember(string) error
	ForgetMemories() error
	GitDiff(context.Context) (string, error)
	GitStatus(context.Context) (string, error)
	CustomCommands() []string
	ExpandCustomCommand(string, string) (string, error)
	Export(string) (string, error)
	Attach(string) (AttachmentSummary, error)
	PendingAttachments() []AttachmentSummary
}
