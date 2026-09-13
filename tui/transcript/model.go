package transcript

import (
	"encoding/json"
	"fmt"
	"strings"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/glamour"
	"github.com/charmbracelet/lipgloss"
	"github.com/charmbracelet/x/ansi"
)

type Role string

const RoleAssistant Role = "assistant"

type ToolCall struct{ ID, Name, Input string }

type Attachment struct{ Name, MIME string }

type Message struct {
	Role             Role
	Content          string
	ReasoningContent string
	ToolCallID       string
	ToolName         string
	ToolCalls        []*ToolCall
	Interrupted      bool
	Attachments      []Attachment
}

type Styles struct {
	Status           lipgloss.Style
	UserLabel        lipgloss.Style
	ToolLabel        lipgloss.Style
	Thinking         lipgloss.Style
	Footer           lipgloss.Style
	MarkdownRenderer *glamour.TermRenderer
}

type Intent struct {
	CopyText string
	Error    string
}

type Model struct {
	messages          []Message
	streaming         *Message
	busy              bool
	width             int
	welcome           string
	styles            Styles
	expandLatestTools bool
	expandAllTools    bool
	expandLatestThink bool
	expandAllThink    bool
}

func New(welcome string, styles Styles) Model {
	return Model{welcome: welcome, styles: styles, width: 80}
}

func (m *Model) SetWidth(width int) { m.width = max(1, width) }

func (m *Model) Replace(messages []Message) { m.messages = append([]Message(nil), messages...) }

func (m *Model) Append(message Message) { m.messages = append(m.messages, message) }

func (m *Model) SetStreaming(message *Message) { m.streaming = message }

func (m *Model) ClearStreaming() { m.streaming = nil }

func (m *Model) SetBusy(busy bool) { m.busy = busy }

func (m Model) Update(message tea.KeyMsg) (Model, *Intent, bool) {
	switch message.String() {
	case "ctrl+o":
		m.expandLatestTools = !m.expandLatestTools
		m.expandAllTools = false
		return m, nil, true
	case "alt+o":
		m.expandAllTools = !m.expandAllTools
		m.expandLatestTools = false
		return m, nil, true
	case "ctrl+t":
		m.expandLatestThink = !m.expandLatestThink
		m.expandAllThink = false
		return m, nil, true
	case "alt+t":
		m.expandAllThink = !m.expandAllThink
		m.expandLatestThink = false
		return m, nil, true
	case "ctrl+y":
		for index := len(m.messages) - 1; index >= 0; index-- {
			blocks := ExtractCodeBlocks(m.messages[index].Content)
			if len(blocks) > 0 {
				return m, &Intent{CopyText: blocks[len(blocks)-1]}, true
			}
		}
		return m, &Intent{Error: "No code blocks found to copy"}, true
	default:
		return m, nil, false
	}
}

func (m Model) View() string {
	parts := []string{m.transcriptView()}
	if stream := m.streamingView(); stream != "" {
		parts = append(parts, stream)
	}
	return strings.Join(parts, "\n\n")
}

