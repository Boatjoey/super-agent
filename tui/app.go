package tui

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/charmbracelet/bubbles/spinner"
	"github.com/charmbracelet/bubbles/textarea"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/charmbracelet/x/ansi"
)

type StartupInfo struct {
	Provider         string
	ModelName        string
	AutoApprove      bool
	PermissionMode   string
	NoTools          bool
	CWD              string
	InstructionPaths []string
}

type App struct {
	session           Conversation
	input             textarea.Model
	spinner           spinner.Model
	styles            Styles
	info              StartupInfo
	history           []string
	historyIdx        int
	historyDraft      string
	queuedInputs      []string
	slashSelection    int
	ready             bool
	width             int
	height            int
	showHelp          bool
	err               string
	status            string
	cancel            context.CancelFunc
	notificationsCh   chan ConversationNotification
	approvalsCh       chan ApprovalDecision
	agentStatus       AgentStatus
	messages          []Message
	pendingTool       *ToolCall
	pendingRequest    PermissionRequest
	pendingToolIndex  int
	pendingToolTotal  int
	approvalSelection int
	approvalSubmitted bool
	streamingMessage  *Message
	turn              int
	compacting        bool
	managingMCP       bool
	commandOutput     string
	expandLatestTools bool
	expandAllTools    bool
	expandLatestThink bool
	expandAllThink    bool
	writeClipboard    func(string) error
	printOutput       func(string) tea.Cmd
}

// Option customizes the model as New builds it.
type Option func(*App)

// WithClipboardWriter replaces the clipboard write, so tests can observe what a
// copy produced without depending on a system clipboard.
func WithClipboardWriter(write func(string) error) Option {
	return func(a *App) { a.writeClipboard = write }
}

// WithOutputPrinter replaces terminal scrollback output for tests.
func WithOutputPrinter(print func(string) tea.Cmd) Option {
	return func(a *App) { a.printOutput = print }
}

type submitDoneMsg struct {
	err error
}

type compactDoneMsg struct {
	err error
}

type mcpDoneMsg struct {
	status string
	err    error
}

type conversationNotificationMsg struct {
	notification ConversationNotification
	turn         int
}

// outputCommittedMsg advances dynamic state only after the renderer has put
// completed content into terminal scrollback.
// waitForNotification listens on ch and tags the delivered notification with
// its turn so stale notifications from a replaced channel can be discarded.
func waitForNotification(ch <-chan ConversationNotification, turn int) tea.Cmd {
	return func() tea.Msg {
		notification, ok := <-ch
		if !ok {
			return nil
		}
		return conversationNotificationMsg{notification: notification, turn: turn}
	}
}

func New(session Conversation, info StartupInfo, options ...Option) App {
	styles := DefaultStyles()

	input := textarea.New()
	input.Placeholder = "Ask me anything... (try /help)"
	input.Focus()
	input.CharLimit = 2000
	input.ShowLineNumbers = false
	input.SetPromptFunc(3, func(line int) string {
		if line == 0 {
			return " ❯ "
		}
		return "   "
	})
	input.FocusedStyle.Prompt = lipgloss.NewStyle().Foreground(lipgloss.Color("6")).Bold(true)
	input.FocusedStyle.Text = lipgloss.NewStyle().Foreground(lipgloss.Color("15"))
	input.SetHeight(1)

	s := spinner.New()
	s.Spinner = spinner.Pulse
	s.Style = lipgloss.NewStyle().Foreground(lipgloss.Color("6"))

	app := App{
		session:         session,
		input:           input,
		spinner:         s,
		styles:          styles,
		info:            info,
		history:         []string{},
		notificationsCh: make(chan ConversationNotification, 100),
		approvalsCh:     make(chan ApprovalDecision, 1),
		agentStatus:     AgentStatus{Label: "Idle"},
		writeClipboard:  defaultClipboardWrite,
		printOutput:     func(content string) tea.Cmd { return tea.Println(content) },
	}
	for _, option := range options {
		option(&app)
	}
	return app
}

func (a App) Init() tea.Cmd {
	// The initial events channel has no producer; arming a listener on it
	// would leak a goroutine for the app's lifetime. submitPrompt arms the
	// first listener on the real turn channel.
	return tea.Batch(
		a.input.Cursor.BlinkCmd(),
		a.spinner.Tick,
	)
}

func (a App) infoBar() string {
	modelStr := a.info.ModelName
	toolsStr := "tools on"
	if a.info.NoTools {
		toolsStr = "tools off"
	}
	mode := a.info.PermissionMode
	if mode == "" {
		mode = "ask"
	}
	sep := a.styles.Footer.Render(" · ")
	join := func(parts []string) string {
		styled := make([]string, len(parts))
		for i, part := range parts {
			styled[i] = a.styles.Footer.Render(part)
		}
		return strings.Join(styled, sep)
	}
	return clampLines(a.width, join([]string{mode, modelStr, toolsStr}))
}

