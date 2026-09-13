package tui

import (
	"context"
	"sort"
	"strings"

	tea "github.com/charmbracelet/bubbletea"
)

var slashCommands = []string{
	"/clear", "/compact", "/delete-session", "/help", "/instructions", "/permissions",
	"/mcp", "/quit", "/rename", "/reset", "/resume", "/sessions", "/undo", "/agent", "/build", "/plan", "/mode", "/fork", "/memory", "/remember", "/forget", "/review", "/diff", "/fix-ci", "/branch", "/commit-message", "/export", "/share", "/attach", "/attachments", "/commands", "/skills", "/plugins", "/diagnostics",
}

var slashCommandDescriptions = map[string]string{
	"/clear":          "Reset the conversation",
	"/agent":          "List or select an agent <name>",
	"/attach":         "Attach a workspace file <path>",
	"/attachments":    "List pending attachments",
	"/build":          "Switch to the build agent",
	"/branch":         "Show branch and working-tree status",
	"/commit-message": "Suggest a commit message",
	"/commands":       "List custom commands",
	"/compact":        "Compact context [summary]",
	"/delete-session": "Delete a saved session <id>",
	"/diff":           "Preview the current patch",
	"/diagnostics":    "Show LSP diagnostics <path>",
	"/export":         "Export session <markdown|json>",
	"/fix-ci":         "Inspect and fix failing CI checks",
	"/help":           "Show commands and shortcuts",
	"/fork":           "Fork the current transcript [title]",
	"/forget":         "Clear cross-session memory",
	"/instructions":   "Show loaded instruction files",
	"/mcp":            "Manage MCP servers <list|add|remove|restart>",
	"/mode":           "Switch mode <plan|build>",
	"/memory":         "Show cross-session memory",
	"/permissions":    "Inspect or change permission mode",
	"/plugins":        "List loaded plugins",
	"/plan":           "Switch to the plan agent",
	"/quit":           "Exit Super Agent",
	"/rename":         "Rename a session <id> <title>",
	"/remember":       "Add cross-session memory <text>",
	"/reset":          "Reset the conversation",
	"/review":         "Review the current changes",
	"/resume":         "Resume a saved session <id>",
	"/sessions":       "List saved sessions",
	"/share":          "Create a local HTML share file",
	"/skills":         "List loaded skills",
	"/undo":           "Restore the last checkpoint",
}

func completeSlashCommand(value string) (string, bool) {
	if !strings.HasPrefix(value, "/") || strings.ContainsAny(value, " \t\n") {
		return value, false
	}
	match := ""
	for _, command := range slashCommands {
		if !strings.HasPrefix(command, value) {
			continue
		}
		if match != "" {
			return value, false
		}
		match = command
	}
	if match == "" || match == value {
		return value, false
	}
	return match, true
}

func matchingSlashCommands(value string) []string {
	if !strings.HasPrefix(value, "/") || strings.ContainsAny(value, " \t\n") {
		return nil
	}
	var matches []string
	for _, command := range slashCommands {
		if strings.HasPrefix(command, value) {
			matches = append(matches, command)
		}
	}
	return matches
}

func (a App) slashMatches() []string {
	matches := matchingSlashCommands(a.input.Value())
	value := a.input.Value()
	if strings.HasPrefix(value, "/") && !strings.ContainsAny(value, " \t\n") {
		custom := append([]string(nil), a.session.CustomCommands()...)
		sort.Strings(custom)
		for _, name := range custom {
			command := "/" + strings.TrimPrefix(name, "/")
			if strings.HasPrefix(command, value) {
				matches = append(matches, command)
			}
		}
	}
	return matches
}

func (a App) completeSelectedSlashCommand() (App, bool) {
	matches := a.slashMatches()
	if len(matches) == 0 {
		return a, false
	}
	if a.slashSelection >= len(matches) {
		a.slashSelection = len(matches) - 1
	}
	selected := matches[a.slashSelection]
	if a.input.Value() == selected {
		return a, false
	}
	a.input.SetValue(selected)
	a.input.CursorEnd()
	a.slashSelection = 0
	a.resizeInput()
	return a, true
}

