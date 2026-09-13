package composer

import (
	"fmt"
	"strings"

	"github.com/charmbracelet/bubbles/textarea"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

type Command struct {
	Name        string
	Description string
}

type IntentKind uint8

const (
	NoIntent IntentKind = iota
	Submit
	Queue
	Steer
	Clear
)

type Intent struct {
	Kind IntentKind
	Text string
}

type Model struct {
	input          textarea.Model
	history        []string
	historyIndex   int
	historyDraft   string
	queued         []string
	commands       []Command
	selection      int
	turnRunning    bool
	compactPalette bool
}

func New(commands []Command) Model {
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
	return Model{input: input, commands: normalizeCommands(commands)}
}

func (m Model) Init() tea.Cmd { return m.input.Cursor.BlinkCmd() }

func (m *Model) SetWidth(width int) { m.input.SetWidth(max(1, width-4)) }

func (m *Model) SetCompactPalette(compact bool) { m.compactPalette = compact }

func (m *Model) SetTurnRunning(running bool) { m.turnRunning = running }

func (m Model) Value() string { return m.input.Value() }

func (m *Model) ClearInput() {
	m.input.SetValue("")
	m.resizeInput()
}

func (m *Model) ClearQueue() { m.queued = nil }

func (m *Model) Enqueue(text string) { m.queued = append(m.queued, text) }

func (m *Model) Prepend(text string) { m.queued = append([]string{text}, m.queued...) }

func (m *Model) NextQueued() (string, bool) {
	if len(m.queued) == 0 {
		return "", false
	}
	value := m.queued[0]
	m.queued = m.queued[1:]
	return value, true
}

func (m Model) Update(message tea.Msg) (Model, *Intent, tea.Cmd) {
	key, ok := message.(tea.KeyMsg)
	if !ok {
		var command tea.Cmd
		m.input, command = m.input.Update(message)
		m.resizeInput()
		return m, nil, command
	}

	switch key.String() {
	case "esc", "ctrl+u":
		if m.input.Value() == "" {
			return m, nil, nil
		}
		m.ClearInput()
		m.historyIndex = len(m.history)
		m.historyDraft = ""
		return m, &Intent{Kind: Clear}, nil
	case "ctrl+j", "shift+enter", "alt+enter":
		var command tea.Cmd
		m.input, command = m.input.Update(tea.KeyMsg{Type: tea.KeyEnter})
		m.resizeInput()
		return m, nil, command
	case "tab":
		if m.turnRunning {
			return m.action(Queue)
		}
		if m.completeSelected() || m.completeUnique() {
			return m, nil, nil
		}
	case "up":
		if matches := m.matches(); len(matches) > 0 {
			if m.selection > 0 {
				m.selection--
			}
			return m, nil, nil
		}
		if !strings.Contains(m.input.Value(), "\n") && m.historyIndex > 0 {
			if m.historyIndex == len(m.history) {
				m.historyDraft = m.input.Value()
			}
			m.historyIndex--
			m.input.SetValue(m.history[m.historyIndex])
			m.resizeInput()
			m.input.CursorEnd()
			return m, nil, nil
		}
	case "down":
		if matches := m.matches(); len(matches) > 0 {
			if m.selection < len(matches)-1 {
				m.selection++
			}
			return m, nil, nil
		}
		if !strings.Contains(m.input.Value(), "\n") {
			if m.historyIndex < len(m.history)-1 {
				m.historyIndex++
				m.input.SetValue(m.history[m.historyIndex])
				m.resizeInput()
				m.input.CursorEnd()
				return m, nil, nil
			}
			if m.historyIndex == len(m.history)-1 {
				m.historyIndex = len(m.history)
				m.input.SetValue(m.historyDraft)
				m.resizeInput()
				m.input.CursorEnd()
				return m, nil, nil
			}
		}
	case "enter":
		if !m.turnRunning && m.completeSelected() {
			return m, nil, nil
		}
		if m.turnRunning {
			return m.action(Steer)
		}
		return m.action(Submit)
	}

	var command tea.Cmd
	m.selection = 0
	m.input, command = m.input.Update(message)
	m.resizeInput()
	return m, nil, command
}

func (m Model) View() string {
	var sections []string
	if queue := m.queueView(); queue != "" {
		sections = append(sections, queue)
	}
	if palette := m.paletteView(); palette != "" && !m.turnRunning {
		sections = append(sections, palette)
	}
	line := " " + strings.Repeat("─", max(1, m.input.Width()+2))
	sections = append(sections, line+"\n"+m.input.View()+"\n"+line)
	return strings.Join(sections, "\n")
}

func (m Model) action(kind IntentKind) (Model, *Intent, tea.Cmd) {
	text := strings.TrimSpace(m.input.Value())
	if text == "" {
		return m, nil, nil
	}
	m.remember(text)
	return m, &Intent{Kind: kind, Text: text}, nil
}

func (m *Model) remember(text string) {
	if len(m.history) == 0 || m.history[len(m.history)-1] != text {
		m.history = append(m.history, text)
	}
	m.historyIndex = len(m.history)
	m.historyDraft = ""
}

func (m *Model) resizeInput() {
	height := strings.Count(m.input.Value(), "\n") + 1
	m.input.SetHeight(min(5, height))
}

func (m *Model) completeSelected() bool {
	matches := m.matches()
	if len(matches) == 0 {
		return false
	}
	if m.selection >= len(matches) {
		m.selection = len(matches) - 1
	}
	selected := matches[m.selection].Name
	if m.input.Value() == selected {
		return false
	}
	m.input.SetValue(selected)
	m.input.CursorEnd()
	m.selection = 0
	m.resizeInput()
	return true
}

func (m *Model) completeUnique() bool {
	matches := m.matches()
	if len(matches) != 1 || matches[0].Name == m.input.Value() {
		return false
	}
	m.input.SetValue(matches[0].Name)
	m.input.CursorEnd()
	m.selection = 0
	m.resizeInput()
	return true
}

func (m Model) matches() []Command {
	value := m.input.Value()
	if !strings.HasPrefix(value, "/") || strings.ContainsAny(value, " \t\n") {
		return nil
	}
	var matches []Command
	for _, command := range m.commands {
		if strings.HasPrefix(command.Name, value) {
			matches = append(matches, command)
		}
	}
	return matches
}

func (m Model) queueView() string {
	if len(m.queued) == 0 {
		return ""
	}
	style := lipgloss.NewStyle().Foreground(lipgloss.Color("6")).Italic(true)
	footer := lipgloss.NewStyle().Foreground(lipgloss.Color("8")).Italic(true)
	lines := []string{style.Render(fmt.Sprintf(" Queued (%d)", len(m.queued)))}
	limit := min(3, len(m.queued))
	if m.compactPalette {
		limit = 0
	}
	for index := 0; index < limit; index++ {
		preview := strings.Join(strings.Fields(m.queued[index]), " ")
		if len([]rune(preview)) > 72 {
			preview = string([]rune(preview)[:72]) + "…"
		}
		lines = append(lines, footer.Render(fmt.Sprintf(" %d. %s", index+1, preview)))
	}
	if remaining := len(m.queued) - limit; remaining > 0 {
		lines = append(lines, footer.Render(fmt.Sprintf(" … %d more", remaining)))
	}
	return strings.Join(lines, "\n")
}

func (m Model) paletteView() string {
	matches := m.matches()
	if len(matches) == 0 {
		return ""
	}
	visible := 6
	if m.compactPalette {
		visible = 3
	}
	start := 0
	if m.selection >= visible {
		start = m.selection - visible + 1
	}
	end := min(start+visible, len(matches))
	footer := lipgloss.NewStyle().Foreground(lipgloss.Color("8")).Italic(true)
	selected := lipgloss.NewStyle().Foreground(lipgloss.Color("6")).Bold(true)
	lines := make([]string, 0, end-start)
	for index := start; index < end; index++ {
		prefix, style := "  ", footer
		if index == m.selection {
			prefix, style = "› ", selected
		}
		label := matches[index].Name
		if !m.compactPalette {
			label = fmt.Sprintf("%-17s %s", label, matches[index].Description)
		}
		lines = append(lines, style.Render(prefix+label))
	}
	return strings.Join(lines, "\n")
}

func normalizeCommands(commands []Command) []Command {
	return append([]Command(nil), commands...)
}
