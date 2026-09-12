package app

import (
	"context"
	"fmt"
	"sync"

	"super-agent/runtime"
	"super-agent/tui"
)

// TUIConversation adapts the runtime application API to the terminal port.
// Conversion stays at the composition edge so neither side knows the other.
type TUIConversation struct {
	session *runtime.Session
	mcp     *MCPController
	agents  *AgentController
}

func NewTUIConversation(session *runtime.Session, controllers ...any) *TUIConversation {
	conversation := &TUIConversation{session: session}
	for _, controller := range controllers {
		switch controller := controller.(type) {
		case *MCPController:
			conversation.mcp = controller
		case *AgentController:
			conversation.agents = controller
		}
	}
	return conversation
}

func (a *TUIConversation) ListAgents() []tui.AgentSummary {
	if a.agents == nil {
		return nil
	}
	profiles := a.agents.List()
	result := make([]tui.AgentSummary, 0, len(profiles))
	for _, profile := range profiles {
		result = append(result, tui.AgentSummary{Name: profile.Name, Provider: profile.Provider, Model: profile.Model, PermissionMode: string(profile.PermissionMode)})
	}
	return result
}

func (a *TUIConversation) CurrentAgent() tui.AgentSummary {
	if a.agents == nil {
		return tui.AgentSummary{}
	}
	profile := a.agents.Current()
	return tui.AgentSummary{Name: profile.Name, Provider: profile.Provider, Model: profile.Model, PermissionMode: string(profile.PermissionMode)}
}

func (a *TUIConversation) UseAgent(name string) error {
	if a.agents == nil {
		return fmt.Errorf("agent profiles are unavailable")
	}
	return a.agents.Use(name)
}

func (a *TUIConversation) Fork(title string) (string, error) {
	meta, err := a.session.Fork(title)
	return string(meta.ID), err
}
func (a *TUIConversation) Memories() ([]string, error) { return a.session.Memories() }
func (a *TUIConversation) Remember(value string) error { return a.session.Remember(value) }
func (a *TUIConversation) ForgetMemories() error       { return a.session.ForgetMemories() }
func (a *TUIConversation) GitDiff(ctx context.Context) (string, error) {
	if a.agents == nil {
		return "", fmt.Errorf("workflow tools are unavailable")
	}
	return a.agents.GitDiff(ctx)
}
func (a *TUIConversation) GitStatus(ctx context.Context) (string, error) {
	if a.agents == nil {
		return "", fmt.Errorf("workflow tools are unavailable")
	}
	return a.agents.GitStatus(ctx)
}

func (a *TUIConversation) Snapshot() tui.ConversationView {
	return toConversationView(a.session.Snapshot())
}

func (a *TUIConversation) RunTurn(ctx context.Context, query string, notifications chan<- tui.ConversationNotification, approvals <-chan tui.ApprovalDecision) error {
	runtimeNotifications := make(chan runtime.SessionNotification, 100)
	runtimeApprovals := make(chan runtime.ApprovalDecision, 1)
	done := make(chan struct{})
	var bridges sync.WaitGroup
	bridges.Add(2)
	go func() {
		defer bridges.Done()
		defer close(notifications)
		for notification := range runtimeNotifications {
			notifications <- toConversationNotification(notification)
		}
	}()
	go func() {
		defer bridges.Done()
		defer close(runtimeApprovals)
		for {
			select {
			case <-ctx.Done():
				return
			case <-done:
				return
			case decision, ok := <-approvals:
				if !ok {
					return
				}
				runtimeApprovals <- runtime.ApprovalDecision(decision)
			}
		}
	}()
	err := a.session.RunTurn(ctx, query, runtimeNotifications, runtimeApprovals)
	close(done)
	bridges.Wait()
	return err
}

func (a *TUIConversation) Cancel() error { return a.session.Cancel() }
func (a *TUIConversation) Reset() error  { return a.session.Reset() }
func (a *TUIConversation) Compact(ctx context.Context, summary string) error {
	// The keep-newest default lives in the runtime session.
	return a.session.Compact(ctx, summary, 0)
}
func (a *TUIConversation) Undo() error { return a.session.Undo() }
func (a *TUIConversation) SetPermissionMode(mode string) error {
	return a.session.SetPermissionMode(runtime.PermissionMode(mode))
}
func (a *TUIConversation) PermissionMode() string {
	return string(a.session.PermissionMode())
}
func (a *TUIConversation) AutoApproveTools() bool {
	return a.session.AutoApproveTools()
}

func (a *TUIConversation) ListMCPServers() []tui.MCPServerSummary {
	if a.mcp == nil {
		return nil
	}
	servers := a.mcp.List()
	result := make([]tui.MCPServerSummary, 0, len(servers))
	for _, server := range servers {
		result = append(result, tui.MCPServerSummary{Name: server.Name, Tools: server.Tools})
	}
	return result
}

func (a *TUIConversation) AddMCPServer(ctx context.Context, name, command string, args []string) error {
	if a.mcp == nil {
		return fmt.Errorf("MCP management is unavailable")
	}
	return a.mcp.Add(ctx, name, command, args)
}

func (a *TUIConversation) RemoveMCPServer(name string) error {
	if a.mcp == nil {
		return fmt.Errorf("MCP management is unavailable")
	}
	return a.mcp.Remove(name)
}