func (a App) submit() (tea.Model, tea.Cmd) {
	if a.compacting || a.managingMCP {
		a.status = "Background operation in progress…"
		return a, nil
	}
	text := strings.TrimSpace(a.input.Value())
	if text == "" {
		return a, nil
	}
	a.remember(text)
	if strings.HasPrefix(text, "/") {
		return a.runSlashCommand(text)
	}
	return a.submitPrompt(text)
}

func (a App) queueInput() (tea.Model, tea.Cmd) {
	if a.compacting {
		a.status = "Compacting conversation…"
		return a, nil
	}
	text := strings.TrimSpace(a.input.Value())
	if text == "" {
		return a, nil
	}
	if strings.HasPrefix(text, "/") {
		a.err = "Slash commands are unavailable while a turn is running"
		return a, nil
	}
	a.remember(text)
	a.queuedInputs = append(a.queuedInputs, text)
	a.input.SetValue("")
	a.resizeInput()
	a.status = "Message queued"
	return a, nil
}

func (a App) steerInput() (tea.Model, tea.Cmd) {
	text := strings.TrimSpace(a.input.Value())
	if text == "" {
		return a, nil
	}
	if strings.HasPrefix(text, "/") {
		a.err = "Slash commands are unavailable while a turn is running"
		return a, nil
	}
	a.remember(text)
	a.queuedInputs = append([]string{text}, a.queuedInputs...)
	a.input.SetValue("")
	a.resizeInput()
	a.cancelRun(false)
	a.status = "Steering current turn"
	return a, nil
}

func (a *App) remember(text string) {
	if len(a.history) == 0 || a.history[len(a.history)-1] != text {
		a.history = append(a.history, text)
	}
	a.historyIdx = len(a.history)
	a.historyDraft = ""
}

