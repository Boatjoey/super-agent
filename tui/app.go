package tui

import (
	"context"
	"fmt"
	"os"
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
		a.printCommand(a.welcomeString()),
		a.input.Cursor.BlinkCmd(),
		a.spinner.Tick,
	)
}

func (a App) infoBar() string {
	modelStr := strings.Trim(a.info.Provider+"/"+a.info.ModelName, "/")
	cwdStr := displayCWD(a.info.CWD)
	toolsStr := "tools:on"
	if a.info.NoTools {
		toolsStr = "tools:off"
	}
	approveStr := "mode:" + a.info.PermissionMode
	if approveStr == "mode:" {
		approveStr = "mode:ask"
	}
	sep := a.styles.Footer.Render(" │ ")
	join := func(parts []string) string {
		styled := make([]string, len(parts))
		for i, part := range parts {
			styled[i] = a.styles.Footer.Render(part)
		}
		return strings.Join(styled, sep)
	}
	state := a.agentStatus.Label
	if a.isBusy() {
		state = a.spinner.View() + " " + state
	} else if a.needsInput() {
		state = "✋ " + state
	}
	parts := []string{state, modelStr}
	if cwdStr != "" {
		parts = append(parts, cwdStr)
	}
	parts = append(parts, toolsStr, approveStr)
	line := join(parts)
	if lipgloss.Width(line) > a.width {
		line = join([]string{state, modelStr, approveStr})
	}
	return clampLines(a.width, line)
}

func (a App) isBusy() bool {
	return a.compacting || a.managingMCP || a.agentStatus.Busy
}

func (a App) needsInput() bool {
	return a.agentStatus.AwaitingApproval
}

func (a App) welcomeString() string {
	location := displayCWD(a.info.CWD)
	if location == "" {
		return fmt.Sprintf("Super Agent\n\nWelcome back!\n\n%s", a.info.ModelName)
	}
	return fmt.Sprintf("Super Agent\n\nWelcome back!\n\n%s · %s", a.info.ModelName, location)
}

func (a App) footerView() string {
	var b strings.Builder

	if a.err != "" {
		b.WriteString(a.styles.Error.Render(" !! error: "+a.err) + "\n")
	}

	if a.status != "" {
		b.WriteString(a.styles.Status.Render(" "+compactStatus(a.status, 3)) + "\n")
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
	b.WriteString(line + "\n\n")
	b.WriteString(a.input.View() + "\n\n")
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

func (a App) renderToolCall(tc *ToolCall) string {
	header := a.styles.ToolLabel.Render("● " + tc.Name)
	input := tc.Input
	if len(input) > 200 {
		input = input[:200] + "..."
	}
	body := lipgloss.NewStyle().Foreground(lipgloss.Color("8")).Render("  └ " + input)
	return header + "\n" + body
}

func (a App) renderMessage(msg Message) string {
	var b strings.Builder
	width := a.width - 2
	if width <= 0 {
		width = 80
	}
	wrap := func(content string) string {
		return lipgloss.NewStyle().PaddingLeft(1).Render(ansi.Wrap(strings.TrimSpace(content), max(1, width-1), " "))
	}
	if msg.Role == "user" {
		b.WriteString(a.styles.UserLabel.Render("❯ ") + msg.Content)
		return wrap(b.String())
	}
	if msg.ReasoningContent != "" {
		b.WriteString(a.styles.Thinking.Render("● "+msg.ReasoningContent) + "\n\n")
	}
	if msg.Content != "" {
		if msg.Role == "assistant" {
			b.WriteString(a.renderMarkdown(msg.Content))
		} else {
			content := msg.Content
			if len(content) > 1000 {
				content = content[:1000] + "... (truncated)"
			}
			b.WriteString(a.styles.ToolLabel.Render("● "+msg.ToolName) + "\n  └ " + content)
		}
	}
	for _, tc := range msg.ToolCalls {
		b.WriteString("\n" + a.renderToolCall(tc))
	}
	for _, attachment := range msg.Attachments {
		b.WriteString("\n" + a.styles.Status.Render("  attachment: "+attachment.Name+" ("+attachment.MIME+")"))
	}
	return wrap(b.String())
}

func (a App) streamingView() string {
	if a.streamingMessage == nil {
		return ""
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