func (a *TUIConversation) RestartMCPServer(ctx context.Context, name string) error {
	if a.mcp == nil {
		return fmt.Errorf("MCP management is unavailable")
	}
	return a.mcp.Restart(ctx, name)
}

func (a *TUIConversation) ListSessions() ([]tui.SessionSummary, error) {
	summaries, err := a.session.ListSessions()
	if err != nil {
		return nil, err
	}
	result := make([]tui.SessionSummary, 0, len(summaries))
	for _, item := range summaries {
		result = append(result, tui.SessionSummary{ID: string(item.ID), Title: item.Title, Provider: item.Provider, Model: item.Model, CWD: item.CWD, ParentID: string(item.ParentID)})
	}
	return result, nil
}

func (a *TUIConversation) Resume(id string) error { return a.session.Resume(runtime.SessionID(id)) }
func (a *TUIConversation) RenameSession(id, title string) error {
	return a.session.RenameSession(runtime.SessionID(id), title)
}
func (a *TUIConversation) DeleteSession(id string) error {
	return a.session.DeleteSession(runtime.SessionID(id))
}

func toConversationNotification(notification runtime.SessionNotification) tui.ConversationNotification {
	switch notification := notification.(type) {
	case runtime.StateChanged:
		return tui.AgentStatusChanged{Status: toTUIStatus(notification.State)}
	case runtime.ToolApprovalRequested:
		return tui.ToolApprovalRequested{ToolCall: toTUIToolCall(notification.ToolCall), Request: toTUIPermission(notification.Request), BatchIndex: notification.BatchIndex, BatchTotal: notification.BatchTotal}
	case runtime.ToolApprovalCleared:
		return tui.ToolApprovalCleared{}
	case runtime.StreamChunkReceived:
		return tui.StreamChunkReceived{Message: toTUIMessagePtr(notification.Message)}
	case runtime.MessageAppended:
		return tui.MessageAppended{Message: toTUIMessage(notification.Message)}
	case runtime.SessionError:
		return tui.ConversationError{Err: notification.Err}
	default:
		// Surface instead of silently dropping so new runtime event types
		// cannot degrade the UI without a trace.
		return tui.ConversationError{Err: fmt.Errorf("unknown runtime session notification: %T", notification)}
	}
}

func toConversationView(view runtime.EngineView) tui.ConversationView {
	messages := make([]tui.Message, 0, len(view.Messages))
	for _, message := range view.Messages {
		messages = append(messages, toTUIMessage(message))
	}
	result := tui.ConversationView{AgentStatus: toTUIStatus(view.State), Messages: messages, PendingToolBatchIndex: view.PendingToolBatchIndex, PendingToolBatchTotal: view.PendingToolBatchTotal, StreamingMessage: toTUIMessagePtr(view.StreamingMessage)}
	if view.PendingTool != nil {
		call := toTUIToolCall(*view.PendingTool)
		result.PendingTool = &call
	}
	if view.PendingPermission != nil {
		req := toTUIPermission(*view.PendingPermission)
		result.PendingPermission = &req
	}
	return result
}

func toTUIStatus(state runtime.State) tui.AgentStatus {
	switch state {
	case runtime.StateInitializing:
		return tui.AgentStatus{Label: "Initializing", Busy: true}
	case runtime.StateIdle:
		return tui.AgentStatus{Label: "Idle"}
	case runtime.StateWaitingLLM:
		return tui.AgentStatus{Label: "WaitingLLM", Busy: true}
	case runtime.StateWaitingApproval:
		return tui.AgentStatus{Label: "WaitingApproval", AwaitingApproval: true}
	case runtime.StateRunningTool:
		return tui.AgentStatus{Label: "RunningTool", Busy: true}
	case runtime.StateAdvancingQueue:
		return tui.AgentStatus{Label: "AdvancingQueue", Busy: true}
	default:
		return tui.AgentStatus{Label: "Unknown"}
	}
}

func toTUIMessagePtr(message *runtime.Message) *tui.Message {
	if message == nil {
		return nil
	}
	converted := toTUIMessage(*message)
	return &converted
}

func toTUIMessage(message runtime.Message) tui.Message {
	calls := make([]*tui.ToolCall, 0, len(message.ToolCalls))
	for _, call := range message.ToolCalls {
		if call == nil {
			continue
		}
		converted := toTUIToolCall(*call)
		calls = append(calls, &converted)
	}
	return tui.Message{Role: tui.Role(message.Role), Content: message.Content, ReasoningContent: message.ReasoningContent, ToolCallID: message.ToolCallID, ToolName: message.ToolName, ToolCalls: calls, Interrupted: message.Interrupted}
}

func toTUIToolCall(call runtime.ToolCall) tui.ToolCall {
	return tui.ToolCall{ID: call.ID, Name: call.Name, Input: call.Input}
}

func toTUIPermission(req runtime.PermissionRequest) tui.PermissionRequest {
	return tui.PermissionRequest{ToolName: req.ToolName, Command: req.Command, CommandClass: string(req.CommandClass), CWD: req.CWD, TouchedPaths: append([]string(nil), req.TouchedPaths...), EnvVars: append([]string(nil), req.EnvVars...), Reason: req.Reason}
}