func (a App) runSlashCommand(text string) (tea.Model, tea.Cmd) {
	parts := strings.Fields(text)
	command := parts[0]
	a.input.SetValue("")
	a.resizeInput()
	switch command {
	case "/agent":
		a.handleAgent(parts)
	case "/plan":
		a.handleAgent([]string{"/agent", "plan"})
	case "/build":
		a.handleAgent([]string{"/agent", "build"})
	case "/mode":
		if len(parts) != 2 || (parts[1] != "plan" && parts[1] != "build") {
			a.err = "Usage: /mode <plan|build>"
			break
		}
		a.handleAgent([]string{"/agent", parts[1]})
	case "/fork":
		a.handleFork(strings.TrimSpace(strings.TrimPrefix(text, command)))
	case "/memory":
		a.handleMemory()
	case "/remember":
		a.handleRemember(strings.TrimSpace(strings.TrimPrefix(text, command)))
	case "/forget":
		a.handleForget()
	case "/diff":
		a.handleGitDiff()
	case "/branch":
		a.handleGitStatus()
	case "/review":
		return a.submitPrompt("Review the current changes. Inspect the git diff, relevant code, and LSP diagnostics when configured, then report only actionable defects with file and line references. Do not modify files.")
	case "/fix-ci":
		return a.submitPrompt("Inspect the repository CI configuration and current failures, reproduce them locally, implement the fixes, and verify the result.")
	case "/commit-message":
		return a.submitPrompt("Inspect the current git diff and suggest one concise conventional commit subject. Do not modify files or commit.")
	case "/export":
		if len(parts) != 2 {
			a.err = "Usage: /export <markdown|json>"
			break
		}
		a.handleExport(parts[1])
	case "/share":
		a.handleExport("html")
	case "/attach":
		if len(parts) != 2 {
			a.err = "Usage: /attach <path>"
			break
		}
		attachment, err := a.session.Attach(parts[1])
		if err != nil {
			a.err = "Attach failed: " + err.Error()
			break
		}
		a.err = ""
		a.status = "Attached " + attachment.Name + " (" + attachment.MIME + ")"
	case "/attachments":
		attachments := a.session.PendingAttachments()
		if len(attachments) == 0 {
			a.status = "No pending attachments"
		} else {
			var names []string
			for _, attachment := range attachments {
				names = append(names, attachment.Name+" ("+attachment.MIME+")")
			}
			a.queueOutput("Attachments:\n- " + strings.Join(names, "\n- "))
			a.status = "Attachments"
		}
	case "/commands":
		a.queueOutput(formatNamedItems("Custom commands", a.session.CustomCommands()))
		a.status = "Custom commands"
	case "/skills":
		a.queueOutput(formatNamedItems("Skills", a.session.Skills()))
		a.status = "Skills"
	case "/plugins":
		a.queueOutput(formatNamedItems("Plugins", a.session.Plugins()))
		a.status = "Plugins"
	case "/diagnostics":
		if len(parts) != 2 {
			a.err = "Usage: /diagnostics <path>"
			break
		}
		result, err := a.session.Diagnostics(context.Background(), parts[1])
		if err != nil {
			a.err = "Diagnostics failed: " + err.Error()
			break
		}
		a.err = ""
		a.queueOutput(result)
		a.status = "Diagnostics"
	case "/instructions":
		a.err = ""
		a.queueOutput(formatInstructions(a.info.InstructionPaths))
		a.status = "Instructions"
	case "/permissions":
		a.handlePermissions(parts)
	case "/mcp":
		return a.handleMCP(parts)
	case "/clear", "/reset":
		a.handleReset()
	case "/sessions":
		a.handleSessions()
	case "/resume":
		a.handleResume(parts)
	case "/rename":
		a.handleRename(text, parts)
	case "/delete-session":
		a.handleDelete(parts)
	case "/compact":
		return a.handleCompact(text, command)
	case "/undo":
		a.handleUndo()
	case "/quit", "/exit":
		return a, tea.Quit
	case "/help":
		a.showHelp = true
	default:
		arguments := strings.TrimSpace(strings.TrimPrefix(text, command))
		expanded, err := a.session.ExpandCustomCommand(strings.TrimPrefix(command, "/"), arguments)
		if err != nil {
			a.err = "Unknown command: " + command
			break
		}
		return a.submitPrompt(expanded)
	}
	output := a.takeOutput()
	return a, a.printCommand(output)
}

func formatNamedItems(label string, items []string) string {
	if len(items) == 0 {
		return "No " + strings.ToLower(label)
	}
	return label + ":\n- " + strings.Join(items, "\n- ")
}

func (a *App) handleExport(format string) {
	path, err := a.session.Export(format)
	if err != nil {
		a.err = "Export failed: " + err.Error()
		return
	}
	a.err = ""
	a.status = "Exported " + path
}

func (a *App) handleGitDiff() {
	result, err := a.session.GitDiff(context.Background())
	if err != nil {
		a.err = "Diff failed: " + err.Error()
		return
	}
	a.err = ""
	if strings.TrimSpace(result) == "" {
		a.status = "No changes"
	} else {
		a.queueOutput(result)
		a.status = "Patch preview"
	}
}

func (a *App) handleGitStatus() {
	result, err := a.session.GitStatus(context.Background())
	if err != nil {
		a.err = "Branch status failed: " + err.Error()
		return
	}
	a.err = ""
	a.queueOutput(result)
	a.status = "Branch status"
}

func (a *App) handleFork(title string) {
	id, err := a.session.Fork(title)
	if err != nil {
		a.err = "Fork failed: " + err.Error()
		return
	}
	a.err = ""
	a.status = "Forked session " + id
	a.refreshSnapshot()
}

func (a *App) handleMemory() {
	items, err := a.session.Memories()
	if err != nil {
		a.err = "Memory failed: " + err.Error()
		return
	}
	a.err = ""
	if len(items) == 0 {
		a.status = "No cross-session memory"
	} else {
		a.queueOutput("Memory:\n- " + strings.Join(items, "\n- "))
		a.status = "Memory"
	}
}

func (a *App) handleRemember(value string) {
	if err := a.session.Remember(value); err != nil {
		a.err = "Remember failed: " + err.Error()
		return
	}
	a.err = ""
	a.status = "Memory saved"
}