func (a App) isBusy() bool {
	return a.compacting || a.managingMCP || a.agentStatus.Busy
}

func (a App) needsInput() bool {
	return a.agentStatus.AwaitingApproval
}

func (a App) welcomeString() string {
	parts := []string{a.info.ModelName}
	if location := displayCWD(a.info.CWD); location != "" {
		parts = append(parts, location)
	}
	if count := len(a.info.InstructionPaths); count > 0 {
		parts = append(parts, filepath.Base(a.info.InstructionPaths[count-1]))
	}
	return "Super Agent\n" + strings.Join(parts, " · ")
}

func (a App) footerView() string {
	var b strings.Builder

	if a.err != "" {
		b.WriteString(a.styles.Error.Render(" !! error: "+a.err) + "\n")
	} else if a.status != "" {
		b.WriteString(a.styles.Status.Render(" "+compactStatus(a.status, 3)) + "\n")
	} else {
		b.WriteByte('\n')
	}

	compact := a.height > 0 && a.height < 18
	if len(a.queuedInputs) > 0 {
		b.WriteString(a.styles.Status.Render(fmt.Sprintf(" Queued (%d)", len(a.queuedInputs))) + "\n")
		limit := min(3, len(a.queuedInputs))
		if compact {
			limit = 0
		}
		for index := 0; index < limit; index++ {
			preview := strings.Join(strings.Fields(a.queuedInputs[index]), " ")
			if len([]rune(preview)) > 72 {
				preview = string([]rune(preview)[:72]) + "…"
			}
			b.WriteString(a.styles.Footer.Render(fmt.Sprintf(" %d. %s", index+1, preview)) + "\n")
		}
		if remaining := len(a.queuedInputs) - limit; remaining > 0 {
			b.WriteString(a.styles.Footer.Render(fmt.Sprintf(" … %d more", remaining)) + "\n")
		}
	}

	if attachments := a.session.PendingAttachments(); len(attachments) > 0 {
		names := make([]string, 0, len(attachments))
		for _, attachment := range attachments {
			names = append(names, attachment.Name)
		}
		b.WriteString(a.styles.Status.Render(" Attachments: "+strings.Join(names, ", ")) + "\n")
	}

	if call := a.pendingTool; call != nil {
		prompt := lipgloss.NewStyle().
			Background(lipgloss.Color("3")).
			Foreground(lipgloss.Color("0")).
			Padding(0, 1).
			Render(" ACTION REQUIRED ")
		progress := ""
		if a.pendingToolTotal > 0 {
			progress = fmt.Sprintf(" tool %d/%d:", a.pendingToolIndex, a.pendingToolTotal)
		}
		b.WriteString(prompt + progress + " approve " + lipgloss.NewStyle().Bold(true).Render(call.Name) + "?\n")
		options := []string{"1. Yes, run once", "2. Yes, always allow", "3. No, deny"}
		for index, option := range options {
			prefix := "  "
			style := a.styles.Footer
			if index == a.approvalSelection {
				prefix = "› "
				style = lipgloss.NewStyle().Foreground(lipgloss.Color("6")).Bold(true)
			}
			b.WriteString(style.Render(prefix+option) + "\n")
		}
		if a.approvalSubmitted {
			b.WriteString(a.styles.Status.Render(" Decision submitted…") + "\n")
		}
		if a.pendingRequest.ToolName != "" || a.pendingRequest.Reason != "" {
			meta := fmt.Sprintf(" class: %s cwd: %s", a.pendingRequest.CommandClass, firstNonEmpty(a.pendingRequest.CWD, a.info.CWD))
			if len(a.pendingRequest.TouchedPaths) > 0 {
				meta += " paths: " + strings.Join(a.pendingRequest.TouchedPaths, ",")
			}
			if a.pendingRequest.Reason != "" {
				meta += " reason: " + a.pendingRequest.Reason
			}
			b.WriteString(a.styles.Footer.Render(meta) + "\n")
		} else if call.Input != "" {
			input := call.Input
			if len(input) > 240 {
				input = input[:240] + "..."
			}
			b.WriteString(a.styles.Footer.Render(" cwd: "+a.info.CWD+" input: "+input) + "\n")
		}
	}

	if matches := a.slashMatches(); len(matches) > 0 && a.cancel == nil && a.pendingTool == nil {
		visible := 6
		if compact {
			visible = 3
		}
		start := 0
		if a.slashSelection >= visible {
			start = a.slashSelection - visible + 1
		}
		end := min(start+visible, len(matches))
		for index := start; index < end; index++ {
			prefix := "  "
			style := a.styles.Footer
			if index == a.slashSelection {
				prefix = "› "
				style = lipgloss.NewStyle().Foreground(lipgloss.Color("6")).Bold(true)
			}
			label := matches[index]
			if !compact {
				description := slashCommandDescriptions[matches[index]]
				if description == "" {
					description = "Custom command"
				}
				label = fmt.Sprintf("%-17s %s", label, description)
			}
			b.WriteString(style.Render(prefix+label) + "\n")
		}
	}

	line := " " + strings.Repeat("─", max(1, a.width-2))
	b.WriteString(line + "\n")
	b.WriteString(a.input.View() + "\n")
	b.WriteString(line + "\n")
	b.WriteString(a.infoBar())

	return clampLines(a.width, b.String())
}

