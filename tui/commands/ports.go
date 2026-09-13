// Package commands owns the slash-command catalogue, the input semantics of
// each command, and the background operations they start. It defines the narrow
// ports it needs; the composition boundary supplies one implementation.
package commands

import "context"

// SessionSummary describes a saved session for listing and resuming.
type SessionSummary struct{ ID, Title, Provider, Model, CWD, ParentID string }

// MCPServerSummary describes one configured MCP server and its discovered tools.
type MCPServerSummary struct {
	Name  string
	Tools []string
}

// AgentSummary describes a selected agent profile.
type AgentSummary struct{ Name, Provider, Model, PermissionMode string }

// Attachment is a file queued for the next turn.
type Attachment struct{ Name, MIME string }

// Ports are the capabilities the command feature needs, each owned by the use
// case that requires it.
type Ports struct {
	Sessions    SessionPort
	Permissions PermissionPort
	MCP         MCPPort
	Agents      AgentPort
	Memory      MemoryPort
	Workspace   WorkspacePort
	Extensions  ExtensionPort
}

// SessionPort is the conversation lifecycle commands operate on.
type SessionPort interface {
	Reset() error
	ListSessions() ([]SessionSummary, error)
	Resume(string) error
	RenameSession(string, string) error
	DeleteSession(string) error
	Compact(context.Context, string) error
	Undo() error
	Fork(string) (string, error)
	Export(string) (string, error)
}

// PermissionPort reads and changes the active permission policy. Mode and
// approval are read back from the runtime so the display cannot drift from
// actual behavior.
type PermissionPort interface {
	SetPermissionMode(string) error
	PermissionMode() string
	AutoApproveTools() bool
}

// MCPPort manages MCP server lifecycle.
type MCPPort interface {
	ListMCPServers() []MCPServerSummary
	AddMCPServer(context.Context, string, string, []string) error
	RemoveMCPServer(string) error
	RestartMCPServer(context.Context, string) error
}

// AgentPort lists and selects agent profiles.
type AgentPort interface {
	ListAgents() []AgentSummary
	CurrentAgent() AgentSummary
	UseAgent(string) error
}

// MemoryPort reads and writes cross-session memory.
type MemoryPort interface {
	Memories() ([]string, error)
	Remember(string) error
	ForgetMemories() error
}

// WorkspacePort runs read-only repository and language-server queries.
type WorkspacePort interface {
	GitDiff(context.Context) (string, error)
	GitStatus(context.Context) (string, error)
	Diagnostics(context.Context, string) (string, error)
}

// ExtensionPort exposes discovered commands, skills, and plugins.
type ExtensionPort interface {
	CustomCommands() []string
	ExpandCustomCommand(string, string) (string, error)
	Skills() []string
	Plugins() []string
}