func (a *App) handleForget() {
	if err := a.session.ForgetMemories(); err != nil {
		a.err = "Forget failed: " + err.Error()
		return
	}
	a.err = ""
	a.status = "Memory cleared"
}

func (a *App) handleAgent(parts []string) {
	if len(parts) == 1 || (len(parts) == 2 && parts[1] == "list") {
		current := a.session.CurrentAgent().Name
		var rows []string
		for _, profile := range a.session.ListAgents() {
			marker := "  "
			if profile.Name == current {
				marker = "* "
			}
			rows = append(rows, marker+profile.Name+" ("+profile.Provider+"/"+profile.Model+", "+profile.PermissionMode+")")
		}
		a.err = ""
		a.queueOutput(strings.Join(rows, "\n"))
		a.status = "Agents"
		return
	}
	if len(parts) != 2 {
		a.err = "Usage: /agent <list|name>"
		return
	}
	if err := a.session.UseAgent(parts[1]); err != nil {
		a.err = "Agent failed: " + err.Error()
		return
	}
	profile := a.session.CurrentAgent()
	a.info.Provider, a.info.ModelName = profile.Provider, profile.Model
	a.info.PermissionMode = profile.PermissionMode
	a.info.AutoApprove = a.session.AutoApproveTools()
	a.err = ""
	a.status = "Using agent " + profile.Name
	a.refreshSnapshot()
}

func (a App) handleMCP(parts []string) (tea.Model, tea.Cmd) {
	if len(parts) == 1 || (len(parts) == 2 && parts[1] == "list") {
		a.err = ""
		a.queueOutput(formatMCPServers(a.session.ListMCPServers()))
		a.status = "MCP servers"
		return a, a.printCommand(a.takeOutput())
	}
	operation := parts[1]
	ctx := context.Background()
	var run func() error
	var status string
	switch operation {
	case "add":
		if len(parts) < 4 {
			a.err = "Usage: /mcp add <name> <command> [args...]"
			return a, nil
		}
		name, command, args := parts[2], parts[3], append([]string(nil), parts[4:]...)
		run = func() error { return a.session.AddMCPServer(ctx, name, command, args) }
		status = "Added MCP server " + name
	case "remove":
		if len(parts) != 3 {
			a.err = "Usage: /mcp remove <name>"
			return a, nil
		}
		name := parts[2]
		run = func() error { return a.session.RemoveMCPServer(name) }
		status = "Removed MCP server " + name
	case "restart":
		if len(parts) != 3 {
			a.err = "Usage: /mcp restart <name>"
			return a, nil
		}
		name := parts[2]
		run = func() error { return a.session.RestartMCPServer(ctx, name) }
		status = "Restarted MCP server " + name
	default:
		a.err = "Usage: /mcp <list|add|remove|restart>"
		return a, nil
	}
	a.err = ""
	a.managingMCP = true
	a.status = "Updating MCP servers…"
	return a, func() tea.Msg { return mcpDoneMsg{status: status, err: run()} }
}

func (a *App) handlePermissions(parts []string) {
	a.err = ""
	if len(parts) >= 3 && parts[1] == "mode" {
		mode := parts[2]
		if err := a.session.SetPermissionMode(mode); err != nil {
			a.err = "Permissions failed: " + err.Error()
			return
		}
		// Report the runtime's view of the policy instead of deriving it
		// locally, so the display cannot drift from actual behavior.
		a.info.PermissionMode = a.session.PermissionMode()
		a.info.AutoApprove = a.session.AutoApproveTools()
	}
	a.queueOutput(formatPermissions(a.info))
	a.status = "Permissions"
}

func (a *App) handleReset() {
	if err := a.session.Reset(); err != nil {
		a.err = "Reset failed: " + err.Error()
	} else {
		a.err = ""
		a.queueOutput(divider("New conversation"))
	}
	a.refreshSnapshot()
}