func ExtractCodeBlocks(content string) []string {
	var blocks []string
	lines := strings.Split(content, "\n")
	inBlock := false
	var current strings.Builder
	for _, line := range lines {
		if strings.HasPrefix(strings.TrimSpace(line), "```") {
			if inBlock {
				blocks = append(blocks, strings.TrimSuffix(current.String(), "\n"))
				current.Reset()
			}
			inBlock = !inBlock
			continue
		}
		if inBlock {
			current.WriteString(line + "\n")
		}
	}
	return blocks
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
	case "write_file", "apply_patch":
		return "Edited", "files", item(value("path"), call.Name)
	case "go_test":
		packages := stringSlice(args["packages"])
		if len(packages) == 0 {
			packages = []string{"./..."}
		}
		return "Ran", "commands", []string{"go test " + strings.Join(packages, " ")}
	case "run_command", "bash":
		return "Ran", "commands", item(value("command"), call.Name)
	case "search", "web_search":
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

func (m Model) renderToolCalls(calls []*ToolCall, expanded bool) string {
	var blocks []string
	for _, group := range toolGroups(calls) {
		summary := group.verb + " " + group.items[0]
		if len(group.items) > 1 {
			summary = fmt.Sprintf("%s %d %s", group.verb, len(group.items), group.kind)
		}
		block := m.styles.ToolLabel.Render("● " + summary)
		if expanded {
			for index, item := range group.items {
				branch := "├"
				if index == len(group.items)-1 {
					branch = "└"
				}
				block += "\n" + m.styles.Footer.Render("  "+branch+" "+item)
			}
		}
		blocks = append(blocks, block)
	}
	return strings.Join(blocks, "\n")
}

func (m Model) renderMessage(message Message, toolsExpanded bool) string {
	var rendered strings.Builder
	wrap := func(content string, indent int) string {
		return lipgloss.NewStyle().PaddingLeft(indent).Render(ansi.Wrap(strings.TrimSpace(content), max(1, m.width-indent), " "))
	}
	if message.Role == "user" {
		return wrap(m.styles.UserLabel.Render("❯ ")+message.Content, 1)
	}
	if message.Role == RoleAssistant && message.Content != "" {
		content := message.Content
		if m.styles.MarkdownRenderer != nil {
			if output, err := m.styles.MarkdownRenderer.Render(content); err == nil {
				content = strings.TrimSpace(output)
			}
		}
		rendered.WriteString(content)
	}
	if len(message.ToolCalls) > 0 {
		if rendered.Len() > 0 {
			rendered.WriteByte('\n')
		}
		rendered.WriteString(m.renderToolCalls(message.ToolCalls, toolsExpanded))
	}
	for _, attachment := range message.Attachments {
		rendered.WriteString("\n" + m.styles.Status.Render("  attachment: "+attachment.Name+" ("+attachment.MIME+")"))
	}
	return wrap(rendered.String(), 0)
}

func (m Model) renderCommitted(message Message, toolsExpanded, thinkingExpanded bool) string {
	content := m.renderMessage(message, toolsExpanded)
	if message.Role != RoleAssistant {
		return content
	}
	thinking := m.styles.Thinking.Render("Thinking...")
	if thinkingExpanded && strings.TrimSpace(message.ReasoningContent) != "" {
		wrapped := ansi.Wrap(strings.TrimSpace(message.ReasoningContent), max(1, m.width-4), " ")
		for index, line := range strings.Split(wrapped, "\n") {
			prefix := "    "
			if index == 0 {
				prefix = "  └ "
			}
			thinking += "\n" + m.styles.Thinking.Render(prefix+line)
		}
	}
	if strings.TrimSpace(content) == "" {
		return thinking
	}
	return thinking + "\n" + content
}

func (m Model) transcriptView() string {
	latestTool, latestThinking := -1, -1
	for index, message := range m.messages {
		if len(message.ToolCalls) > 0 {
			latestTool = index
		}
		if message.Role == RoleAssistant && strings.TrimSpace(message.ReasoningContent) != "" {
			latestThinking = index
		}
	}
	blocks := []string{m.welcome}
	for index, message := range m.messages {
		toolsExpanded := m.expandAllTools || m.expandLatestTools && index == latestTool
		thinkingExpanded := m.expandAllThink || m.expandLatestThink && index == latestThinking
		if content := m.renderCommitted(message, toolsExpanded, thinkingExpanded); strings.TrimSpace(content) != "" {
			blocks = append(blocks, content)
		}
	}
	return strings.Join(blocks, "\n")
}

func (m Model) streamingView() string {
	if m.streaming == nil {
		if m.busy {
			return m.styles.Thinking.Render("Thinking...")
		}
		return ""
	}
	if m.streaming.Content == "" && m.streaming.ReasoningContent != "" {
		return m.styles.Thinking.Render("Thinking...")
	}
	return m.renderMessage(*m.streaming, false)
}