func (a *App) refreshSnapshot() {
	snapshot := a.session.Snapshot()
	a.agentStatus = snapshot.AgentStatus
	a.messages = append([]Message(nil), snapshot.Messages...)
	a.pendingTool = snapshot.PendingTool
	if snapshot.PendingPermission != nil {
		a.pendingRequest = *snapshot.PendingPermission
	} else {
		a.pendingRequest = PermissionRequest{}
	}
	a.streamingMessage = snapshot.StreamingMessage
	// Match the notification path: entering WaitingApproval advances the
	// batch index in the same committed transition, so it is already one-based.
	a.pendingToolIndex = snapshot.PendingToolBatchIndex
	a.pendingToolTotal = snapshot.PendingToolBatchTotal
}

func (a App) renderMarkdown(content string) string {
	if a.styles.MarkdownRenderer == nil {
		return content
	}
	out, err := a.styles.MarkdownRenderer.Render(content)
	if err != nil {
		return content
	}
	return strings.TrimSpace(out)
}

type toolDisplayGroup struct {
	verb  string
	kind  string
	items []string
}

func toolGroups(calls []*ToolCall) []toolDisplayGroup {
	groups := make([]toolDisplayGroup, 0, len(calls))
	for _, call := range calls {
		verb, kind, items := toolDisplay(call)
		if len(groups) > 0 && groups[len(groups)-1].verb == verb && groups[len(groups)-1].kind == kind {
			groups[len(groups)-1].items = append(groups[len(groups)-1].items, items...)
			continue
		}
		groups = append(groups, toolDisplayGroup{verb: verb, kind: kind, items: items})
	}
	return groups
}

func toolDisplay(call *ToolCall) (string, string, []string) {
	args := map[string]any{}
	_ = json.Unmarshal([]byte(call.Input), &args)
	value := func(key string) string {
		text, _ := args[key].(string)
		return text
	}
	item := func(value, fallback string) []string {
		if value == "" {
			value = fallback
		}
		return []string{value}
	}
	switch call.Name {
	case "read_file":
		return "Read", "files", item(value("path"), call.Name)
	case "write_file":
		return "Edited", "files", item(value("path"), call.Name)
	case "apply_patch":
		return "Edited", "files", item(value("path"), call.Name)
	case "go_test":
		packages := stringSlice(args["packages"])
		if len(packages) == 0 {
			packages = []string{"./..."}
		}
		return "Ran", "commands", []string{"go test " + strings.Join(packages, " ")}
	case "run_command", "bash":
		return "Ran", "commands", item(value("command"), call.Name)
	case "search":
		return "Searched", "queries", item(value("query"), call.Name)
	case "web_search":
		return "Searched", "queries", item(value("query"), call.Name)
	case "browser_fetch":
		return "Fetched", "pages", item(value("url"), call.Name)
	case "list_files":
		return "Listed", "paths", item(value("path"), ".")
	case "format":
		files := stringSlice(args["files"])
		if len(files) == 0 {
			files = []string{call.Name}
		}
		return "Formatted", "files", files
	case "git_status":
		return "Ran", "commands", []string{"git status --short"}
	case "git_diff":
		return "Ran", "commands", []string{"git diff"}
	default:
		return "Called", "tools", []string{call.Name}
	}
}

func stringSlice(value any) []string {
	values, _ := value.([]any)
	result := make([]string, 0, len(values))
	for _, value := range values {
		if text, ok := value.(string); ok {
			result = append(result, text)
		}
	}
	return result
}

func toolGroupSummary(group toolDisplayGroup) string {
	if len(group.items) == 1 {
		return group.verb + " " + group.items[0]
	}
	return fmt.Sprintf("%s %d %s", group.verb, len(group.items), group.kind)
}