func (a *App) handleSessions() {
	summaries, err := a.session.ListSessions()
	if err != nil {
		a.err = "Sessions failed: " + err.Error()
		return
	}
	a.err = ""
	a.queueOutput(formatSessions(summaries))
	a.status = "Sessions"
}

func (a *App) handleResume(parts []string) {
	if len(parts) < 2 {
		a.err = "Usage: /resume <id>"
		return
	}
	if err := a.session.Resume(parts[1]); err != nil {
		a.err = "Resume failed: " + err.Error()
		return
	}
	a.err = ""
	a.status = "Resumed " + parts[1]
	a.queueOutput(divider("Resumed session " + parts[1]))
	a.refreshSnapshot()
}

func (a *App) handleRename(text string, parts []string) {
	if len(parts) < 3 {
		a.err = "Usage: /rename <id> <title>"
		return
	}
	title := strings.TrimSpace(strings.TrimPrefix(text, parts[0]+" "+parts[1]))
	if err := a.session.RenameSession(parts[1], title); err != nil {
		a.err = "Rename failed: " + err.Error()
		return
	}
	a.err = ""
	a.status = "Renamed " + parts[1]
}

func (a *App) handleDelete(parts []string) {
	if len(parts) < 2 {
		a.err = "Usage: /delete-session <id>"
		return
	}
	if err := a.session.DeleteSession(parts[1]); err != nil {
		a.err = "Delete failed: " + err.Error()
		return
	}
	a.err = ""
	a.status = "Deleted " + parts[1]
}

// handleCompact runs outside the update loop: with no summary it triggers
// a full model call that must not freeze the UI. The keep-newest policy
// stays in the runtime; the TUI only passes the optional summary.
func (a App) handleCompact(text, command string) (tea.Model, tea.Cmd) {
	summary := strings.TrimSpace(strings.TrimPrefix(text, command))
	a.compacting = true
	a.status = "Compacting conversation…"
	run := func() tea.Msg { return compactDoneMsg{err: a.session.Compact(context.Background(), summary)} }
	return a, run
}

func (a *App) handleUndo() {
	if err := a.session.Undo(); err != nil {
		a.err = "Undo failed: " + err.Error()
		return
	}
	a.err = ""
	a.status = "Restored last checkpoint"
	a.queueOutput(divider("Restored checkpoint"))
	a.refreshSnapshot()
}

func (a App) submitPrompt(text string) (tea.Model, tea.Cmd) {
	a.err = ""
	a.status = ""
	a.commandOutput = ""
	a.streamingMessage = nil
	a.agentStatus = AgentStatus{Label: "Submitting", Busy: true}
	a.pendingTool = nil
	a.pendingRequest = PermissionRequest{}
	a.input.SetValue("")
	a.resizeInput()
	a.notificationsCh = make(chan ConversationNotification, 100)
	a.approvalsCh = make(chan ApprovalDecision, 1)
	ctx, cancel := context.WithCancel(context.Background())
	a.cancel = cancel
	a.turn++
	run := func() tea.Msg {
		return submitDoneMsg{err: a.session.RunTurn(ctx, text, a.notificationsCh, a.approvalsCh)}
	}
	return a, tea.Batch(waitForNotification(a.notificationsCh, a.turn), run)
}

func (a App) handleApprovalKey(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	if a.approvalSubmitted {
		return a, nil
	}
	var decision ApprovalDecision
	switch strings.ToLower(msg.String()) {
	case "up", "k":
		if a.approvalSelection > 0 {
			a.approvalSelection--
		}
		return a, nil
	case "down", "j":
		if a.approvalSelection < 2 {
			a.approvalSelection++
		}
		return a, nil
	case "enter":
		decision = []ApprovalDecision{ApproveOnce, ApproveAlways, DenyApproval}[a.approvalSelection]
	case "1", "y":
		decision = ApproveOnce
	case "2", "a":
		decision = ApproveAlways
	case "3", "n":
		decision = DenyApproval
	default:
		return a, nil
	}
	a.streamingMessage = nil
	a.approvalSubmitted = true
	a.approvalsCh <- decision
	return a, nil
}