func (a App) renderToolCalls(calls []*ToolCall, expanded bool) string {
	var blocks []string
	for _, group := range toolGroups(calls) {
		block := a.styles.ToolLabel.Render("● " + toolGroupSummary(group))
		if expanded {
			for index, item := range group.items {
				branch := "├"
				if index == len(group.items)-1 {
					branch = "└"
				}
				block += "\n" + a.styles.Footer.Render("  "+branch+" "+item)
			}
		}
		blocks = append(blocks, block)
	}
	return strings.Join(blocks, "\n")
}

func (a App) renderMessage(msg Message) string {
	return a.renderMessageWithTools(msg, false)
}

func (a App) renderMessageWithTools(msg Message, expanded bool) string {
	var b strings.Builder
	width := a.width
	if width <= 0 {
		width = 80
	}
	wrap := func(content string, indent int) string {
		return lipgloss.NewStyle().PaddingLeft(indent).Render(ansi.Wrap(strings.TrimSpace(content), max(1, width-indent), " "))
	}
	if msg.Role == "user" {
		b.WriteString(a.styles.UserLabel.Render("❯ ") + msg.Content)
		return wrap(b.String(), 1)
	}
	if msg.Content != "" {
		if msg.Role == "assistant" {
			b.WriteString(a.renderMarkdown(msg.Content))
		}
	}
	if len(msg.ToolCalls) > 0 {
		if b.Len() > 0 {
			b.WriteByte('\n')
		}
		b.WriteString(a.renderToolCalls(msg.ToolCalls, expanded))
	}
	for _, attachment := range msg.Attachments {
		b.WriteString("\n" + a.styles.Status.Render("  attachment: "+attachment.Name+" ("+attachment.MIME+")"))
	}
	return wrap(b.String(), 0)
}

func (a App) renderCommittedMessage(msg Message, toolsExpanded, thinkingExpanded bool) string {
	content := a.renderMessageWithTools(msg, toolsExpanded)
	if msg.Role != RoleAssistant {
		return content
	}
	thinking := a.styles.Thinking.Render("Thinking...")
	if thinkingExpanded && strings.TrimSpace(msg.ReasoningContent) != "" {
		wrapped := ansi.Wrap(strings.TrimSpace(msg.ReasoningContent), max(1, a.width-4), " ")
		lines := strings.Split(wrapped, "\n")
		for index, line := range lines {
			prefix := "    "
			if index == 0 {
				prefix = "  └ "
			}
			thinking += "\n" + a.styles.Thinking.Render(prefix+line)
		}
	}
	if strings.TrimSpace(content) == "" {
		return thinking
	}
	return thinking + "\n" + content
}

func (a App) renderTranscript() string {
	latestTool := -1
	latestThinking := -1
	for index, message := range a.messages {
		if len(message.ToolCalls) > 0 {
			latestTool = index
		}
		if message.Role == RoleAssistant && strings.TrimSpace(message.ReasoningContent) != "" {
			latestThinking = index
		}
	}
	blocks := []string{a.welcomeString()}
	for index, message := range a.messages {
		toolsExpanded := a.expandAllTools || a.expandLatestTools && index == latestTool
		thinkingExpanded := a.expandAllThink || a.expandLatestThink && index == latestThinking
		if content := a.renderCommittedMessage(message, toolsExpanded, thinkingExpanded); strings.TrimSpace(content) != "" {
			blocks = append(blocks, content)
		}
	}
	return strings.Join(blocks, "\n")
}

func (a App) streamingView() string {
	if a.streamingMessage == nil {
		if a.agentStatus.Busy {
			return a.styles.Thinking.Render("Thinking...")
		}
		return ""
	}
	if a.streamingMessage.Content == "" && a.streamingMessage.ReasoningContent != "" {
		return a.styles.Thinking.Render("Thinking...")
	}
	return a.renderMessage(*a.streamingMessage)
}

func (a App) printCommand(content string) tea.Cmd {
	if strings.TrimSpace(content) == "" {
		return nil
	}
	print := a.printOutput
	if print == nil {
		print = func(content string) tea.Cmd { return tea.Println(content) }
	}
	return print(strings.TrimRight(content, "\n"))
}

func displayCWD(cwd string) string {
	if home, err := os.UserHomeDir(); err == nil {
		return strings.Replace(cwd, home, "~", 1)
	}
	return cwd
}

func (a *App) queueOutput(content string) {
	if strings.TrimSpace(content) != "" {
		a.commandOutput = content
	}
}

func (a *App) takeOutput() string {
	content := a.commandOutput
	a.commandOutput = ""
	return content
}

func divider(label string) string {
	return "── " + label + " ──"
}

func compactStatus(value string, maxLines int) string {
	lines := strings.Split(value, "\n")
	if len(lines) <= maxLines {
		return value
	}
	return strings.Join(lines[:maxLines], "\n") + fmt.Sprintf("\n… %d more lines", len(lines)-maxLines)
}
